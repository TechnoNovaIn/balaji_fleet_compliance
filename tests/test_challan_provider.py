"""Unit and integration tests for Masters India e-Challan API provider and fleet scanning."""
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from app.extensions import db
from app.models.challan import Challan
from app.models.monitoring_log import MonitoringLog
from app.services.challan_provider import (
    MastersIndiaChallanProvider,
    parse_flexible_datetime,
    ProviderResult,
)
from app.services.challan_monitor import ChallanMonitorService


def test_parse_flexible_datetime():
    """Verify robust parsing of Indian traffic portal date formats."""
    d1 = parse_flexible_datetime("02-04-2024 11:19:06")
    assert d1.year == 2024
    assert d1.month == 4
    assert d1.day == 2
    assert d1.hour == 11

    d2 = parse_flexible_datetime("2024-05-15 14:30:00")
    assert d2.year == 2024
    assert d2.month == 5

    d3 = parse_flexible_datetime(None)
    assert isinstance(d3, datetime)


def test_provider_unconfigured():
    """Verify that unconfigured provider with allow_sandbox=False returns unconfigured status."""
    provider = MastersIndiaChallanProvider(api_token="", username="", password="", allow_sandbox=False)
    assert provider.is_configured() is False
    res = provider.check_vehicle("MH12AB1234")
    assert res.status == "unconfigured"
    assert "not configured" in res.error_message


def test_provider_sandbox_simulation():
    """Verify that unconfigured provider with allow_sandbox=True executes realistic simulation."""
    provider = MastersIndiaChallanProvider(api_token="", username="", password="", allow_sandbox=True)
    res = provider.check_vehicle("MH12AB1234")
    assert res.status == "success"
    assert "Sandbox" in res.provider_name


def test_provider_parses_masters_india_payload(app, sample_vehicle):
    """Verify that Masters India JSON response with pending & disposed records parses properly."""
    provider = MastersIndiaChallanProvider(api_token="mock_jwt_token")
    mock_payload = {
        "success": True,
        "message": "Success",
        "data": {
            "response": [
                {
                    "response": {
                        "data": {
                            "Pending_data": [
                                {
                                    "challan_no": "MH12PND202601",
                                    "challan_date_time": "15-10-2026 14:22:10",
                                    "challan_place": "Mumbai-Pune Expressway KM 42",
                                    "fine_imposed": "2000",
                                    "challan_status": "Pending",
                                    "driver_name": "Ramesh Patil",
                                    "evidence_image_url": "https://camera.traffic.gov.in/snap1.jpg",
                                    "offence_details": [
                                        {"name": "Speed Violation", "act": "MV Act 1988 S 183"}
                                    ],
                                }
                            ],
                            "Disposed_data": [
                                {
                                    "challan_no": "MH12DIS202602",
                                    "challan_date_time": "10-09-2026 09:10:00",
                                    "challan_place": "Navi Mumbai Signal 4",
                                    "fine_imposed": "500",
                                    "challan_status": "Disposed",
                                    "driver_name": "Suresh Kale",
                                    "offence_details": [
                                        {"name": "Signal Jump", "act": "MV Act 1988 S 119"}
                                    ],
                                }
                            ],
                        },
                        "status": "200",
                        "message": "Record finds successfully",
                    },
                    "responseStatus": "SUCCESS",
                }
            ]
        },
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload

    with patch("requests.post", return_value=mock_resp):
        res = provider.check_vehicle(sample_vehicle.registration_number)
        assert res.status == "success"
        assert len(res.challans) == 2

        pending = res.challans[0]
        assert pending.challan_number == "MH12PND202601"
        assert pending.penalty_amount == 2000.0
        assert pending.status == "pending"
        assert pending.raw_payload["location"] == "Mumbai-Pune Expressway KM 42"
        assert pending.raw_payload["evidence_image_url"] == "https://camera.traffic.gov.in/snap1.jpg"

        disposed = res.challans[1]
        assert disposed.challan_number == "MH12DIS202602"
        assert disposed.status == "paid"


def test_monitor_service_persists_challan_and_alerts(app, sample_vehicle):
    """Verify that ChallanMonitorService persists new challans and triggers unacknowledged alerts."""
    provider = MastersIndiaChallanProvider(api_token="mock_jwt_token")
    mock_payload = {
        "success": True,
        "data": {
            "response": [
                {
                    "response": {
                        "data": {
                            "Pending_data": [
                                {
                                    "challan_no": "TEST-CH-9999",
                                    "challan_date_time": "20-10-2026 16:00:00",
                                    "challan_place": "Thane Toll Plaza",
                                    "fine_imposed": "1500",
                                    "challan_status": "Pending",
                                    "driver_name": "Ajay Singh",
                                    "offence_details": [
                                        {"name": "Overloading Cargo", "act": "MV Act 1988 S 194"}
                                    ],
                                }
                            ]
                        }
                    }
                }
            ]
        },
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload

    with patch("requests.post", return_value=mock_resp):
        service = ChallanMonitorService(provider=provider)
        log = service.check_single_vehicle(sample_vehicle)

        assert log.status == MonitoringLog.STATUS_SUCCESS
        assert log.challans_found == 1

        saved = Challan.query.filter_by(challan_number="TEST-CH-9999").first()
        assert saved is not None
        assert saved.vehicle_id == sample_vehicle.id
        assert saved.penalty_amount == 1500.0
        assert saved.is_acknowledged is False  # Live alert notification active!
        assert saved.violation_type == "Overloading Cargo"


def test_surepass_provider_parses_payload(app, sample_vehicle):
    """Verify that SurepassChallanProvider correctly queries and parses vehicle challans."""
    from app.services.challan_provider import SurepassChallanProvider
    provider = SurepassChallanProvider(endpoint_url="https://mock.test/api/GetVehicleRCChallanData")

    mock_surepass_data = [
        {
            "Id": 101,
            "VehicleNo": sample_vehicle.registration_number,
            "ChallanNo": "SP-CH-12345",
            "ChallanDate": "2026-03-10",
            "Place": "Bangalore Toll Plaza",
            "Offence": "Speed Limit Exceeded",
            "Amount": "1000",
            "Status": "Pending",
            "State": "KA",
            "Accused": "Balaji Transports",
        },
        {
            "Id": 102,
            "VehicleNo": sample_vehicle.registration_number,
            "ChallanNo": "SP-CH-12346",
            "ChallanDate": "2025-11-20",
            "Place": "Pune Highway",
            "Offence": "Lane Discipline",
            "Amount": "500",
            "Status": "Disposed",
            "State": "MH",
            "Accused": "Balaji Transports",
        },
        {
            "Id": 103,
            "VehicleNo": "OTHER1234",
            "ChallanNo": "SP-CH-99999",
            "ChallanDate": "2025-01-01",
            "Place": "Delhi",
            "Offence": "Red Light",
            "Amount": "1000",
            "Status": "Pending",
            "State": "DL",
            "Accused": "Other",
        }
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_surepass_data

    with patch("requests.get", return_value=mock_resp):
        res = provider.check_vehicle(sample_vehicle.registration_number)
        assert res.status == "success"
        assert res.challans_count == 2
        assert res.challans[0].challan_number == "SP-CH-12345"
        assert res.challans[0].status == "pending"
        assert res.challans[0].penalty_amount == 1000.0
        assert res.challans[1].challan_number == "SP-CH-12346"
        assert res.challans[1].status == "paid"

        # Test with Monitor Service
        service = ChallanMonitorService(provider=provider)
        log = service.check_single_vehicle(sample_vehicle)
        assert log.status == MonitoringLog.STATUS_SUCCESS
        assert log.challans_found == 2

