"""WSGI entry point for Balaji Fleet Compliance System."""
import os
from app import create_app

app = create_app(os.environ.get("FLASK_ENV", "development"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print(f" * Balaji Fleet Compliance running on http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=app.config.get("DEBUG", False))
