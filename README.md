# Balaji Fleet Compliance System

A centralized fleet traffic challan monitoring and penalty management web application built for **Balaji Transports**, an Indian logistics and commercial transport enterprise operating 500+ commercial vehicles (trucks, buses, and cars).

---

## 1. Architecture & Technology Stack

* **Backend Framework**: Python 3.13+ with Flask
* **Database & ORM**: PostgreSQL (production) with Flask-SQLAlchemy 3.x
* **Migrations**: Flask-Migrate & Alembic
* **Authentication & RBAC**: Flask-Login with Werkzeug password hashing
* **CSRF Protection**: Flask-WTF
* **Frontend**: HTML5, CSS3, JavaScript, Bootstrap 5.3, Bootstrap Icons, Google Fonts (Inter)
* **Analytics**: Chart.js for violation penalty trend tracking
* **Data Processing**: Pandas & OpenPyXL
* **Production WSGI Server**: Gunicorn
* **Automated Testing**: Pytest

---

## 2. Role-Based Access Control (RBAC)

Permissions are enforced strictly on the server side:

| Role | Key Permissions |
| :--- | :--- |
| **CEO / Administrator (`admin`)** | Full access to fleet, challans, payments, user accounts, and compliance audit logs |
| **Transport Manager (`manager`)** | Vehicle registration/editing, batch imports, challan monitoring, driver follow-up |
| **Accounts Team (`accounts`)** | Challan tracking, payment entry, receipt upload, payment verification, financial reports |
| **Viewer (`viewer`)** | Read-only executive reports and dashboard viewing |

---

## 3. Directory Structure

```
Balaji_Fleet_Compliance/
├── app/
│   ├── __init__.py               # Application factory & CLI commands
│   ├── extensions.py             # SQLAlchemy, Migrate, LoginManager, CSRF
│   ├── models/                   # SQLAlchemy models
│   │   ├── __init__.py
│   │   ├── user.py               # User authentication & RBAC roles
│   │   ├── vehicle.py            # Normalized registration & vehicle details
│   │   ├── challan.py            # Traffic violation notices & penalties
│   │   ├── payment.py            # Payment history & verification workflow
│   │   ├── monitoring_log.py     # Check records & provider failure tracking
│   │   └── audit_log.py          # Immutable compliance audit trail
│   ├── routes/                   # Modular route blueprints
│   │   ├── __init__.py
│   │   ├── auth.py               # Login, logout, session security
│   │   ├── dashboard.py          # Real database metrics & trend charts
│   │   ├── vehicles.py           # Fleet vehicle management
│   │   ├── challans.py           # Challan tracking
│   │   ├── payments.py           # Payment recording & verification
│   │   └── reports.py            # Compliance & audit reports
│   ├── services/                 # Business logic & monitoring services
│   │   ├── __init__.py
│   │   ├── challan_provider.py   # Extensible provider interface & compliance policy
│   │   └── challan_monitor.py    # Vehicle check coordinator & logging
│   ├── static/
│   │   ├── css/style.css         # Modern corporate theme
│   │   └── js/main.js            # Auto-dismiss alerts & UX helpers
│   ├── templates/                # Jinja2 responsive templates
│   │   ├── base.html             # Base sidebar & navbar layout
│   │   ├── auth/login.html       # Corporate login
│   │   ├── dashboard/index.html  # Live executive dashboard
│   │   ├── vehicles/index.html
│   │   ├── challans/index.html
│   │   ├── payments/index.html
│   │   ├── reports/index.html
│   │   └── errors/               # 403, 404, 500 error pages
│   └── utils/
│       ├── __init__.py
│       └── decorators.py         # Server-side @roles_required decorators
├── migrations/                   # Alembic schema version tracking
├── tests/                        # Pytest automated test suite
├── config.py                     # Environment-aware configuration
├── wsgi.py                       # WSGI entry point for local dev & Gunicorn
├── requirements.txt              # Production and development dependencies
├── .env.example                  # Environment configuration template
└── README.md
```

---

## 4. Local Setup Guide (Windows PowerShell)

### Step 1: Open Terminal in Project Directory
```powershell
cd E:\Balaji_Fleet_Compliance
```

### Step 2: Configure Environment Variables
Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```

To configure PostgreSQL, update `.env` or set `DATABASE_URL`:
```powershell
# Example PostgreSQL Connection String
$env:DATABASE_URL="postgresql://postgres:your_password@localhost:5432/balaji_fleet_db"
```
*(If `DATABASE_URL` is not set, the application automatically uses a local SQLite database in `instance/fleet_compliance.db` for development convenience).*

### Step 3: Run Database Migrations
Initialize and apply the schema:
```powershell
$env:FLASK_APP="wsgi.py"
flask db upgrade
```

### Step 4: Create the Initial CEO / Administrator Account
No hardcoded administrator credentials exist. Run the interactive CLI command:
```powershell
flask create-admin
```
Follow the prompts to enter:
* **Username**: `admin`
* **Full Name**: `Balaji Transports Administrator`
* **Email**: `admin@balajitransports.com`
* **Password**: `YourSecurePassword#2026`

### Step 5: (Optional) Seed Demo Fleet Data
To populate sample vehicles, pending violations, and initialize the Administrator login:
```powershell
flask seed-demo
```
This initializes the single Administrator account:
* **Username**: `admin`
* **Default Password**: `BalajiFleet#2026`
* **Email**: `admin@balajitransports.com`

### Step 6: Start the Application
```powershell
python wsgi.py
```
Open your browser and navigate to:
**[http://localhost:5001](http://localhost:5001)**


---

## 5. PostgreSQL Configuration Options

The application supports both connection formats in `.env`:

### Option A: Standard Full Database URL
```ini
DATABASE_URL=postgresql://username:password@hostname:5432/databasename
```

### Option B: Discrete Parameters
```ini
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_secure_password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=balaji_fleet_db
```

### Running Fleet Scans
1. **From the Web App**:
   * Navigate to **Fleet Vehicles** (`/vehicles`).
   * Click **⚡ Scan Fleet** in the top action bar to choose **Top 15 Test Vehicles**, Top 50, or All Fleet.
   * Or click **Live Check** beside any specific vehicle row.
2. **From Terminal / Command Line**:
   ```powershell
   flask scan-fleet --limit 15
   ```

---

## 7. Running Automated Tests

Run the complete Pytest suite (23 tests):
```powershell
python -m pytest -v
```

---

## 8. Render Deployment Notes

To deploy on Render:
1. Create a **PostgreSQL** instance on Render and copy the Internal Database URL.
2. Create a **Web Service** on Render pointing to your Git repository:
   * **Environment**: `Python 3`
   * **Build Command**: `pip install -r requirements.txt && flask db upgrade`
   * **Start Command**: `gunicorn wsgi:app`
3. Add Environment Variables in the Render dashboard:
   * `DATABASE_URL`: *(Your Render PostgreSQL connection string)*
   * `SECRET_KEY`: *(Generate a 32+ character random secret string)*
   * `FLASK_ENV`: `production`
   * `SESSION_COOKIE_SECURE`: `True`
4. Use the Render Shell tab to run `flask create-admin` to provision your CEO account.
