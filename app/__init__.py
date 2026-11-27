"""Application factory for Balaji Fleet Compliance System."""
import os
import click
from datetime import datetime, timezone
from flask import Flask, render_template
from app.extensions import db, migrate, login_manager, csrf
from config import config_by_name, DEFAULT_DEV_SECRET_KEY


def format_inr(value) -> str:
    """Format numeric values as Indian Rupee currency (e.g., ₹1,23,456.00)."""
    try:
        val = float(value or 0.0)
        sign = "-" if val < 0 else ""
        int_part, dec_part = f"{abs(val):.2f}".split(".")
        if len(int_part) > 3:
            last3 = int_part[-3:]
            rest = int_part[:-3]
            groups = [rest[max(i - 2, 0):i] for i in range(len(rest), 0, -2)][::-1]
            grouped = ",".join(groups) + "," + last3
        else:
            grouped = int_part
        return f"{sign}₹{grouped}.{dec_part}"
    except (ValueError, TypeError):
        return f"₹{value}"


def create_app(config_name=None) -> Flask:
    """Create and configure the Flask application instance."""
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "development")

    app = Flask(__name__)
    app.config.from_object(config_by_name.get(config_name, config_by_name["default"]))

    if config_name == "production":
        secret_key = app.config.get("SECRET_KEY")
        if not secret_key or secret_key == DEFAULT_DEV_SECRET_KEY:
            raise RuntimeError(
                "SECRET_KEY environment variable must be set to a strong non-default value in production."
            )

    # Ensure required instance folders exist
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(os.path.join(app.instance_path), exist_ok=True)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Register Jinja context filters and processors
    app.jinja_env.filters["inr"] = format_inr

    @app.context_processor
    def inject_global_template_vars():
        from flask_login import current_user
        from app.models.challan import Challan
        unack_challans = []
        total_unack = 0
        if current_user.is_authenticated:
            try:
                unack_challans = Challan.query.filter_by(is_acknowledged=False).order_by(Challan.violation_date.desc()).limit(5).all()
                total_unack = Challan.query.filter_by(is_acknowledged=False).count()
            except Exception:
                unack_challans = []
                total_unack = 0

        return {
            "current_year": datetime.now(timezone.utc).year,
            "company_name": "Balaji Transports",
            "app_name": "Balaji Fleet Compliance",
            "unread_alerts_count": total_unack,
            "recent_alerts": unack_challans,
        }

    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.vehicles import vehicles_bp
    from app.routes.challans import challans_bp
    from app.routes.payments import payments_bp
    from app.routes.reports import reports_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(challans_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(reports_bp)

    # Error Handlers
    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template("errors/500.html"), 500

    # Security Headers
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        if not app.debug:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    # Register Custom CLI Commands
    register_cli_commands(app)

    return app


def register_cli_commands(app: Flask):
    """Register CLI management commands."""
    from app.models.user import User
    from app.models.vehicle import Vehicle
    from app.models.challan import Challan
    from app.models.payment import Payment
    from app.models.monitoring_log import MonitoringLog
    from app.models.audit_log import AuditLog

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True, help="Administrator username")
    @click.option("--fullname", prompt=True, help="Full name of administrator")
    @click.option("--email", prompt=True, default="", help="Email address (optional)")
    @click.option(
        "--password",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
        help="Secure password",
    )
    def create_admin(username, fullname, email, password):
        """Securely create or promote the initial CEO / Administrator."""
        if not username or not password or not fullname:
            click.echo("Error: Username, Full Name, and Password are required.", err=True)
            return

        existing = User.query.filter_by(username=username).first()
        if existing:
            existing.full_name = fullname
            if email:
                existing.email = email
            existing.role = User.ROLE_ADMIN
            existing.set_password(password)
            existing.is_active = True
            db.session.commit()
            click.echo(f"Successfully updated user '{username}' as CEO / Administrator.")
            AuditLog.record(
                action="ADMIN_UPDATED_VIA_CLI",
                user=None,
                entity_type="User",
                entity_id=existing.id,
                details=f"Admin account '{username}' updated via CLI",
            )
            db.session.commit()
        else:
            admin_user = User(
                username=username,
                full_name=fullname,
                email=email if email else None,
                role=User.ROLE_ADMIN,
                is_active=True,
            )
            admin_user.set_password(password)
            db.session.add(admin_user)
            db.session.commit()
            click.echo(f"Successfully created CEO / Administrator '{username}' (ID: {admin_user.id}).")
            AuditLog.record(
                action="ADMIN_CREATED_VIA_CLI",
                user=None,
                entity_type="User",
                entity_id=admin_user.id,
                details=f"First admin account '{username}' created via CLI",
            )
            db.session.commit()

    @app.cli.command("seed-demo")
    def seed_demo():
        """Seed realistic fleet data for demonstration and validation."""
        click.echo("Seeding initial fleet compliance data...")

        # Ensure single primary Administrator account exists
        admin = User.query.filter_by(username="admin").first()
        if not admin:
            admin = User(
                username="admin",
                full_name="Balaji Administrator",
                email="admin@balajitransports.com",
                role=User.ROLE_ADMIN,
                is_active=True,
            )
            admin.set_password("BalajiFleet#2026")
            db.session.add(admin)
            db.session.commit()
            click.echo("Created Administrator account: admin (BalajiFleet#2026)")
        else:
            admin.full_name = "Balaji Administrator"
            admin.email = "admin@balajitransports.com"
            admin.role = User.ROLE_ADMIN
            admin.set_password("BalajiFleet#2026")
            db.session.commit()

        # Remove all other accounts, reassigning any references to the single admin
        other_users = User.query.filter(User.id != admin.id).all()
        if other_users:
            for u in other_users:
                Payment.query.filter_by(recorded_by_user_id=u.id).update({"recorded_by_user_id": admin.id})
                Payment.query.filter_by(verified_by_user_id=u.id).update({"verified_by_user_id": admin.id})
                AuditLog.query.filter_by(user_id=u.id).update({"user_id": admin.id})
                db.session.delete(u)
            db.session.commit()
            click.echo("Consolidated all logins to single Administrator account.")

        # If real fleet vehicles already exist in database, skip seeding demo vehicles
        if Vehicle.query.count() > 0:
            click.echo("Existing fleet vehicles detected in database. Skipping demo vehicle creation.")
            click.echo("Demo data successfully seeded!")
            return

        # Seed sample vehicles
        sample_vehicles = [
            ("MH12AB1234", "Truck", "Tata Prima 4028.S", "Balaji Transports Pvt Ltd", "Pune Logistics Hub", "Rajesh Sharma"),
            ("MH14CD5678", "Truck", "BharatBenz 2823R", "Balaji Transports Pvt Ltd", "Mumbai Port Division", "Rajesh Sharma"),
            ("DL01EF9012", "Car", "Toyota Innova Crysta", "Balaji Transports Exec Pool", "Corporate HQ", "Pooja Mehta"),
            ("KA04GH3456", "Truck", "Ashok Leyland 4220", "Balaji Transports South Hub", "Bengaluru Depot", "Rajesh Sharma"),
            ("GJ06JK7890", "Bus", "Volvo 9600 Multi-Axle", "Balaji Staff Transport", "Vadodara Branch", "Rajesh Sharma"),
        ]

        veh_objects = []
        for reg, vtype, make, owner, dept, mgr in sample_vehicles:
            norm_reg = Vehicle.normalize_registration(reg)
            v = Vehicle.query.filter_by(registration_number=norm_reg).first()
            if not v:
                v = Vehicle(
                    registration_number=norm_reg,
                    display_reg_number=Vehicle.format_registration(norm_reg),
                    vehicle_type=vtype,
                    make_model=make,
                    registered_owner=owner,
                    department=dept,
                    assigned_manager=mgr,
                    is_active=True,
                )
                db.session.add(v)
                db.session.commit()
            veh_objects.append(v)

        # Seed sample challans with realistic highway locations and camera photo evidence
        sample_challans = [
            (
                veh_objects[0].id,
                "MH-ECH-2026-981241",
                "Speed Limit Violation",
                "Over-speeding detected via automated expressway CCTV camera (94 km/h in 80 km/h zone).",
                "Mumbai-Pune Expressway (KM 42 near Lonavala)",
                datetime(2026, 3, 10, 14, 30, tzinfo=timezone.utc),
                datetime(2026, 3, 11, 9, 0, tzinfo=timezone.utc),
                "Highway Safety Police, Maharashtra",
                2000.0,
                Challan.STATUS_PENDING,
                Challan.PAYMENT_UNPAID,
                "High-Speed Expressway Radar Camera #42",
                "/static/images/challan_evidence_1.jpg",
                False,
            ),
            (
                veh_objects[1].id,
                "MH-ECH-2026-887412",
                "No Entry / Route Restriction",
                "Heavy commercial vehicle operating during restricted peak hours in red zone.",
                "CST Railway Terminus South Mumbai Red Zone",
                datetime(2026, 3, 15, 11, 15, tzinfo=timezone.utc),
                datetime(2026, 3, 15, 15, 45, tzinfo=timezone.utc),
                "Mumbai Traffic Police",
                4000.0,
                Challan.STATUS_PENDING,
                Challan.PAYMENT_UNPAID,
                "Mumbai Police CCTV Surveillance Unit",
                "/static/images/challan_evidence_2.jpg",
                False,
            ),
            (
                veh_objects[2].id,
                "DL-TRF-2026-554109",
                "Improper Parking",
                "Unauthorized parking in designated red zone near airport gate.",
                "Delhi IGI Airport Cargo Gate 3",
                datetime(2026, 2, 20, 16, 20, tzinfo=timezone.utc),
                datetime(2026, 2, 21, 10, 0, tzinfo=timezone.utc),
                "Delhi Traffic Police",
                1000.0,
                Challan.STATUS_PAID,
                Challan.PAYMENT_PAID,
                "Delhi Traffic Police Portal",
                None,
                True,
            ),
        ]

        for vid, cnum, vtype, vdesc, vloc, vdate, idate, auth, penalty, status, pstatus, src, img_url, ack in sample_challans:
            c = Challan.query.filter_by(challan_number=cnum).first()
            if not c:
                c = Challan(
                    vehicle_id=vid,
                    challan_number=cnum,
                    violation_type=vtype,
                    violation_description=vdesc,
                    violation_location=vloc,
                    violation_date=vdate,
                    issue_date=idate,
                    issuing_authority=auth,
                    penalty_amount=penalty,
                    status=status,
                    payment_status=pstatus,
                    source=src,
                    last_verified_at=idate,
                    evidence_image_url=img_url,
                    is_acknowledged=ack,
                )
                db.session.add(c)
                db.session.commit()
            else:
                c.violation_location = vloc
                c.evidence_image_url = img_url
                c.is_acknowledged = ack
                db.session.commit()

                # If paid, record payment
                if pstatus == Challan.PAYMENT_PAID:
                    p = Payment(
                        challan_id=c.id,
                        amount_paid=penalty,
                        payment_date=idate.date(),
                        payment_mode=Payment.MODE_NET_BANKING,
                        payment_reference="UPI-REF-20260221-8899",
                        recorded_by_user_id=admin.id,
                        verification_status=Payment.VERIFICATION_VERIFIED,
                        verified_by_user_id=admin.id,
                        verified_at=idate,
                        notes="Paid online via Delhi Traffic Police official portal.",
                    )
                    db.session.add(p)
                    db.session.commit()

        # Seed monitoring log
        now_utc = datetime.now(timezone.utc)
        for v in veh_objects[:3]:
            m = MonitoringLog(
                vehicle_id=v.id,
                check_start_time=now_utc,
                check_completion_time=now_utc,
                status=MonitoringLog.STATUS_SUCCESS,
                data_source="Manual Verification (Authorized Staff)",
                challans_found=v.challans.count(),
            )
            db.session.add(m)
        db.session.commit()

        click.echo("Demo data successfully seeded!")

    @app.cli.command("scan-fleet")
    @click.option("--limit", default=15, type=int, help="Number of vehicles to check (default: 15, use 0 for all)")
    @click.option("--delay", default=0.05, type=float, help="Delay in seconds between API requests")
    def scan_fleet_cmd(limit, delay):
        """Execute live e-Challan checks against the configured provider."""
        from app.services.challan_monitor import ChallanMonitorService
        from app.services.challan_provider import get_default_challan_provider
        provider = get_default_challan_provider()
        lim_str = "ALL" if limit == 0 else str(limit)
        click.echo(f"Initializing live fleet scan via {provider.provider_name} (Limit: {lim_str})...")
        service = ChallanMonitorService(provider=provider)
        lim = None if limit == 0 else limit
        result = service.check_fleet(limit=lim, delay_seconds=delay)
        click.echo(f"Scan finished: {result['success_count']}/{result['total_checked']} vehicles checked successfully.")
        click.echo(f"New challans added/updated: {result['challans_added']}, Failed: {result['failed_count']}")
        if result["failed_count"] > 0 and result["logs"]:
            first_fail = next((l for l in result["logs"] if l.status != "success"), None)
            if first_fail and first_fail.error_details:
                click.echo(f"Sample failure reason: {first_fail.error_details}", err=True)

    @app.cli.command("sync-surepass")
    @click.option("--top15/--all", default=True, help="Sync top 15 test vehicles (default: True, or pass --all for entire fleet)")
    def sync_surepass_cmd(top15):
        """Sync live challan data from Surepass API."""
        from app.services.challan_provider import SurepassChallanProvider
        from app.services.challan_monitor import ChallanMonitorService

        top_15_regs = [
            'KA19AA8275', 'KA06AC0186', 'KA06AB2916', 'KA06AC1276',
            'TN18AP2121', 'KA06AB4585', 'KA06AC5357', 'KA06AC1924',
            'KA06AC2410', 'KA06AC4728', 'AP16TE6293', 'KA06AB7874',
            'TS01UA3642', 'TS01UA5252', 'TS01UA5242'
        ]

        provider = SurepassChallanProvider()
        service = ChallanMonitorService(provider=provider)

        if top15:
            click.echo(f"Checking top 15 test vehicles with most challans from Surepass...")
            vehicles = Vehicle.query.filter(Vehicle.registration_number.in_(top_15_regs)).all()
        else:
            click.echo("Checking all fleet vehicles from Surepass...")
            vehicles = Vehicle.query.filter_by(is_active=True).all()

        result = service.check_fleet(vehicles=vehicles, delay_seconds=0.02)
        click.echo(f"[OK] Sync completed successfully!")
        click.echo(f"Total checked: {result['total_checked']}")
        click.echo(f"Successful checks: {result['success_count']}")
        click.echo(f"Total challans recorded/updated: {result['challans_added']}")
