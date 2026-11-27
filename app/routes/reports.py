"""Reports blueprint for generating and downloading multi-person Excel checklists."""
from datetime import datetime
from flask import Blueprint, render_template, request, send_file, flash, redirect, url_for
from flask_login import login_required, current_user
from openpyxl import load_workbook
from app.extensions import db
from app.models.challan import Challan
from app.models.payment import Payment
from app.models.vehicle import Vehicle
from app.models.audit_log import AuditLog
from app.services.challan_queries import build_filtered_challans_query
from app.utils.decorators import roles_required
from app.services.excel_reports import (
    _challan_financials,
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

    financials = [_challan_financials(c) for c in challans]
    total_fine = sum(f for f, _, _ in financials)
    total_paid = sum(p for _, p, _ in financials)
    total_balance = sum(d for _, _, d in financials)
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


@reports_bp.route("/import-signoff", methods=["POST"])
@login_required
@roles_required("admin", "manager", "accounts")
def import_signoff_excel():
    """Import Checked By (Sign-off) and Reviewer Remarks from a reviewed Excel checklist."""
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename.lower().endswith(".xlsx"):
        flash("Please upload a valid .xlsx Excel checklist file.", "danger")
        return redirect(url_for("reports.index"))

    try:
        wb = load_workbook(uploaded, data_only=True)
    except Exception:
        flash("Could not read the uploaded Excel file. Ensure it is a valid .xlsx workbook.", "danger")
        return redirect(url_for("reports.index"))

    if "Challan Checklist" not in wb.sheetnames:
        flash("Uploaded workbook does not contain a 'Challan Checklist' sheet.", "danger")
        return redirect(url_for("reports.index"))

    ws = wb["Challan Checklist"]
    headers = [str(cell.value).strip() if cell.value is not None else "" for cell in ws[1]]
    col_map = {h: idx for idx, h in enumerate(headers)}

    if "Challan No." not in col_map:
        flash("Missing 'Challan No.' column in 'Challan Checklist' sheet.", "danger")
        return redirect(url_for("reports.index"))

    cno_idx = col_map["Challan No."]
    signoff_idx = col_map.get("Checked By (Sign-off)")
    remarks_idx = col_map.get("Reviewer Remarks")

    updated_count = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        cno_raw = row[cno_idx] if cno_idx < len(row) else None
        if not cno_raw:
            continue
        cno_str = str(cno_raw).strip()
        signoff = str(row[signoff_idx]).strip() if signoff_idx is not None and signoff_idx < len(row) and row[signoff_idx] is not None else ""
        remarks = str(row[remarks_idx]).strip() if remarks_idx is not None and remarks_idx < len(row) and row[remarks_idx] is not None else ""

        if not signoff and not remarks:
            continue

        challan = None
        if cno_str.startswith("ID-") and cno_str[3:].isdigit():
            challan = db.session.get(Challan, int(cno_str[3:]))
        else:
            challan = Challan.query.filter_by(challan_number=cno_str).first()

        if challan:
            if signoff:
                challan.assigned_staff = signoff[:120]
            if remarks:
                challan.notes = remarks
            challan.last_verified_at = datetime.now()
            updated_count += 1

    AuditLog.record(
        action="EXCEL_SIGNOFF_IMPORTED",
        user=current_user,
        entity_type="Report",
        details={"updated_challans": updated_count, "filename": uploaded.filename},
    )
    db.session.commit()
    flash(f"Synced sign-off & reviewer remarks for {updated_count} challan(s) from Excel.", "success")
    return redirect(url_for("reports.index"))


@reports_bp.route("/audit-logs", methods=["GET"])
@login_required
def audit_logs():
    """Browse recent compliance and user activity audit logs."""
    action_filter = request.args.get("action", "").strip()
    page = request.args.get("page", 1, type=int)

    query = AuditLog.query
    if action_filter:
        query = query.filter(AuditLog.action == action_filter)

    pagination = query.order_by(AuditLog.timestamp.desc()).paginate(page=page, per_page=50, error_out=False)
    actions = [row[0] for row in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action).all()]

    return render_template(
        "reports/audit_logs.html",
        logs=pagination.items,
        pagination=pagination,
        actions=actions,
        selected_action=action_filter,
    )
