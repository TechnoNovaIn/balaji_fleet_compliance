"""Challans blueprint handling traffic violation notices, driver tagging, and salary deductions."""
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, flash, redirect, url_for, send_file, abort
from flask_login import login_required, current_user
from sqlalchemy import func
from app.extensions import db
from app.models.challan import Challan
from app.models.vehicle import Vehicle
from app.models.monitoring_log import MonitoringLog
from app.models.audit_log import AuditLog
from app.services.challan_monitor import ChallanMonitorService
from app.services.challan_queries import build_filtered_challans_query
from app.utils.decorators import manager_or_admin_required, roles_required

challans_bp = Blueprint("challans", __name__, url_prefix="/challans")


@challans_bp.route("/", methods=["GET"])
@login_required
def index():
    """Challan management listing with driver, location, and deduction filters."""
    tab_param = request.args.get("tab", "").strip()
    status_filter = request.args.get("status", "").strip()
    vehicle_filter = request.args.get("vehicle_id", type=int)
    deduction_filter = request.args.get("deduction", "").strip()
    sort_by = request.args.get("sort", "").strip()
    search_query = request.args.get("search", "").strip()
    page = request.args.get("page", 1, type=int)

    if tab_param in ("unpaid", "paid", "all"):
        active_tab = tab_param
        if not status_filter:
            status_filter = "" if active_tab == "all" else active_tab
    elif status_filter in ("unpaid", "paid"):
        active_tab = status_filter
    else:
        active_tab = "unpaid"
        status_filter = "unpaid"

    query = build_filtered_challans_query(
        vehicle_id=vehicle_filter,
        status=status_filter,
        deduction=deduction_filter,
        sort_by=sort_by,
        search_query=search_query,
    )

    pagination = query.paginate(page=page, per_page=50, error_out=False)
    challans = pagination.items

    total_count = Challan.query.count()
    unpaid_count = Challan.query.filter(
        Challan.payment_status.in_([Challan.PAYMENT_UNPAID, Challan.PAYMENT_PARTIALLY_PAID])
    ).count()
    paid_count = Challan.query.filter(Challan.payment_status == Challan.PAYMENT_PAID).count()
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
        pagination=pagination,
        total_count=total_count,
        unpaid_count=unpaid_count,
        paid_count=paid_count,
        active_tab=active_tab,
        pending_deduction_count=pending_deduction_count,
        vehicles=vehicles,
        selected_vehicle=selected_vehicle,
        selected_vehicle_id=vehicle_filter,
        selected_status=status_filter,
        selected_deduction=deduction_filter,
        selected_sort=sort_by,
        search_query=search_query,
    )


@challans_bp.route("/<int:challan_id>/tag-driver", methods=["POST"])
@login_required
@manager_or_admin_required
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
@manager_or_admin_required
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
@manager_or_admin_required
def acknowledge(challan_id):
    """Acknowledge an in-app roadside challan alert."""
    challan = db.session.get(Challan, challan_id)
    if challan:
        challan.is_acknowledged = True
        db.session.commit()
        flash(f"Alert for Challan #{challan.challan_number or challan.id} marked as reviewed.", "success")
    return redirect(request.referrer or url_for("challans.index"))


@challans_bp.route("/<int:challan_id>/mark-paid", methods=["POST"])
@login_required
@roles_required("admin", "manager", "accounts")
def mark_paid(challan_id):
    """Mark a challan as Paid / Settled directly from the Traffic Challans page."""
    challan = db.session.get(Challan, challan_id)
    if not challan:
        flash("Challan not found.", "danger")
        return redirect(url_for("challans.index"))

    challan.status = Challan.STATUS_PAID
    challan.payment_status = Challan.PAYMENT_PAID
    challan.is_acknowledged = True
    AuditLog.record(
        action="CHALLAN_MARKED_PAID",
        user=current_user,
        entity_type="Challan",
        entity_id=challan.id,
        details={"challan_number": challan.challan_number, "amount": float(challan.penalty_amount or 0)},
    )
    db.session.commit()
    flash(f"Challan #{challan.challan_number or challan.id} marked as Paid.", "success")
    return redirect(request.referrer or url_for("challans.index"))


@challans_bp.route("/acknowledge-all", methods=["POST"])
@login_required
@manager_or_admin_required
def acknowledge_all():
    """Mark all active alerts as reviewed."""
    Challan.query.filter_by(is_acknowledged=False).update({"is_acknowledged": True})
    db.session.commit()
    flash("All challan alerts have been cleared.", "info")
    return redirect(request.referrer or url_for("challans.index"))


@challans_bp.route("/bulk-action", methods=["POST"])
@login_required
def bulk_action():
    """Perform bulk acknowledge or Excel export on selected challans."""
    challan_ids = request.form.getlist("challan_ids", type=int)
    action = request.form.get("bulk_action", "").strip()

    if not challan_ids:
        flash("Please select at least one challan.", "warning")
        return redirect(request.referrer or url_for("challans.index"))

    if action == "acknowledge":
        if not current_user.has_role("admin", "manager"):
            abort(403)
        updated = Challan.query.filter(Challan.id.in_(challan_ids)).update(
            {"is_acknowledged": True}, synchronize_session=False
        )
        AuditLog.record(
            action="BULK_CHALLANS_ACKNOWLEDGED",
            user=current_user,
            entity_type="Challan",
            details={"count": updated, "challan_ids": challan_ids},
        )
        db.session.commit()
        flash(f"Acknowledged {updated} selected challan alert(s).", "success")
        return redirect(request.referrer or url_for("challans.index"))

    if action == "export_excel":
        from app.models.payment import Payment
        from app.services.excel_reports import generate_challan_checklist_workbook

        selected_challans = (
            Challan.query.filter(Challan.id.in_(challan_ids))
            .order_by(Challan.penalty_amount.desc(), Challan.violation_date.desc())
            .all()
        )
        payments = Payment.query.filter(Payment.challan_id.in_(challan_ids)).all()
        workbook_io = generate_challan_checklist_workbook(
            challans=selected_challans,
            payments=payments,
            generated_by=current_user.full_name,
            filters_summary=f"Selected {len(selected_challans)} Challan(s)",
        )
        AuditLog.record(
            action="EXCEL_REPORT_EXPORTED",
            user=current_user,
            entity_type="Report",
            details={"report_type": "bulk_selected_challans", "row_count": len(selected_challans)},
        )
        db.session.commit()
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        return send_file(
            workbook_io,
            as_attachment=True,
            download_name=f"Balaji_Selected_Challans_{stamp}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    flash("Invalid bulk action requested.", "danger")
    return redirect(request.referrer or url_for("challans.index"))
