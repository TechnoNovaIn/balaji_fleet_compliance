"""Test the secure create-admin CLI command."""
from app.models.user import User


def test_create_admin_command(runner, app):
    """Test creating an initial CEO / Administrator via the CLI."""
    result = runner.invoke(
        args=[
            "create-admin",
            "--username", "initial_ceo",
            "--fullname", "Balaji Managing Director",
            "--email", "md@balajitransports.com",
            "--password", "DirectorSecret#2026",
        ]
    )
    assert result.exit_code == 0
    assert "Successfully created CEO / Administrator 'initial_ceo'" in result.output

    with app.app_context():
        user = User.query.filter_by(username="initial_ceo").first()
        assert user is not None
        assert user.role == User.ROLE_ADMIN
        assert user.is_admin is True
        assert user.check_password("DirectorSecret#2026") is True


def test_seed_demo_command(runner, app):
    """Test the seed-demo CLI command."""
    result = runner.invoke(args=["seed-demo"])
    assert result.exit_code == 0
    assert "Demo data successfully seeded!" in result.output

    with app.app_context():
        from app.models.vehicle import Vehicle
        from app.models.challan import Challan
        assert Vehicle.query.count() >= 5
        assert Challan.query.count() >= 3
