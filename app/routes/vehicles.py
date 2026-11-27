"""Vehicles blueprint handling fleet management, Excel/CSV imports, and monitoring history."""
import io
import pandas as pd
from datetime import datetime, timezone, date
from flask import Blueprint, render_template, request, flash, redirect, url_for, send_file
from flask_login import login_required, current_user
from app.extensions import db
from app.models.vehicle import Vehicle
from app.models.monitoring_log import MonitoringLog
from app.models.audit_log import AuditLog
from app.services.challan_monitor import ChallanMonitorService
from app.utils.decorators import manager_or_admin_required

vehicles_bp = Blueprint("vehicles", __name__, url_prefix="/vehicles")


from app.services.challan_provider import (
    MastersIndiaChallanProvider,
    SurepassChallanProvider,
    get_default_challan_provider,
)

TOP_15_TEST_VEHICLES = [
    'KA19AA8275', 'KA06AC0186', 'KA06AB2916', 'KA06AC1276',
    'TN18AP2121', 'KA06AB4585', 'KA06AC5357', 'KA06AC1924',
    'KA06AC2410', 'KA06AC4728', 'AP16TE6293', 'KA06AB7874',
    'TS01UA3642', 'TS01UA5252', 'TS01UA5242'
]


@vehicles_bp.route("/scan-fleet", methods=["POST"])
@login_required
@manager_or_admin_required
def scan_fleet():
    """Trigger live challan scan across fleet vehicles."""
    import os
    batch_val = request.form.get("batch_size", "all").strip()
    api_token = request.form.get("api_token", "").strip()

    vehicles_to_check = None
    if batch_val == "all" or not batch_val:
        limit = None
    else:
        try:
            limit = int(batch_val)
        except ValueError:
            limit = None

    if api_token:
        provider = MastersIndiaChallanProvider(api_token=api_token, allow_sandbox=True)
    else:
        provider = get_default_challan_provider()

    service = ChallanMonitorService(provider=provider)
    result = service.check_fleet(vehicles=vehicles_to_check, limit=limit, user=current_user)

    if result["success_count"] > 0:
        flash(
            f"⚡ Fleet scan completed ({provider.provider_name}): {result['success_count']} of {result['total_checked']} vehicles checked. "
            f"{result['challans_added']} live challan(s) detected and recorded.",
            "success",
        )
    else:
        err = result["logs"][0].error_details if result["logs"] else "No vehicles scanned"
        flash(
            f"Fleet scan processed {result['total_checked']} vehicles ({result['failed_count']} errors: {err}).",
            "danger",
        )

    return redirect(url_for("vehicles.index"))


@vehicles_bp.route("/", methods=["GET"])
@login_required
def index():
    """Vehicle fleet listing with filters and search."""
    status_filter = request.args.get("status", "").strip()
    type_filter = request.args.get("type", "").strip()
    search_query = request.args.get("search", "").strip()
    page = request.args.get("page", 1, type=int)

    query = Vehicle.query

    if status_filter == "active":
        query = query.filter(Vehicle.is_active == True)
    elif status_filter == "inactive":
        query = query.filter(Vehicle.is_active == False)

    if type_filter:
        query = query.filter(Vehicle.vehicle_type == type_filter)

    if search_query:
        norm_search = Vehicle.normalize_registration(search_query)
        query = query.filter(
            db.or_(
                Vehicle.registration_number.ilike(f"%{norm_search}%"),
                Vehicle.display_reg_number.ilike(f"%{search_query}%"),
                Vehicle.make_model.ilike(f"%{search_query}%"),
                Vehicle.registered_owner.ilike(f"%{search_query}%"),
            )
        )

    pagination = query.order_by(Vehicle.created_at.desc()).paginate(page=page, per_page=50, error_out=False)
    vehicles = pagination.items
    total_count = Vehicle.query.count()
    active_count = Vehicle.query.filter_by(is_active=True).count()

    return render_template(
        "vehicles/index.html",
        vehicles=vehicles,
        pagination=pagination,
        total_count=total_count,
        active_count=active_count,
        selected_status=status_filter,
        selected_type=type_filter,
        search_query=search_query,
        vehicle_types=Vehicle.VEHICLE_TYPES,
    )


@vehicles_bp.route("/monitoring-history", methods=["GET"])
@login_required
def monitoring_history():
    """View monitoring logs for vehicles checked today and historical attempts."""
    filter_today = request.args.get("today", "1") == "1"

    query = MonitoringLog.query.join(Vehicle, isouter=True)

    if filter_today:
        now_utc = datetime.now(timezone.utc)
        today_start = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc)
        query = query.filter(MonitoringLog.check_start_time >= today_start)

    logs = query.order_by(MonitoringLog.check_start_time.desc()).limit(100).all()

    return render_template(
        "vehicles/monitoring_history.html",
        logs=logs,
        filter_today=filter_today,
    )


@vehicles_bp.route("/template", methods=["GET"])
@login_required
def download_template():
    """Generate and download sample Excel template for bulk vehicle import."""
    sample_data = {
        "Registration Number": ["MH12AB1234", "MH14CD5678", "DL01EF9012", "KA04GH3456"],
        "Vehicle Type": ["Truck", "Truck", "Car", "Bus"],
        "Make & Model": ["Tata Prima 4028.S", "BharatBenz 2823R", "Toyota Innova", "Ashok Leyland 4220"],
        "Registered Owner": ["Balaji Transports Pvt Ltd", "Balaji Transports Pvt Ltd", "Corporate Fleet", "Balaji South Hub"],
        "Department": ["Pune Logistics Hub", "Mumbai Port Division", "Corporate HQ", "Bengaluru Depot"],
    }

    df = pd.DataFrame(sample_data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Fleet_Vehicles")
    output.seek(0)

    return send_file(
        output,
        download_name="Balaji_Fleet_Vehicle_Import_Template.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@vehicles_bp.route("/upload", methods=["POST"])
@login_required
@manager_or_admin_required
def upload_excel():
    """Bulk import vehicles from Excel (.xlsx/.xls) or CSV."""
    if "file" not in request.files:
        flash("No file was uploaded.", "danger")
        return redirect(url_for("vehicles.index"))

    file = request.files["file"]
    if file.filename == "":
        flash("Please select an Excel or CSV file to upload.", "danger")
        return redirect(url_for("vehicles.index"))

    filename = file.filename.lower()
    if not (filename.endswith(".xlsx") or filename.endswith(".xls") or filename.endswith(".csv")):
        flash("Unsupported file format. Please upload an Excel (.xlsx, .xls) or CSV file.", "danger")
        return redirect(url_for("vehicles.index"))

    try:
        if filename.endswith(".csv"):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)

        # Standardize column headers
        col_map = {}
        for c in df.columns:
            cleaned = str(c).strip().lower().replace(" ", "_").replace("&", "").replace("__", "_")
            if "reg" in cleaned or "number" in cleaned or "vehicle_no" in cleaned:
                col_map[c] = "reg_no"
            elif "type" in cleaned:
                col_map[c] = "type"
            elif "make" in cleaned or "model" in cleaned:
                col_map[c] = "make_model"
            elif "owner" in cleaned:
                col_map[c] = "owner"
            elif "dept" in cleaned or "department" in cleaned or "branch" in cleaned or "hub" in cleaned:
                col_map[c] = "department"

        df = df.rename(columns=col_map)

        if "reg_no" not in df.columns:
            flash("Error: Could not find 'Registration Number' column in the uploaded file.", "danger")
            return redirect(url_for("vehicles.index"))

        imported_count = 0
        skipped_count = 0
        reactivated_count = 0
        deactivated_count = 0
        uploaded_norms = set()
        error_rows = []
        sync_active = request.form.get("sync_active") == "1"

        for idx, row in df.iterrows():
            raw_reg = str(row["reg_no"]).strip() if pd.notna(row["reg_no"]) else ""
            if not raw_reg or raw_reg.lower() == "nan":
                continue

            norm_reg = Vehicle.normalize_registration(raw_reg)
            if not norm_reg:
                error_rows.append(f"Row {idx+2}: Invalid registration number '{raw_reg}'")
                continue

            uploaded_norms.add(norm_reg)

            # Check for existing duplicate
            existing = Vehicle.query.filter_by(registration_number=norm_reg).first()
            if existing:
                if sync_active and not existing.is_active:
                    existing.is_active = True
                    reactivated_count += 1
                else:
                    skipped_count += 1
                continue

            # Extract fields
            vtype = str(row["type"]).strip().capitalize() if ("type" in df.columns and pd.notna(row["type"])) else Vehicle.TYPE_TRUCK
            if vtype not in Vehicle.VEHICLE_TYPES:
                vtype = Vehicle.TYPE_TRUCK

            make_model = str(row["make_model"]).strip() if ("make_model" in df.columns and pd.notna(row["make_model"])) else None
            owner = str(row["owner"]).strip() if ("owner" in df.columns and pd.notna(row["owner"])) else "Balaji Transports Pvt Ltd"
            dept = str(row["department"]).strip() if ("department" in df.columns and pd.notna(row["department"])) else None

            veh = Vehicle(
                registration_number=norm_reg,
                display_reg_number=Vehicle.format_registration(norm_reg),
                vehicle_type=vtype,
                make_model=make_model,
                registered_owner=owner,
                department=dept,
                is_active=True,
            )
            db.session.add(veh)
            imported_count += 1

        if sync_active and uploaded_norms:
            deactivated_count = Vehicle.query.filter(
                Vehicle.is_active == True,
                ~Vehicle.registration_number.in_(uploaded_norms),
            ).update({"is_active": False}, synchronize_session=False)

        db.session.commit()

        # Audit log entry
        AuditLog.record(
            action="VEHICLES_EXCEL_IMPORTED",
            user=current_user,
            entity_type="Vehicle",
            entity_id=f"Count: {imported_count}",
            details={
                "file": file.filename,
                "imported": imported_count,
                "skipped_duplicates": skipped_count,
                "reactivated": reactivated_count,
                "deactivated": deactivated_count,
                "sync_active": sync_active,
            },
        )
        db.session.commit()

        msg = f"Excel Import Completed: {imported_count} vehicle(s) successfully registered."
        if skipped_count > 0:
            msg += f" {skipped_count} vehicle(s) skipped as duplicates."
        if reactivated_count > 0:
            msg += f" {reactivated_count} reactivated."
        if deactivated_count > 0:
            msg += f" {deactivated_count} marked Inactive (not in active sheet)."
        flash(msg, "success")

    except Exception as exc:
        db.session.rollback()
        flash(f"Failed to process Excel file: {str(exc)}", "danger")

    return redirect(url_for("vehicles.index"))


@vehicles_bp.route("/<int:vehicle_id>/toggle-active", methods=["POST"])
@login_required
@manager_or_admin_required
def toggle_active(vehicle_id):
    """Toggle a vehicle between Active and Inactive without deleting challan history."""
    vehicle = db.session.get(Vehicle, vehicle_id)
    if not vehicle:
        flash("Vehicle not found.", "danger")
        return redirect(url_for("vehicles.index"))

    vehicle.is_active = not vehicle.is_active
    AuditLog.record(
        action="VEHICLE_STATUS_UPDATED",
        user=current_user,
        entity_type="Vehicle",
        entity_id=vehicle.id,
        details={"registration": vehicle.registration_number, "is_active": vehicle.is_active},
    )
    db.session.commit()
    state_label = "Active" if vehicle.is_active else "Inactive"
    flash(f"Vehicle {vehicle.formatted_registration} marked as {state_label}.", "info")
    return redirect(request.referrer or url_for("vehicles.index"))
