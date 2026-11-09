"""Payments blueprint handling payment recording, settlement logs, and reference tracking."""
from datetime import datetime, timezone, date
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app.extensions import db
from app.models.payment import Payment
from app.models.challan import Challan
from app.models.vehicle import Vehicle
from app.models.audit_log import AuditLog

payments_bp = Blueprint("payments", __name__, url_prefix="/payments")


@payments_bp.route("/", methods=["GET"])
@login_required
def index():
    """Payment records listing with filtering by payment mode, vehicle, and search."""
    mode_filter = request.args.get("mode", "").strip()
    vehicle_filter = request.args.get("vehicle_id", type=int)
    search_query = request.args.get("search", "").strip()

    query = Payment.query.join(Challan)

    if mode_filter:
        query = query.filter(Payment.payment_mode == mode_filter)
    if vehicle_filter:
        query = query.filter(Challan.vehicle_id == vehicle_filter)
    if search_query:
        query = query.filter(
            db.or_(
                Payment.payment_reference.ilike(f"%{search_query}%"),
                Challan.challan_number.ilike(f"%{search_query}%"),
            )
        )

    payments = query.order_by(Payment.payment_date.desc(), Payment.created_at.desc()).all()

    # Challans available for payment (unpaid or partially paid)
    pending_challans = Challan.query.filter(
        Challan.payment_status.in_([Challan.PAYMENT_UNPAID, Challan.PAYMENT_PARTIALLY_PAID])
    ).order_by(Challan.violation_date.desc()).all()

    vehicles = Vehicle.query.filter_by(is_active=True).order_by(Vehicle.display_reg_number).all()

    return render_template(
        "payments/index.html",
        payments=payments,
        pending_challans=pending_challans,
        payment_modes=Payment.PAYMENT_MODES,
        vehicles=vehicles,
        selected_mode=mode_filter,
        selected_vehicle_id=vehicle_filter,
        search_query=search_query,
    )


@payments_bp.route("/record", methods=["POST"])
@login_required
def record():
    """Route that receives and processes new payment information."""
    challan_id = request.form.get("challan_id", type=int)
    amount_paid = request.form.get("amount_paid", type=float)
    payment_mode = request.form.get("payment_mode", Payment.MODE_UPI).strip()
    reference_id = request.form.get("reference_id", "").strip()
    payment_date_str = request.form.get("payment_date", "").strip()
    notes = request.form.get("notes", "").strip()

    if not challan_id or not amount_paid or not reference_id:
        flash("Challan, Amount, and Reference ID are required fields.", "danger")
        return redirect(url_for("payments.index"))

    challan = db.session.get(Challan, challan_id)
    if not challan:
        flash("The selected challan could not be found.", "danger")
        return redirect(url_for("payments.index"))

    # Parse payment date or default to today
    try:
        payment_date = datetime.strptime(payment_date_str, "%Y-%m-%d").date() if payment_date_str else date.today()
    except ValueError:
        payment_date = date.today()

    payment = Payment(
        challan_id=challan.id,
        amount_paid=amount_paid,
        payment_date=payment_date,
        payment_mode=payment_mode,
        payment_reference=reference_id,  # Stored as Reference ID
        recorded_by_user_id=current_user.id,
        verification_status=Payment.VERIFICATION_VERIFIED,
        notes=notes,
    )
    db.session.add(payment)
    db.session.flush()

    # Automatically sync challan payment status
    challan.sync_payment_status()

    # Record in audit log
    AuditLog.record(
        action="PAYMENT_RECORDED",
        user=current_user,
        entity_type="Payment",
        entity_id=payment.id,
        details={
            "challan_id": challan.id,
            "vehicle": challan.vehicle.registration_number if challan.vehicle else "N/A",
            "amount": amount_paid,
            "payment_mode": payment_mode,
            "reference_id": reference_id,
        },
    )
    db.session.commit()

    flash(f"Payment of ₹{amount_paid:,.2f} recorded successfully for Challan #{challan.challan_number or challan.id}.", "success")
    return redirect(url_for("payments.index"))
