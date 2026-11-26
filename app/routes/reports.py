"""Reports blueprint for generating and downloading multi-person Excel checklists."""
from datetime import datetime
from flask import Blueprint, render_template, request, send_file
from flask_login import login_required, current_user
from app.extensions import db
from app.models.challan import Challan
from app.models.payment import Payment
from app.models.vehicle import Vehicle
from app.models.audit_log import AuditLog
from app.services.challan_queries import build_filtered_challans_query
from app.services.excel_reports import (
    generate_challan_checklist_workbook,
    generate_vehicle_compliance_workbook,
)

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")


@reports_bp.route("/", methods=["GET"])
@login_required
def index():
    """Excel report builder and one-click multi-person verification downloads."""
    vehicle_id = request.args.get("vehicle_id", type=int)
    status = request.args.get("status", "").strip()
    sort_by = request.args.get("sort", "amount_desc").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    challans = build_filtered_challans_query(
        vehicle_id=vehicle_id,
        status=status,
        sort_by=sort_by,
        date_from=date_from,
        date_to=date_to,
    ).all()

    total_fine = sum(float(c.penalty_amount or 0) for c in challans)
    total_paid = sum(float(c.total_paid or 0) for c in challans)
    total_balance = sum(float(c.remaining_penalty or 0) for c in challans)
    unpaid_count = sum(1 for c in challans if c.payment_status in (Challan.PAYMENT_UNPAID, Challan.PAYMENT_PARTIALLY_PAID))

    vehicles = Vehicle.query.filter_by(is_active=True).order_by(Vehicle.display_reg_number).all()

    return render_template(
        "reports/index.html",
        vehicles=vehicles,
        selected_vehicle_id=vehicle_id,
        selected_status=status,
        selected_sort=sort_by,
        date_from=date_from,
        date_to=date_to,
        matching_count=len(challans),
        unpaid_count=unpaid_count,
        total_fine=total_fine,
        total_paid=total_paid,
        total_balance=total_balance,
    )


@reports_bp.route("/export/challans", methods=["GET"])
@login_required
def export_challans_excel():
    """Generate and download the multi-sheet Challan & Payment Excel Checklist."""
    vehicle_id = request.args.get("vehicle_id", type=int)
    status = request.args.get("status", "").strip()
    sort_by = request.args.get("sort", "amount_desc").strip()
    search_query = request.args.get("search", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    challans = build_filtered_challans_query(
        vehicle_id=vehicle_id,
        status=status,
        sort_by=sort_by,
        search_query=search_query,
        date_from=date_from,
        date_to=date_to,
    ).all()

    challan_ids = [c.id for c in challans]
    payments = (
        Payment.query.filter(Payment.challan_id.in_(challan_ids))
        .order_by(Payment.payment_date.desc())
        .all()
        if challan_ids
        else []
    )

    filter_parts = []
    if vehicle_id:
        v = db.session.get(Vehicle, vehicle_id)
        if v:
            filter_parts.append(f"Vehicle: {v.formatted_registration}")
    if status:
        filter_parts.append(f"Status: {status.title()}")
    if sort_by:
        filter_parts.append(f"Sort: {sort_by}")
    if date_from or date_to:
        filter_parts.append(f"Dates: {date_from or '...'} to {date_to or '...'}")
    if search_query:
        filter_parts.append(f"Search: {search_query}")
    filters_summary = " | ".join(filter_parts) if filter_parts else "All Fleet Challans"

    workbook_io = generate_challan_checklist_workbook(
        challans=challans,
        payments=payments,
        generated_by=current_user.full_name,
        filters_summary=filters_summary,
    )

    AuditLog.record(
        action="EXCEL_REPORT_EXPORTED",
        user=current_user,
        entity_type="Report",
        details={"report_type": "challan_checklist", "row_count": len(challans), "filters": filters_summary},
    )
    db.session.commit()

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return send_file(
        workbook_io,
        as_attachment=True,
        download_name=f"Balaji_Challan_Checklist_{stamp}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@reports_bp.route("/export/vehicles", methods=["GET"])
@login_required
def export_vehicles_excel():
    """Generate and download the Vehicle-Wise Compliance Excel report."""
    vehicles = Vehicle.query.order_by(Vehicle.display_reg_number).all()
    workbook_io = generate_vehicle_compliance_workbook(
        vehicles=vehicles,
        generated_by=current_user.full_name,
    )

    AuditLog.record(
        action="EXCEL_REPORT_EXPORTED",
        user=current_user,
        entity_type="Report",
        details={"report_type": "vehicle_compliance", "row_count": len(vehicles)},
    )
    db.session.commit()

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return send_file(
        workbook_io,
        as_attachment=True,
        download_name=f"Balaji_Vehicle_Compliance_{stamp}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
