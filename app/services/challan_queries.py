"""Shared query builder for filtered and sorted Challan listings and exports."""
from datetime import datetime
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.models.challan import Challan
from app.models.vehicle import Vehicle


def build_filtered_challans_query(
    vehicle_id: int | None = None,
    status: str = "",
    deduction: str = "",
    sort_by: str = "",
    search_query: str = "",
    date_from: str = "",
    date_to: str = "",
):
    """Build an eager-loaded, filtered, and sorted SQLAlchemy query for Challan."""
    query = Challan.query.join(Vehicle).options(joinedload(Challan.vehicle))

    if vehicle_id:
        query = query.filter(Challan.vehicle_id == vehicle_id)

    if status == "unpaid":
        query = query.filter(
            Challan.payment_status.in_([Challan.PAYMENT_UNPAID, Challan.PAYMENT_PARTIALLY_PAID])
        )
    elif status == "paid":
        query = query.filter(Challan.payment_status == Challan.PAYMENT_PAID)

    if deduction:
        query = query.filter(Challan.deduction_status == deduction)

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

    if date_from:
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(Challan.violation_date >= dt_from)
        except ValueError:
            pass

    if date_to:
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            query = query.filter(Challan.violation_date <= dt_to)
        except ValueError:
            pass

    if sort_by == "high_5000":
        query = query.filter(Challan.penalty_amount >= 5000)
    elif sort_by == "high_10000":
        query = query.filter(Challan.penalty_amount >= 10000)

    if sort_by in ("amount_desc", "high_5000", "high_10000"):
        query = query.order_by(Challan.penalty_amount.desc(), Challan.violation_date.desc())
    elif sort_by == "amount_asc":
        query = query.order_by(Challan.penalty_amount.asc(), Challan.violation_date.desc())
    else:
        query = query.order_by(Challan.violation_date.desc(), Challan.created_at.desc())

    return query
