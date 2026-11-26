"""Tests for the highest challan amount filter and Excel report generation."""
from datetime import datetime, timezone
from io import BytesIO
from openpyxl import load_workbook
from app.extensions import db
from app.models.challan import Challan


def test_challans_highest_amount_filter(client, admin_user, sample_vehicle):
    """Verify sorting and filtering by highest challan amounts on /challans/."""
    with client.application.app_context():
        c1 = Challan(
            vehicle_id=sample_vehicle.id,
            challan_number="CH-LOW-500",
            violation_type="Parking Violation",
            violation_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
            penalty_amount=500.00,
            payment_status=Challan.PAYMENT_UNPAID,
        )
        c2 = Challan(
            vehicle_id=sample_vehicle.id,
            challan_number="CH-HIGH-12000",
            violation_type="Overloading",
            violation_date=datetime(2026, 10, 2, tzinfo=timezone.utc),
            penalty_amount=12000.00,
            payment_status=Challan.PAYMENT_UNPAID,
        )
        c3 = Challan(
            vehicle_id=sample_vehicle.id,
            challan_number="CH-MID-6000",
            violation_type="Signal Jump",
            violation_date=datetime(2026, 10, 3, tzinfo=timezone.utc),
            penalty_amount=6000.00,
            payment_status=Challan.PAYMENT_UNPAID,
        )
        db.session.add_all([c1, c2, c3])
        db.session.commit()

    client.post("/auth/login", data={"username": "admin_ceo", "password": "SecureAdmin#2026"})

    # Sort by highest amount
    resp = client.get("/challans/?sort=amount_desc")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert html.index("CH-HIGH-12000") < html.index("CH-MID-6000") < html.index("CH-LOW-500")

    # Filter >= 5000
    resp_5k = client.get("/challans/?sort=high_5000")
    assert resp_5k.status_code == 200
    html_5k = resp_5k.data.decode("utf-8")
    assert "CH-HIGH-12000" in html_5k
    assert "CH-MID-6000" in html_5k
    assert "CH-LOW-500" not in html_5k

    # Filter >= 10000
    resp_10k = client.get("/challans/?sort=high_10000")
    assert resp_10k.status_code == 200
    html_10k = resp_10k.data.decode("utf-8")
    assert "CH-HIGH-12000" in html_10k
    assert "CH-MID-6000" not in html_10k


def test_excel_reports_download(client, admin_user, sample_vehicle, sample_challan):
    """Verify /reports/ and Excel (.xlsx) downloads for challans and vehicles."""
    client.post("/auth/login", data={"username": "admin_ceo", "password": "SecureAdmin#2026"})

    resp_page = client.get("/reports/")
    assert resp_page.status_code == 200
    assert b"Custom Excel Checklist Builder" in resp_page.data

    # Download challan checklist Excel
    resp_xlsx = client.get("/reports/export/challans?sort=amount_desc")
    assert resp_xlsx.status_code == 200
    assert "spreadsheetml.sheet" in resp_xlsx.content_type

    wb = load_workbook(BytesIO(resp_xlsx.data))
    assert wb.sheetnames == ["Summary", "Challan Checklist", "Payment Settlements"]
    checklist_ws = wb["Challan Checklist"]
    headers = [cell.value for cell in checklist_ws[1]]
    assert "Checked By (Sign-off)" in headers
    assert "Reviewer Remarks" in headers
    assert checklist_ws.cell(row=2, column=5).value == sample_challan.challan_number

    # Download vehicle compliance Excel
    resp_v = client.get("/reports/export/vehicles")
    assert resp_v.status_code == 200
    wb_v = load_workbook(BytesIO(resp_v.data))
    assert wb_v.sheetnames == ["Vehicle Compliance"]
    assert wb_v["Vehicle Compliance"].cell(row=2, column=2).value == sample_vehicle.formatted_registration


def test_format_inr_indian_grouping():
    """Verify Indian Rupee formatting uses lakhs/crores grouping."""
    from app import format_inr

    assert format_inr(0) == "₹0.00"
    assert format_inr(500) == "₹500.00"
    assert format_inr(2000) == "₹2,000.00"
    assert format_inr(123456.78) == "₹1,23,456.78"
    assert format_inr(10000000) == "₹1,00,00,000.00"
    assert format_inr(-15000.5) == "-₹15,000.50"


def test_is_safe_redirect_url(app):
    """Verify open redirect protection rejects external and javascript: URLs."""
    from app.routes.auth import is_safe_redirect_url

    with app.test_request_context("/", base_url="http://localhost:9000"):
        assert is_safe_redirect_url("/challans/") is True
        assert is_safe_redirect_url("http://localhost:9000/reports/") is True
        assert is_safe_redirect_url("https://evil.example.com/phish") is False
        assert is_safe_redirect_url("javascript:alert(1)") is False

