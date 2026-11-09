"""Single administrator access control decorators and permission utilities."""
from functools import wraps
from flask import redirect, url_for
from flask_login import current_user


def roles_required(*allowed_roles):
    """Enforce authentication. In single-login architecture, administrator has universal access."""
    def decorator(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))
            return fn(*args, **kwargs)

        return decorated_view

    return decorator


def admin_required(fn):
    """Shorthand decorator for Administrator access."""
    return roles_required("admin")(fn)


def manager_or_admin_required(fn):
    """Access for fleet management functions."""
    return roles_required("admin")(fn)


def accounts_or_admin_required(fn):
    """Access for payment and verification functions."""
    return roles_required("admin")(fn)
