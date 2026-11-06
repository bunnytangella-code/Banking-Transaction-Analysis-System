# BankSight — Banking Transaction Analysis System

BankSight is an educational Flask application for exploring synthetic customer, account, and transaction records. It persists data in MySQL, updates simulated balances transactionally, and produces database-backed analytics, review flags, and CSV/chart exports.

> **Educational simulation only.** All balances and records are fictional. This is not a real banking service. Do not enter real financial or identity information. Rule matches are prompts for human review, not fraud findings.

## Features

- Direct access to the dashboard with no username/password prompt; Flask CSRF protection remains enabled for state-changing forms.
- Customer and account management with relationship safeguards, search, filters, and pagination.
- Deposit, withdrawal, and account-to-account transfer processing with decimal amounts, row locking, rollback-safe balance updates, and one-time form tokens.
- Immutable completed transactions and review flags for threshold, rapid activity, and account-relative amount patterns.
- Dashboard KPI cards, Chart.js visualizations, Pandas summaries, and NumPy descriptive statistics.
- Filtered transaction and summary CSV exports, plus a downloadable Matplotlib monthly chart.
- Optional idempotent synthetic demo-data loader.
- Responsive layouts for desktop and mobile.

Transfers require two different active accounts and sufficient funds in the source account. Each transfer updates both balances atomically and creates matching debit/credit ledger entries marked “Transfer out” and “Transfer in.”

## Technology

Python 3.10+, Flask, Flask-SQLAlchemy / SQLAlchemy, MySQL Connector/Python, Pandas, NumPy, Matplotlib, Bootstrap 5, Chart.js, and pytest.

## Project layout

```text
app.py                 Flask routes, validation, transaction processing
config.py              Environment-based configuration
db.py                  SQLAlchemy models and safe schema initialization
analytics.py           Pandas and NumPy data analysis
schema.sql             Repeatable MySQL schema
templates/             Responsive Jinja pages
static/css/style.css   BankSight design system and responsive styling
static/js/              Navigation, form UX, and Chart.js charts
tests/                  Isolated SQLite-backed automated tests
exports/                Reserved for local generated output
```

## Prerequisites

- Python 3.10 or later (tested here with Python 3.14.6).
- MySQL Server 8.x running locally.
- A MySQL account that can create the configured database, or permission to create it manually.

## MySQL configuration

The local `.env` contains the requested database defaults and a development session secret:

```dotenv
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=root
DB_NAME=banksight_db
SECRET_KEY=<unique random local secret>
FLASK_DEBUG=true
UNUSUAL_AMOUNT_THRESHOLD=50000
```

These are **local development settings only**. Change the database password and `SECRET_KEY` before use beyond a private local machine. The local `.env` has a generated random secret. The `.env` file is ignored by Git. Use `.env.example` as a template on another machine.

By default, startup tries to create `banksight_db` if it does not exist and then creates missing tables without dropping existing data. If database-creation permission is unavailable, create the database manually:

```sql
CREATE DATABASE banksight_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

The application account must have the needed permissions on that database. An alternative SQLAlchemy `DATABASE_URL` can override the individual `DB_*` values.

## Install and run

PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000**. The dashboard opens directly without a login screen. BankSight binds to localhost only; it does not expose itself to the public internet. If PowerShell blocks activation, use `.\.venv\Scripts\python.exe` instead of activating the environment.

## Demo records

Choose **Load demo data** from the empty dashboard or Settings. The operation inserts fictional names, account balances, and transactions once; it is not run automatically during startup and does not reset or overwrite existing records. Synthetic rows are described as demonstration data.

## Tests

The automated tests use a temporary SQLite database and never connect to the configured MySQL database:

```powershell
python -m pytest -q
```

They cover schema setup, direct dashboard access, customer/account validation, balance changes, invalid transactions, review flags, analytics, filtered CSV exports, one-time transaction submission, and CSRF rejection.

## Exports and reports

The Reports page supports date/type filters and provides:

- Filtered transaction CSV.
- Filtered summary CSV with generated timestamp and monthly totals.
- Filtered monthly deposits-versus-withdrawals PNG generated by Matplotlib.

Export endpoints use current database records. CSV data is synthetic project data only.

## Common setup issues

| Problem | Suggested action |
|---|---|
| MySQL connection refused | Start the local MySQL service and verify `DB_HOST`/`DB_PORT`. |
| Access denied / cannot create database | Check `DB_USER`/`DB_PASSWORD`, or create `banksight_db` manually and grant the app user access. |
| Unknown database | Create it using the SQL above and restart the app. |
| Missing Python module | Activate the intended virtual environment and run `pip install -r requirements.txt`. |
| Charts do not load | Check internet access for the CDN-hosted Chart.js and Bootstrap assets; the server-rendered pages and exports remain available. |
| CSRF error | Reload the page to receive a fresh form token, then submit again. |

## Security and educational limitations

This application is a student demonstration, not production banking software. It has no login or authorization; all users who can reach the local app can view and modify its synthetic records. It has no real banking integration, payment rails, account credentials, or customer identity verification. Flask's development server binds to localhost only. Do not expose it to a network, deploy it publicly, or use it with real financial data or to make decisions about real people or accounts.
