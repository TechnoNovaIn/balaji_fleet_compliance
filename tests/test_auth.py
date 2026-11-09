"""Authentication test suite."""
from app.models.user import User


def test_login_page_renders(client):
    """Test that login page renders with corporate branding."""
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert b"Balaji Transports" in response.data
    assert b"Sign In" in response.data


def test_login_success(client, admin_user):
    """Test successful authentication and session creation."""
    response = client.post(
        "/auth/login",
        data={"username": "admin_ceo", "password": "SecureAdmin#2026"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Traffic Challans" in response.data or b"Challan Records" in response.data


def test_login_invalid_password(client, admin_user):
    """Test login failure with invalid password."""
    response = client.post(
        "/auth/login",
        data={"username": "admin_ceo", "password": "WrongPassword!"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Invalid username or password" in response.data


def test_login_deactivated_user(client, app):
    """Test that deactivated accounts cannot log in."""
    with app.app_context():
        user = User(
            username="inactive_emp",
            full_name="Deactivated Employee",
            role=User.ROLE_VIEWER,
            is_active=False,
        )
        user.set_password("SomePassword#1")
        from app.extensions import db
        db.session.add(user)
        db.session.commit()

    response = client.post(
        "/auth/login",
        data={"username": "inactive_emp", "password": "SomePassword#1"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"account has been deactivated" in response.data


def test_logout(client, admin_user):
    """Test that logout terminates the session."""
    # First log in
    client.post(
        "/auth/login",
        data={"username": "admin_ceo", "password": "SecureAdmin#2026"},
        follow_redirects=True,
    )

    # Perform logout
    response = client.post("/auth/logout", follow_redirects=True)
    assert response.status_code == 200
    assert b"securely logged out" in response.data

    # Accessing dashboard should now redirect to login
    dash_response = client.get("/")
    assert dash_response.status_code == 302
    assert "/auth/login" in dash_response.location
