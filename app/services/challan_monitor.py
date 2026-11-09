"""Challan monitoring service.

Coordinates vehicle checks, creates monitoring logs, and updates challan data.
Guarantees that a failed check is never recorded as a clean vehicle.
"""
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from app.extensions import db
from app.models.vehicle import Vehicle
from app.models.challan import Challan
from app.models.monitoring_log import MonitoringLog
from app.models.audit_log import AuditLog
from app.services.challan_provider import (
    BaseChallanProvider,
    MastersIndiaChallanProvider,
    SurepassChallanProvider,
    ManualVerificationProvider,
    get_default_challan_provider,
)


class ChallanMonitorService:
    """Orchestrates challan checking and logging for fleet vehicles."""

    def __init__(self, provider: Optional[BaseChallanProvider] = None):
        # Default to configured provider (Surepass Parivahan API by default)
        self.provider = provider or get_default_challan_provider()

    def check_single_vehicle(self, vehicle: Vehicle, user=None) -> MonitoringLog:
        """Execute a challan compliance check for a specific vehicle and log results."""
        start_time = datetime.now(timezone.utc)

        log = MonitoringLog(
            vehicle_id=vehicle.id,
            check_start_time=start_time,
            data_source=self.provider.provider_name,
            status=MonitoringLog.STATUS_IN_PROGRESS,
            challans_found=0,
        )
        db.session.add(log)
        db.session.commit()

        try:
            result = self.provider.check_vehicle(vehicle.registration_number)
            log.check_completion_time = datetime.now(timezone.utc)
            log.data_source = result.provider_name
            log.challans_found = result.challans_count
            log.error_details = result.error_message

            if result.status == "success":
                log.status = MonitoringLog.STATUS_SUCCESS

                # Persist or update received challans in database
                new_count = 0
                for dto in result.challans:
                    existing = None
                    if dto.challan_number:
                        existing = Challan.query.filter_by(challan_number=dto.challan_number).first()

                    if existing:
                        # Update status if settled/paid
                        if dto.status in ("paid", "disposed"):
                            existing.status = Challan.STATUS_PAID
                            existing.payment_status = Challan.PAYMENT_PAID
                        if dto.raw_payload.get("evidence_image_url"):
                            existing.evidence_image_url = dto.raw_payload.get("evidence_image_url")
                        if dto.raw_payload.get("location"):
                            existing.violation_location = dto.raw_payload.get("location")
                    else:
                        # Create new real-time roadside challan record
                        is_disposed = dto.status in ("paid", "disposed")
                        new_challan = Challan(
                            vehicle_id=vehicle.id,
                            challan_number=dto.challan_number,
                            violation_type=dto.violation_type or "Traffic Rule Violation",
                            violation_description=dto.violation_description,
                            violation_location=dto.raw_payload.get("location") or "Highway / City Camera Point",
                            violation_date=dto.violation_date,
                            penalty_amount=dto.penalty_amount,
                            status=Challan.STATUS_PAID if is_disposed else Challan.STATUS_PENDING,
                            payment_status=Challan.PAYMENT_PAID if is_disposed else Challan.PAYMENT_UNPAID,
                            evidence_image_url=dto.raw_payload.get("evidence_image_url"),
                            is_acknowledged=False,  # Triggers immediate live notification alert
                            driver_name=dto.raw_payload.get("driver_name"),
                            issuing_authority=dto.issuing_authority or "Traffic Police",
                            source=self.provider.provider_name,
                        )
                        db.session.add(new_challan)
                        new_count += 1

                log.challans_found = new_count if new_count > 0 else result.challans_count
                vehicle.updated_at = datetime.now(timezone.utc)

            elif result.status in [
                MonitoringLog.STATUS_RATE_LIMITED,
                MonitoringLog.STATUS_AUTH_ERROR,
                MonitoringLog.STATUS_SERVICE_UNAVAILABLE,
            ]:
                log.status = result.status
            elif result.status in ("unconfigured", "manual_review_required"):
                log.status = MonitoringLog.STATUS_FAILED
            else:
                log.status = MonitoringLog.STATUS_FAILED

            AuditLog.record(
                action="MONITORING_CHECK_EXECUTED",
                user=user,
                entity_type="Vehicle",
                entity_id=vehicle.id,
                details={
                    "registration": vehicle.registration_number,
                    "status": log.status,
                    "provider": log.data_source,
                    "challans_found": log.challans_found,
                    "error": log.error_details,
                },
            )
            db.session.commit()

        except Exception as exc:
            db.session.rollback()
            log.check_completion_time = datetime.now(timezone.utc)
            log.status = MonitoringLog.STATUS_FAILED
            log.error_details = f"Unexpected monitor exception: {str(exc)}"
            db.session.add(log)
            db.session.commit()

        return log

    def check_fleet(
        self,
        vehicles: Optional[List[Vehicle]] = None,
        limit: Optional[int] = None,
        delay_seconds: float = 0.2,
        user=None,
    ) -> Dict[str, Any]:
        """Execute compliance checks across fleet vehicles."""
        if vehicles is None:
            query = Vehicle.query.filter_by(is_active=True).order_by(Vehicle.created_at.desc())
            if limit:
                query = query.limit(limit)
            vehicles = query.all()

        total = len(vehicles)
        success_count = 0
        failed_count = 0
        challans_added = 0
        logs = []

        for idx, vehicle in enumerate(vehicles, start=1):
            log = self.check_single_vehicle(vehicle, user=user)
            logs.append(log)
            if log.status == MonitoringLog.STATUS_SUCCESS:
                success_count += 1
                challans_added += (log.challans_found or 0)
            else:
                failed_count += 1

            if delay_seconds and idx < total:
                time.sleep(delay_seconds)

        return {
            "total_checked": total,
            "success_count": success_count,
            "failed_count": failed_count,
            "challans_added": challans_added,
            "logs": logs,
        }
