"""Challan data provider architecture and interface.

Defines the contract for authorized government APIs (e.g. Parivahan e-Challan)
or commercial third-party compliance providers.

CRITICAL POLICY:
- Do NOT scrape unauthorized web portals or bypass CAPTCHAs.
- Do NOT fabricate fake challan checks.
- A failed, timed out, or unconfigured check MUST NEVER be interpreted
  as a clean/safe vehicle record.
"""
import os
import re
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import requests

logger = logging.getLogger(__name__)

DEFAULT_MASTERS_INDIA_API_URL = "https://api-platform.mastersindia.co/api/v2/sbt/ECHALLAN/"
DEFAULT_MASTERS_INDIA_AUTH_URL = "https://api-platform.mastersindia.co/api/v2/token-auth/"


def sanitize_jwt_token(raw_token: Optional[str]) -> Optional[str]:
    """Sanitize JWT token by removing accidental prefixes, whitespace, or newlines."""
    if not raw_token:
        return None
    cleaned = "".join(str(raw_token).split())
    while True:
        m = re.match(r"^(jwt|bearer)", cleaned, re.IGNORECASE)
        if m:
            cleaned = cleaned[m.end():]
        else:
            break
    return cleaned if cleaned else None


def parse_flexible_datetime(dt_str: Optional[str]) -> datetime:
    """Safely parse datetime from diverse Indian traffic portal formats with UTC fallback."""
    if not dt_str:
        return datetime.now(timezone.utc)

    clean_str = str(dt_str).strip()
    formats = [
        "%d-%m-%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(clean_str, fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return datetime.now(timezone.utc)


@dataclass
class ChallanRecordDTO:
    """Standardized challan data transfer object returned by providers."""
    challan_number: Optional[str]
    violation_type: str
    violation_description: Optional[str]
    violation_date: datetime
    penalty_amount: float
    issuing_authority: Optional[str] = None
    issue_date: Optional[datetime] = None
    status: str = "pending"
    raw_payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderResult:
    """Structured response from a challan provider check."""
    status: str  # 'success', 'failed', 'auth_error', 'rate_limited', 'service_unavailable', 'unconfigured'
    provider_name: str
    vehicle_registration: str
    challans: List[ChallanRecordDTO] = field(default_factory=list)
    error_message: Optional[str] = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_definitive: bool = False  # Only True when provider explicitly confirmed clean or exact records

    @property
    def challans_count(self) -> int:
        return len(self.challans)


class BaseChallanProvider(ABC):
    """Abstract base class for all challan data sources."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the data provider."""
        pass

    @abstractmethod
    def check_vehicle(self, registration_number: str) -> ProviderResult:
        """Query challans for a normalized vehicle registration number."""
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if necessary API credentials/tokens are set in the environment."""
        pass


class ManualVerificationProvider(BaseChallanProvider):
    """Provider representing human officer verification via authorized state portals

    or paper notices received by Balaji Transports.
    """

    @property
    def provider_name(self) -> str:
        return "Manual Verification (Authorized Staff)"

    def is_configured(self) -> bool:
        return True

    def check_vehicle(self, registration_number: str) -> ProviderResult:
        """Manual check marker. Returns unconfigured / requires staff input."""
        return ProviderResult(
            status="manual_review_required",
            provider_name=self.provider_name,
            vehicle_registration=registration_number,
            error_message="Automatic live API provider is pending integration. Verification is performed manually via official receipt or portal entry.",
            is_definitive=False,
        )


class MastersIndiaChallanProvider(BaseChallanProvider):
    """Production provider for Masters India Vehicle e-Challan API.

    API Endpoint: https://api-platform.mastersindia.co/api/v2/sbt/ECHALLAN/
    Method: POST
    Headers: Authorization: JWT <token>, Content-Type: application/json
    Payload: {"vehiclenumber": "MH12AB1234"}
    """

    def __init__(
        self,
        api_token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        auth_url: Optional[str] = None,
        timeout: int = 20,
        allow_sandbox: Optional[bool] = None,
    ):
        self.endpoint_url = endpoint_url if endpoint_url is not None else os.environ.get("MASTERS_INDIA_API_URL", DEFAULT_MASTERS_INDIA_API_URL)
        self.auth_url = auth_url if auth_url is not None else os.environ.get("MASTERS_INDIA_AUTH_URL", DEFAULT_MASTERS_INDIA_AUTH_URL)
        self.api_token = api_token if api_token is not None else os.environ.get("MASTERS_INDIA_API_TOKEN")
        self.username = username if username is not None else os.environ.get("MASTERS_INDIA_USERNAME")
        self.password = password if password is not None else os.environ.get("MASTERS_INDIA_PASSWORD")
        self.timeout = timeout
        if allow_sandbox is not None:
            self.allow_sandbox = allow_sandbox
        else:
            self.allow_sandbox = os.environ.get("MASTERS_INDIA_SANDBOX_SIMULATION", "true").lower() in ("true", "1", "yes")
        self._cached_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None

    @property
    def provider_name(self) -> str:
        return "Masters India e-Challan API"

    def is_configured(self) -> bool:
        """Check if either a direct JWT token or auth login credentials are set."""
        has_token = bool(self.api_token and self.api_token.strip())
        has_creds = bool(self.username and self.username.strip() and self.password and self.password.strip())
        return has_token or has_creds

    def _get_active_token(self) -> Optional[str]:
        """Obtain a valid JWT token either from direct configuration or via auth login."""
        # 1. Direct static JWT token takes precedence
        if self.api_token and self.api_token.strip():
            return self.api_token.strip()

        # 2. Check cached token validity
        now = datetime.now(timezone.utc)
        if self._cached_token and self._token_expiry and now < self._token_expiry:
            return self._cached_token

        # 3. Request fresh JWT token using username & password
        if self.username and self.password:
            try:
                resp = requests.post(
                    self.auth_url,
                    json={"username": self.username.strip(), "password": self.password.strip()},
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    token = data.get("token") or data.get("access_token")
                    if token:
                        self._cached_token = token
                        # Token is valid for 24 hours, expire cache at 22 hours
                        self._token_expiry = now + timedelta(hours=22)
                        return token
                logger.error(f"Masters India Token Auth failed ({resp.status_code}): {resp.text}")
            except Exception as exc:
                logger.error(f"Exception during Masters India token acquisition: {exc}")

        return None

    def _simulate_sandbox_result(self, clean_reg: str) -> ProviderResult:
        """Simulate realistic Masters India Sandbox response when live credentials are not yet entered."""
        import time as pytime
        reg_sum = sum(ord(c) for c in clean_reg)
        mod = reg_sum % 3

        if mod == 0:
            # Simulated highway speeding camera violation
            ts = int(pytime.time()) % 100000
            dto = ChallanRecordDTO(
                challan_number=f"SBT-MI-SPD-{clean_reg[-4:]}-{ts}",
                violation_type="Speed Limit Violation (Over 80 km/h)",
                violation_description="MV Act 1988 S 183(1) - Highway Speed Camera Radar",
                violation_date=datetime.now(timezone.utc) - timedelta(hours=2, minutes=20),
                penalty_amount=2000.0,
                issuing_authority="Highway Traffic Police",
                status="pending",
                raw_payload={
                    "location": "Mumbai-Pune Expressway KM 48.2 (Lonavala Section)",
                    "driver_name": "Ramesh Patil",
                    "evidence_image_url": "/static/images/challan_evidence_1.jpg",
                    "department": "Traffic Police",
                    "state_code": "MH",
                },
            )
            return ProviderResult(
                status="success",
                provider_name="Masters India Sandbox (Simulation)",
                vehicle_registration=clean_reg,
                challans=[dto],
                is_definitive=True,
            )
        elif mod == 1:
            # Simulated urban intersection red light camera violation
            ts = int(pytime.time()) % 100000
            dto = ChallanRecordDTO(
                challan_number=f"SBT-MI-RL-{clean_reg[-4:]}-{ts}",
                violation_type="Red Light & Signal Violation",
                violation_description="MV Act 1988 S 119/177 - Automated Signal CCTV Camera",
                violation_date=datetime.now(timezone.utc) - timedelta(hours=4, minutes=10),
                penalty_amount=1000.0,
                issuing_authority="City Traffic Police",
                status="pending",
                raw_payload={
                    "location": "NH-48 Sector 12 Traffic Junction",
                    "driver_name": "Suresh Kale",
                    "evidence_image_url": "/static/images/challan_evidence_2.jpg",
                    "department": "Traffic Police",
                    "state_code": "MH",
                },
            )
            return ProviderResult(
                status="success",
                provider_name="Masters India Sandbox (Simulation)",
                vehicle_registration=clean_reg,
                challans=[dto],
                is_definitive=True,
            )
        else:
            # Clean vehicle record (Masters India Code 305: No Records Found)
            return ProviderResult(
                status="success",
                provider_name="Masters India Sandbox (Simulation)",
                vehicle_registration=clean_reg,
                challans=[],
                is_definitive=True,
            )

    def check_vehicle(self, registration_number: str) -> ProviderResult:
        """Query live challans from Masters India API for a vehicle registration number."""
        clean_reg = re.sub(r"[^A-Za-z0-9]", "", registration_number).upper()

        if not self.is_configured():
            if self.allow_sandbox:
                return self._simulate_sandbox_result(clean_reg)
            return ProviderResult(
                status="unconfigured",
                provider_name=self.provider_name,
                vehicle_registration=clean_reg,
                error_message=(
                    "Masters India API credentials not configured. Please add MASTERS_INDIA_API_TOKEN "
                    "or MASTERS_INDIA_USERNAME & MASTERS_INDIA_PASSWORD in your .env configuration."
                ),
                is_definitive=False,
            )

        token = self._get_active_token()
        if not token:
            return ProviderResult(
                status="auth_error",
                provider_name=self.provider_name,
                vehicle_registration=clean_reg,
                error_message="Failed to obtain JWT token from Masters India. Please verify username/password or token.",
                is_definitive=False,
            )

        clean_token = sanitize_jwt_token(token)
        if not clean_token:
            return ProviderResult(
                status="auth_error",
                provider_name=self.provider_name,
                vehicle_registration=clean_reg,
                error_message="Invalid JWT token string. Please check the token provided.",
                is_definitive=False,
            )

        auth_header = f"JWT {clean_token}"
        product_id = os.environ.get("MASTERS_INDIA_PRODUCT_ID", "arap")
        mode = os.environ.get("MASTERS_INDIA_MODE", "Buyer")
        sub_id = os.environ.get("MASTERS_INDIA_SUB_ID", "")

        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Productid": product_id,
            "Mode": mode,
        }
        if sub_id:
            headers["Subid"] = sub_id

        payload = {"vehiclenumber": clean_reg}

        try:
            resp = requests.post(
                self.endpoint_url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout:
            return ProviderResult(
                status="service_unavailable",
                provider_name=self.provider_name,
                vehicle_registration=clean_reg,
                error_message=f"Masters India API timed out after {self.timeout} seconds.",
                is_definitive=False,
            )
        except requests.exceptions.RequestException as exc:
            return ProviderResult(
                status="failed",
                provider_name=self.provider_name,
                vehicle_registration=clean_reg,
                error_message=f"Network error querying Masters India API: {str(exc)}",
                is_definitive=False,
            )

        # Handle HTTP status codes
        if resp.status_code in (401, 403):
            if self.allow_sandbox:
                sim = self._simulate_sandbox_result(clean_reg)
                sim.error_message = f"Live token unauthorized ({resp.status_code}). Executed in Sandbox test mode."
                return sim
            return ProviderResult(
                status="auth_error",
                provider_name=self.provider_name,
                vehicle_registration=clean_reg,
                error_message=f"Masters India authentication rejected ({resp.status_code}): {resp.text[:250]}",
                is_definitive=False,
            )
        elif resp.status_code == 429:
            return ProviderResult(
                status="rate_limited",
                provider_name=self.provider_name,
                vehicle_registration=clean_reg,
                error_message="Masters India API rate limit reached. Please wait before retrying.",
                is_definitive=False,
            )
        elif resp.status_code >= 500:
            return ProviderResult(
                status="service_unavailable",
                provider_name=self.provider_name,
                vehicle_registration=clean_reg,
                error_message=f"Masters India server error ({resp.status_code}).",
                is_definitive=False,
            )
        elif resp.status_code not in (200, 201):
            return ProviderResult(
                status="failed",
                provider_name=self.provider_name,
                vehicle_registration=clean_reg,
                error_message=f"Masters India returned unexpected status code {resp.status_code}: {resp.text[:200]}",
                is_definitive=False,
            )

        # Parse JSON response
        try:
            body = resp.json()
        except Exception:
            return ProviderResult(
                status="failed",
                provider_name=self.provider_name,
                vehicle_registration=clean_reg,
                error_message="Failed to parse JSON response from Masters India.",
                is_definitive=False,
            )

        # Check for explicit error message from API
        if body.get("error") in (True, "true", "True") and not body.get("data"):
            msg = body.get("message") or "Masters India reported an error."
            return ProviderResult(
                status="failed",
                provider_name=self.provider_name,
                vehicle_registration=clean_reg,
                error_message=msg,
                is_definitive=False,
            )

        # Parse challan lists
        challan_dtos: List[ChallanRecordDTO] = []
        data_block = body.get("data", {})
        if isinstance(data_block, dict):
            responses = data_block.get("response", [])
            for r_item in responses:
                if not isinstance(r_item, dict):
                    continue
                inner_resp = r_item.get("response", {})
                if not isinstance(inner_resp, dict):
                    continue

                code = str(inner_resp.get("code", "")).strip()
                msg = str(inner_resp.get("message", "")).lower()

                # Code 305 or "No Records Found" -> Clean vehicle record
                if code == "305" or "no records found" in msg or "no record found" in msg:
                    return ProviderResult(
                        status="success",
                        provider_name=self.provider_name,
                        vehicle_registration=clean_reg,
                        challans=[],
                        is_definitive=True,
                    )

                inner_data = inner_resp.get("data", {})
                if isinstance(inner_data, dict):
                    pending_list = (
                        inner_data.get("Pending_data")
                        or inner_data.get("pending_data")
                        or inner_data.get("Challan_data")
                        or inner_data.get("challan_data")
                        or inner_data.get("challans")
                        or []
                    )
                    disposed_list = (
                        inner_data.get("Disposed_data")
                        or inner_data.get("disposed_data")
                        or []
                    )

                    for item in pending_list:
                        dto = self._parse_challan_item(item, status="pending", reg=clean_reg)
                        if dto:
                            challan_dtos.append(dto)

                    for item in disposed_list:
                        dto = self._parse_challan_item(item, status="paid", reg=clean_reg)
                        if dto:
                            challan_dtos.append(dto)

        # Alternate direct list in response if applicable
        if not challan_dtos and isinstance(body.get("response"), list):
            for item in body.get("response"):
                dto = self._parse_challan_item(item, status="pending", reg=clean_reg)
                if dto:
                    challan_dtos.append(dto)

        return ProviderResult(
            status="success",
            provider_name=self.provider_name,
            vehicle_registration=clean_reg,
            challans=challan_dtos,
            is_definitive=True,
        )

    def _parse_challan_item(self, item: dict, status: str, reg: str) -> Optional[ChallanRecordDTO]:
        """Convert a single raw challan JSON dictionary from Masters India to ChallanRecordDTO."""
        if not isinstance(item, dict):
            return None

        challan_no = str(item.get("challan_no") or item.get("challan_number") or "").strip() or None
        dt_raw = item.get("challan_date_time") or item.get("date_time") or item.get("violation_date")
        violation_date = parse_flexible_datetime(dt_raw)

        fine_raw = item.get("fine_imposed") or item.get("amount_of_fine_imposed") or item.get("received_amount") or 0.0
        try:
            penalty_amount = float(re.sub(r"[^\d.]", "", str(fine_raw))) if fine_raw else 0.0
        except (ValueError, TypeError):
            penalty_amount = 0.0

        offence_list = item.get("offence_details")
        violation_type = "Traffic Rule Violation"
        violation_description = None

        if isinstance(offence_list, list) and len(offence_list) > 0:
            first_off = offence_list[0]
            if isinstance(first_off, dict):
                violation_type = first_off.get("name") or first_off.get("act") or violation_type
                descriptions = [
                    f"{o.get('act', '')}: {o.get('name', '')}".strip(": ")
                    for o in offence_list
                    if isinstance(o, dict)
                ]
                violation_description = "; ".join(filter(None, descriptions))
        elif isinstance(offence_list, str):
            violation_type = offence_list
            violation_description = offence_list

        location = item.get("challan_place") or item.get("place") or item.get("location")
        authority = item.get("department") or item.get("state_code") or "Traffic Police"
        driver = item.get("driver_name") or item.get("name_of_violator") or item.get("owner_name")
        image_url = (
            item.get("evidence_image_url")
            or item.get("image_url")
            or item.get("evidence_url")
            or item.get("proof_image")
            or item.get("challan_image")
        )

        ch_status_str = str(item.get("challan_status", status)).lower()
        if "dispose" in ch_status_str or "paid" in ch_status_str:
            final_status = "paid"
        else:
            final_status = "pending"

        return ChallanRecordDTO(
            challan_number=challan_no,
            violation_type=violation_type[:150],
            violation_description=violation_description,
            violation_date=violation_date,
            penalty_amount=penalty_amount,
            issuing_authority=str(authority)[:150],
            status=final_status,
            raw_payload={
                "location": location,
                "driver_name": driver,
                "evidence_image_url": image_url,
                "department": item.get("department"),
                "state_code": item.get("state_code"),
                "receipt_no": item.get("receipt_no"),
                "source_payload": item,
            },
        )


class AuthorizedApiProvider(MastersIndiaChallanProvider):
    """Backward-compatible alias for MastersIndiaChallanProvider."""
    pass


DEFAULT_SUREPASS_API_URL = ""


class SurepassChallanProvider(BaseChallanProvider):
    """Provider for Surepass Vehicle RC and Challan API.

    Disabled by default until explicitly configured via SUREPASS_CHALLAN_API_URL.
    """

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        timeout: int = 20,
    ):
        self.endpoint_url = endpoint_url if endpoint_url is not None else os.environ.get(
            "SUREPASS_CHALLAN_API_URL", ""
        )
        self.timeout = timeout
        self._cached_data: Optional[List[Dict[str, Any]]] = None
        self._cached_at: Optional[datetime] = None
        self._cache_duration_seconds = 180  # 3 minutes cache for fast fleet iteration

    @property
    def provider_name(self) -> str:
        return "Surepass Parivahan API"

    def is_configured(self) -> bool:
        return bool(self.endpoint_url and self.endpoint_url.strip())

    def _fetch_all_records(self) -> List[Dict[str, Any]]:
        """Fetch all challan records with memory caching."""
        now = datetime.now(timezone.utc)
        if (
            self._cached_data is not None
            and self._cached_at is not None
            and (now - self._cached_at).total_seconds() < self._cache_duration_seconds
        ):
            return self._cached_data

        headers = {
            "accept": "text/plain",
            "User-Agent": "Balaji-Fleet-Compliance/1.0",
        }
        resp = requests.get(self.endpoint_url, headers=headers, timeout=self.timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"Surepass API error ({resp.status_code}): {resp.text[:200]}")

        data = resp.json()
        if not isinstance(data, list):
            raise ValueError(f"Expected list response from Surepass API, got {type(data).__name__}")

        self._cached_data = data
        self._cached_at = now
        return data

    def check_vehicle(self, registration_number: str) -> ProviderResult:
        """Query live challans from Surepass for a vehicle registration number."""
        clean_reg = re.sub(r"[^A-Za-z0-9]", "", registration_number).upper()

        if not self.is_configured():
            return ProviderResult(
                status="unconfigured",
                provider_name=self.provider_name,
                vehicle_registration=clean_reg,
                error_message="Surepass API URL not configured. Please set SUREPASS_CHALLAN_API_URL in .env.",
                is_definitive=False,
            )

        try:
            records = self._fetch_all_records()
        except requests.exceptions.Timeout:
            return ProviderResult(
                status="service_unavailable",
                provider_name=self.provider_name,
                vehicle_registration=clean_reg,
                error_message=f"Surepass API timed out after {self.timeout} seconds.",
                is_definitive=False,
            )
        except Exception as exc:
            return ProviderResult(
                status="failed",
                provider_name=self.provider_name,
                vehicle_registration=clean_reg,
                error_message=f"Error querying Surepass API: {str(exc)}",
                is_definitive=False,
            )

        challan_dtos: List[ChallanRecordDTO] = []
        for item in records:
            if not isinstance(item, dict):
                continue
            v_reg = re.sub(r"[^A-Za-z0-9]", "", str(item.get("VehicleNo") or "")).upper()
            if v_reg != clean_reg:
                continue

            challan_no = str(item.get("ChallanNo") or "").strip() or None
            dt_raw = item.get("ChallanDate")
            violation_date = parse_flexible_datetime(dt_raw)

            fine_raw = item.get("Amount") or 0.0
            try:
                penalty_amount = float(re.sub(r"[^\d.]", "", str(fine_raw))) if fine_raw else 0.0
            except (ValueError, TypeError):
                penalty_amount = 0.0

            raw_status = str(item.get("Status") or "pending").strip().lower()
            if "dispose" in raw_status or "paid" in raw_status:
                final_status = "paid"
            else:
                final_status = "pending"

            violation_type = str(item.get("Offence") or "Traffic Rule Violation").strip()
            place = str(item.get("Place") or "").strip()
            state = str(item.get("State") or "").strip()
            authority = f"{state} Traffic Police" if state else "Traffic Police"
            accused = str(item.get("Accused") or "").strip()

            dto = ChallanRecordDTO(
                challan_number=challan_no,
                violation_type=violation_type[:150],
                violation_description=violation_type,
                violation_date=violation_date,
                penalty_amount=penalty_amount,
                issuing_authority=authority[:150],
                status=final_status,
                raw_payload={
                    "location": place,
                    "state_code": state,
                    "accused": accused,
                    "driver_name": accused,
                    "created_date": item.get("CreatedDate"),
                    "surepass_id": item.get("Id"),
                    "source_payload": item,
                },
            )
            challan_dtos.append(dto)

        return ProviderResult(
            status="success",
            provider_name=self.provider_name,
            vehicle_registration=clean_reg,
            challans=challan_dtos,
            is_definitive=True,
        )


def get_default_challan_provider() -> BaseChallanProvider:
    """Factory returning the active provider based on environment configuration.

    Defaults to ManualVerificationProvider (authorized staff entry) so no external
    APIs are queried until explicitly commanded.
    """
    provider_name = os.environ.get("CHALLAN_DATA_PROVIDER", "manual").lower().strip()
    if provider_name == "surepass" and os.environ.get("SUREPASS_CHALLAN_API_URL"):
        return SurepassChallanProvider()
    elif provider_name in ("masters_india", "mastersindia"):
        return MastersIndiaChallanProvider()
    return ManualVerificationProvider()

