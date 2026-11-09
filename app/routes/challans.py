"""Challans blueprint handling traffic violation notices, driver tagging, and salary deductions."""
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from app.extensions import db
from app.models.challan import Challan
from app.models.vehicle import Vehicle
from app.models.monitoring_log import MonitoringLog
from app.models.audit_log import AuditLog
from app.services.challan_monitor import ChallanMonitorService

challans_bp = Blueprint("challans", __name__, url_prefix="/challans")


@challans_bp.route("/", methods=["GET"])
@login_required
def index():
    """Challan management listing with driver, location, and deduction filters."""
    status_filter = request.args.get("status", "").strip()
    vehicle_filter = request.args.get("vehicle_id", type=int)
    deduction_filter = request.args.get("deduction", "").strip()
    search_query = request.args.get("search", "").strip()

    query = Challan.query.join(Vehicle)

    if vehicle_filter:
        query = query.filter(Challan.vehicle_id == vehicle_filter)

    if status_filter == "unpaid":
        query = query.filter(Challan.payment_status.in_([Challan.PAYMENT_UNPAID, Challan.PAYMENT_PARTIALLY_PAID]))
    elif status_filter == "paid":
        query = query.filter(Challan.payment_status == Challan.PAYMENT_PAID)

    if deduction_filter:
        query = query.filter(Challan.deduction_status == deduction_filter)

    if search_query:
        norm_search = Vehicle.normalize_registration(search_query)
        query = query.filter(
            db.or_(
                Challan.challan_number.ilike(f"%{search_query}%"),
                Challan.violation_type.ilike(f"%{search_query}%"),
                Challan.driver_name.ilike(f"%{search_query}%"),
                Challan.trip_reference.ilike(f"%{search_query}%"),
                Challan.violation_location.ilike(f"%{search_query}%"),
                Vehicle.registration_number.ilike(f"%{norm_search}%"),
                Vehicle.display_reg_number.ilike(f"%{search_query}%"),
            )
        )

    challans = query.order_by(Challan.violation_date.desc(), Challan.created_at.desc()).all()

    total_count = Challan.query.count()
    unpaid_count = Challan.query.filter(
        Challan.payment_status.in_([Challan.PAYMENT_UNPAID, Challan.PAYMENT_PARTIALLY_PAID])
    ).count()
    pending_deduction_count = Challan.query.filter(
        Challan.deduction_status == Challan.DEDUCTION_PENDING,
        Challan.driver_name.isnot(None),
        Challan.driver_name != "",
    ).count()

    vehicles = Vehicle.query.filter_by(is_active=True).order_by(Vehicle.display_reg_number).all()
    selected_vehicle = db.session.get(Vehicle, vehicle_filter) if vehicle_filter else None

    return render_template(
        "challans/index.html",
        challans=challans,
        total_count=total_count,
        unpaid_count=unpaid_count,
        pending_deduction_count=pending_deduction_count,
        vehicles=vehicles,
        selected_vehicle=selected_vehicle,
        selected_vehicle_id=vehicle_filter,
        selected_status=status_filter,
        selected_deduction=deduction_filter,
        search_query=search_query,
    )


@challans_bp.route("/<int:challan_id>/tag-driver", methods=["POST"])
@login_required
def tag_driver(challan_id):
    """Assign driver details and update salary deduction status for a challan."""
    challan = db.session.get(Challan, challan_id)
    if not challan:
        flash("Challan not found.", "danger")
        return redirect(url_for("challans.index"))

    driver_name = request.form.get("driver_name", "").strip()
    driver_mobile = request.form.get("driver_mobile", "").strip()
    trip_ref = request.form.get("trip_reference", "").strip()
    location = request.form.get("violation_location", "").strip()
    deduction_status = request.form.get("deduction_status", Challan.DEDUCTION_PENDING).strip()
    deduction_ref = request.form.get("deduction_reference", "").strip()
    deducted_amount = request.form.get("deducted_amount", type=float) or 0.0

    challan.driver_name = driver_name if driver_name else None
    challan.driver_mobile = driver_mobile if driver_mobile else None
    challan.trip_reference = trip_ref if trip_ref else None
    if location:
        challan.violation_location = location
    challan.deduction_status = deduction_status
    challan.deduction_reference = deduction_ref if deduction_ref else None
    challan.deducted_amount = deducted_amount

    if deduction_status == Challan.DEDUCTION_DEDUCTED:
        challan.deducted_at = datetime.now(timezone.utc)

    AuditLog.record(
        action="CHALLAN_DRIVER_TAGGED",
        user=current_user,
        entity_type="Challan",
        entity_id=challan.id,
        details={
            "challan_number": challan.challan_number,
            "driver_name": driver_name,
            "deduction_status": deduction_status,
            "deducted_amount": deducted_amount,
            "deduction_reference": deduction_ref,
        },
    )
    db.session.commit()

    flash(f"Driver '{driver_name or 'N/A'}' & deduction details updated for Challan #{challan.challan_number or challan.id}.", "success")
    return redirect(request.referrer or url_for("challans.index"))


@challans_bp.route("/deductions-ledger", methods=["GET"])
@login_required
def deductions_ledger():
    """Salary & Trip Settlement Ledger showing pending penalty deductions per driver."""
    search_driver = request.args.get("driver", "").strip()

    # Query all challans where a driver has been tagged
    query = Challan.query.join(Vehicle).filter(
        Challan.driver_name.isnot(None),
        Challan.driver_name != "",
    )

    if search_driver:
        query = query.filter(Challan.driver_name.ilike(f"%{search_driver}%"))

    challans = query.order_by(Challan.violation_date.desc()).all()

    # Aggregate summaries per driver
    drivers_summary = {}
    for c in challans:
        dname = c.driver_name
        if dname not in drivers_summary:
            drivers_summary[dname] = {
                "driver_name": dname,
                "driver_mobile": c.driver_mobile or "-",
                "total_violations": 0,
                "total_penalties": 0.0,
                "pending_deductions": 0.0,
                "deducted_amount": 0.0,
                "challans": [],
            }
        drivers_summary[dname]["total_violations"] += 1
        drivers_summary[dname]["total_penalties"] += float(c.penalty_amount or 0.0)
        drivers_summary[dname]["challans"].append(c)

        if c.deduction_status == Challan.DEDUCTION_DEDUCTED:
            drivers_summary[dname]["deducted_amount"] += float(c.deducted_amount or c.penalty_amount or 0.0)
        elif c.deduction_status == Challan.DEDUCTION_PENDING:
            drivers_summary[dname]["pending_deductions"] += float(c.penalty_amount or 0.0)

    return render_template(
        "challans/deductions_ledger.html",
        drivers_summary=list(drivers_summary.values()),
        search_driver=search_driver,
    )


@challans_bp.route("/check-live/<int:vehicle_id>", methods=["POST"])
@login_required
def check_live(vehicle_id):
    """Trigger an on-demand live challan check for a specific vehicle."""
    vehicle = db.session.get(Vehicle, vehicle_id)
    if not vehicle:
        flash("Vehicle not found.", "danger")
        return redirect(url_for("vehicles.index"))

    service = ChallanMonitorService()
    log = service.check_single_vehicle(vehicle, user=current_user)

    if log.status == MonitoringLog.STATUS_SUCCESS:
        if log.challans_found > 0:
            flash(
                f"Live check completed for {vehicle.formatted_registration}: {log.challans_found} new roadside challan(s) detected and alert raised!",
                "warning",
            )
        else:
            flash(
                f"Live check completed for {vehicle.formatted_registration}. Status: Clean/Verified (0 active challans on record).",
                "success",
            )
    elif log.status == MonitoringLog.STATUS_AUTH_ERROR:
        flash(
            f"Live check for {vehicle.formatted_registration}: Masters India Authentication Error ({log.error_details}). Please check your MASTERS_INDIA_API_TOKEN in .env.",
            "danger",
        )
    elif log.error_details and "credentials not configured" in log.error_details.lower():
        flash(
            f"Live check for {vehicle.formatted_registration}: Masters India API credentials not configured in .env. Please set MASTERS_INDIA_API_TOKEN.",
            "warning",
        )
    else:
        flash(
            f"Live check completed for {vehicle.formatted_registration}. Result: {log.status.upper()} ({log.error_details or '0 new challans'}).",
            "info",
        )
    return redirect(request.referrer or url_for("vehicles.index"))


@challans_bp.route("/<int:challan_id>/acknowledge", methods=["POST"])
@login_required
def acknowledge(challan_id):
    """Acknowledge an in-app roadside challan alert."""
    challan = db.session.get(Challan, challan_id)
    if challan:
        challan.is_acknowledged = True
        db.session.commit()
        flash(f"Alert for Challan #{challan.challan_number or challan.id} marked as reviewed.", "success")
    return redirect(request.referrer or url_for("challans.index"))


@challans_bp.route("/acknowledge-all", methods=["POST"])
@login_required
def acknowledge_all():
    """Mark all active alerts as reviewed."""
    Challan.query.filter_by(is_acknowledged=False).update({"is_acknowledged": True})
    db.session.commit()
    flash("All challan alerts have been cleared.", "info")
    return redirect(request.referrer or url_for("challans.index"))


@challans_bp.route("/simulate-live-alert", methods=["POST"])
@login_required
def simulate_live_alert():
    """Simulate a roadside speed camera triggering an instant in-app challan notification with photo evidence."""
    import random
    vehicle = Vehicle.query.filter_by(is_active=True).first()
    if not vehicle:
        flash("No active vehicle found to simulate.", "warning")
        return redirect(url_for("challans.index"))

    timestamp = datetime.now(timezone.utc)
    cnum = f"MH-ECH-LIVE-{random.randint(100000, 999999)}"

    # Alternate between daytime expressway speeding and nighttime intersection
    is_speed = random.choice([True, False])
    if is_speed:
        vtype = "Speed Enforcement Camera (94 km/h in 80 km/h Zone)"
        vloc = "Mumbai-Pune Expressway (KM 42.5 Near Lonavala)"
        auth = "Highway Safety Police Maharashtra"
        img = "/static/images/challan_evidence_1.jpg"
        fine = 2000.00
    else:
        vtype = "No Entry / Red Light Violation (Restricted Hours)"
        vloc = "South Mumbai CST Signal Intersection"
        auth = "Mumbai Traffic Police"
        img = "/static/images/challan_evidence_2.jpg"
        fine = 4000.00

    new_c = Challan(
        vehicle_id=vehicle.id,
        challan_number=cnum,
        violation_type=vtype,
        violation_description="Automated surveillance CCTV camera radar detection for vehicle on the move.",
        violation_location=vloc,
        violation_date=timestamp,
        issuing_authority=auth,
        penalty_amount=fine,
        status=Challan.STATUS_PENDING,
        payment_status=Challan.PAYMENT_UNPAID,
        source="Roadside Automated Camera System",
        evidence_image_url=img,
        is_acknowledged=False,
    )
    db.session.add(new_c)
    db.session.commit()

    flash(
        f"🚨 IN-APP ALERT: Roadside camera detected {vtype} for Truck {vehicle.formatted_registration} at {vloc}! Photo evidence attached.",
        "danger",
    )
    return redirect(url_for("challans.index"))
