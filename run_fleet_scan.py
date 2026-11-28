"""Standalone execution runner for Fleet e-Challan API scanning.

Usage:
    # Check top 10 vehicles:
    python run_fleet_scan.py --limit 10

    # Check a specific vehicle:
    python run_fleet_scan.py --vehicle MH12AB1234

    # Check all fleet vehicles:
    python run_fleet_scan.py --all
"""
import sys
import argparse
import time
from app import create_app
from app.models.vehicle import Vehicle
from app.services.challan_provider import (
    ManualVerificationProvider,
    MastersIndiaChallanProvider,
    SurepassChallanProvider,
)
from app.services.challan_monitor import ChallanMonitorService


def resolve_provider(app):
    """Select the active challan provider from app.config['CHALLAN_DATA_PROVIDER']."""
    provider_key = (app.config.get("CHALLAN_DATA_PROVIDER") or "manual").strip().lower()
    if provider_key == "surepass":
        return SurepassChallanProvider(
            endpoint_url=app.config.get("SUREPASS_CHALLAN_API_URL") or None,
        )
    if provider_key in ("masters_india", "mastersindia"):
        return MastersIndiaChallanProvider(
            api_token=app.config.get("MASTERS_INDIA_API_TOKEN"),
            username=app.config.get("MASTERS_INDIA_USERNAME"),
            password=app.config.get("MASTERS_INDIA_PASSWORD"),
            endpoint_url=app.config.get("MASTERS_INDIA_API_URL"),
            auth_url=app.config.get("MASTERS_INDIA_AUTH_URL"),
        )
    return ManualVerificationProvider()


def main():
    parser = argparse.ArgumentParser(description="Balaji Fleet - Live e-Challan Scanner")
    parser.add_argument("--limit", type=int, default=10, help="Number of vehicles to check (default: 10)")
    parser.add_argument("--all", action="store_true", help="Scan all registered fleet vehicles")
    parser.add_argument("--vehicle", type=str, help="Specific vehicle registration number to check")
    parser.add_argument("--delay", type=float, default=0.25, help="Delay in seconds between requests (default: 0.25)")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        provider = resolve_provider(app)
        endpoint = getattr(provider, "endpoint_url", None) or "N/A (Manual Mode)"
        print("=" * 65)
        print(" BALAJI FLEET COMPLIANCE - LIVE E-CHALLAN SCANNER")
        print(f" Provider:   {provider.provider_name}")
        print(f" Endpoint:   {endpoint}")
        print(f" Configured: {'YES' if provider.is_configured() else 'NO (Requires API credentials in .env)'}")
        print("=" * 65)

        service = ChallanMonitorService(provider=provider)

        if args.vehicle:
            reg_norm = Vehicle.normalize_registration(args.vehicle)
            vehicle = Vehicle.query.filter_by(registration_number=reg_norm).first()
            if not vehicle:
                print(f"[!] Vehicle '{args.vehicle}' (normalized: {reg_norm}) not found in database.")
                sys.exit(1)

            print(f"[*] Querying live status for {vehicle.formatted_registration}...")
            log = service.check_single_vehicle(vehicle)
            print(f"    Status: {log.status.upper()}")
            print(f"    Challans Found: {log.challans_found}")
            if log.error_details:
                print(f"    Details/Error: {log.error_details}")
            print("=" * 65)
            return

        # Fleet batch scan
        limit = None if args.all else args.limit
        vehicles_query = Vehicle.query.filter_by(is_active=True).order_by(Vehicle.created_at.desc())
        if limit:
            vehicles_query = vehicles_query.limit(limit)
        vehicles = vehicles_query.all()

        total = len(vehicles)
        print(f"[*] Starting live scan across {total} vehicle(s)...")

        success_count = 0
        failed_count = 0
        new_challans = 0

        for idx, v in enumerate(vehicles, start=1):
            sys.stdout.write(f"\r[{idx}/{total}] Checking {v.formatted_registration}...")
            sys.stdout.flush()
            log = service.check_single_vehicle(v)
            if log.status == "success":
                success_count += 1
                new_challans += (log.challans_found or 0)
                print(f" -> OK (Found: {log.challans_found})")
            else:
                failed_count += 1
                err_msg = (log.error_details or log.status)[:50]
                print(f" -> {log.status.upper()} ({err_msg})")

            if args.delay and idx < total:
                time.sleep(args.delay)

        print("-" * 65)
        print("Scan Completed:")
        print(f"  Total Queried:    {total}")
        print(f"  Successful:       {success_count}")
        print(f"  Failed / Paused:  {failed_count}")
        print(f"  Challans Added:   {new_challans}")
        print("=" * 65)


if __name__ == "__main__":
    main()
