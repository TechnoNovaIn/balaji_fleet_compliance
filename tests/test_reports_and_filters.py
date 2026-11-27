"""Tests for the highest challan amount filter and Excel report generation."""
from datetime import datetime, timezone
from io import BytesIO
from openpyxl import load_workbook
from app.extensions import db
from app.models.challan import Challan
from app.models.vehicle import Vehicle


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


def test_bulk_challan_actions_and_signoff_import(client, admin_user, sample_vehicle, sample_challan):
    """Verify bulk acknowledge, bulk Excel export, sign-off re-import, and audit log viewer."""
    client.post("/auth/login", data={"username": "admin_ceo", "password": "SecureAdmin#2026"})

    # Bulk acknowledge
    resp_ack = client.post(
        "/challans/bulk-action",
        data={"challan_ids": [sample_challan.id], "bulk_action": "acknowledge"},
        follow_redirects=True,
    )
    assert resp_ack.status_code == 200
    assert b"Acknowledged 1 selected challan" in resp_ack.data

    # Bulk Excel export
    resp_exp = client.post(
        "/challans/bulk-action",
        data={"challan_ids": [sample_challan.id], "bulk_action": "export_excel"},
    )
    assert resp_exp.status_code == 200
    assert "spreadsheetml.sheet" in resp_exp.content_type

    # Modify exported Excel with Checked By & Reviewer Remarks and re-import
    wb = load_workbook(BytesIO(resp_exp.data))
    ws = wb["Challan Checklist"]
    ws.cell(row=2, column=18, value="Ramesh (Accounts)")
    ws.cell(row=2, column=19, value="Verified with Parivahan receipt")
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    resp_imp = client.post(
        "/reports/import-signoff",
        data={"file": (buf, "reviewed.xlsx")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp_imp.status_code == 200
    assert b"Synced sign-off &amp; reviewer remarks for 1 challan" in resp_imp.data

    with client.application.app_context():
        refreshed = db.session.get(Challan, sample_challan.id)
        assert refreshed.assigned_staff == "Ramesh (Accounts)"
        assert refreshed.notes == "Verified with Parivahan receipt"

    # Audit log viewer
    resp_logs = client.get("/reports/audit-logs")
    assert resp_logs.status_code == 200
    assert b"EXCEL_SIGNOFF_IMPORTED" in resp_logs.data


def test_paid_unpaid_tabs_mark_paid_and_excel_balance(client, admin_user, sample_vehicle, sample_challan):
    """Verify Unpaid/Paid tab separation, Mark Paid action, and Excel Paid balance calculation."""
    client.post("/auth/login", data={"username": "admin_ceo", "password": "SecureAdmin#2026"})

    # Initially unpaid: appears on unpaid tab, not on paid tab
    assert sample_challan.challan_number.encode() in client.get("/challans/?tab=unpaid").data
    assert sample_challan.challan_number.encode() not in client.get("/challans/?tab=paid").data

    # Mark Paid directly
    resp_paid = client.post(f"/challans/{sample_challan.id}/mark-paid", follow_redirects=True)
    assert resp_paid.status_code == 200

    # Now appears on paid tab, not on unpaid tab
    assert sample_challan.challan_number.encode() not in client.get("/challans/?tab=unpaid").data
    assert sample_challan.challan_number.encode() in client.get("/challans/?tab=paid").data

    # Excel export for API-settled Paid challan shows Paid Amount == Fine Amount and Balance Due == 0
    resp_xlsx = client.get("/reports/export/challans")
    wb = load_workbook(BytesIO(resp_xlsx.data))
    ws = wb["Challan Checklist"]
    assert ws.cell(row=2, column=10).value == 2000.0  # Fine Amount
    assert ws.cell(row=2, column=11).value == 2000.0  # Paid Amount
    assert ws.cell(row=2, column=12).value == 0.0     # Balance Due


def test_vehicle_toggle_active_and_sync_excel(client, admin_user, sample_vehicle):
    """Verify vehicle Active/Inactive toggle and Sync Active Fleet Excel upload."""
    import pandas as pd

    client.post("/auth/login", data={"username": "admin_ceo", "password": "SecureAdmin#2026"})

    # Toggle inactive then active
    client.post(f"/vehicles/{sample_vehicle.id}/toggle-active")
    with client.application.app_context():
        assert db.session.get(Vehicle, sample_vehicle.id).is_active is False

    # Upload Excel with a different active vehicle + sync_active=1
    df = pd.DataFrame({"Registration Number": ["KA01AB9999"], "Vehicle Type": ["Truck"]})
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    buf.seek(0)

    resp = client.post(
        "/vehicles/upload",
        data={"file": (buf, "active.xlsx"), "sync_active": "1"},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with client.application.app_context():
        v_new = Vehicle.query.filter_by(registration_number="KA01AB9999").first()
        assert v_new is not None and v_new.is_active is True
        assert db.session.get(Vehicle, sample_vehicle.id).is_active is False

