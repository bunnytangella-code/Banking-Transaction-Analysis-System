# BankSight Project Documentation

## Problem statement

Learners need a practical example of how a small web application can collect synthetic records, enforce business rules, persist transactions, and turn operational data into understandable analytics. BankSight provides a local-only sandbox for those exercises.

## Objectives and scope

- Maintain fictional customers, simulated accounts, deposits, and withdrawals.
- Keep account balance changes consistent with their transaction records.
- Explore transaction patterns with Pandas, NumPy, Chart.js, and Matplotlib.
- Demonstrate input validation, sessions, CSRF defenses, SQL constraints, and review workflows.
- Export current filtered data and summaries for classroom demonstrations.

Out of scope: real financial data, banking APIs, payment services, identity verification, production authorization, fraud determination, and public deployment.

## Architecture

1. Jinja templates render pages directly; HTML forms submit to Flask.
2. Flask validates every submitted field and uses Flask-WTF CSRF tokens for state-changing requests. No user login or authorization is implemented; the app is intended for localhost-only use with synthetic records.
3. SQLAlchemy maps application models to MySQL tables. A test override uses isolated SQLite files.
4. Transaction handling locks the selected account row on MySQL, applies a signed balance delta, inserts the positive-amount transaction, evaluates review rules, and commits all changes together.
5. `analytics.py` converts database transactions to a Pandas DataFrame, calculates accounting totals using `Decimal`, and uses NumPy for descriptive statistics.
6. Chart.js consumes a JSON endpoint; Matplotlib generates a downloadable PNG.

## Database design

- **customers**: fictional display name and generated customer ID.
- **accounts**: customer foreign key, account type, opening/current decimal balances, and status.
- **transactions**: account foreign key, date, Deposit/Withdrawal type, positive decimal amount, optional description.
- **review_flags**: transaction link, rule name/reason, status, timestamps, and a unique transaction/rule constraint.
- **app_settings**: persisted rule threshold and idempotent demo-data marker.

Relationships use InnoDB foreign keys. Customer/account deletion is constrained when dependent records exist. Completed transactions cannot be edited or deleted through the UI. Monetary database values use `DECIMAL(15,2)`.

## Modules

- `config.py`: loads local environment variables and SQLAlchemy settings.
- `db.py`: SQLAlchemy models and non-destructive initialization.
- `app.py`: routes, server-side validation, transaction processing, review rules, CSV/chart generation, and synthetic seed action.
- `analytics.py`: filtered data frame preparation, monthly/type/account summaries, exact monetary summary totals, and NumPy statistics.
- `templates/`, `static/`: accessible responsive UI, styles, form behavior, and interactive visualizations.
- `schema.sql`: repeatable standalone MySQL schema.
- `tests/test_app.py`: isolated tests that do not touch the user's configured MySQL database.

## Analytics methods

Pandas groups deposits and withdrawals by month, daily transaction volume, transaction type, and account. Summary totals use `Decimal` values to avoid treating binary floats as exact accounting amounts. NumPy calculates mean, median, standard deviation, minimum, maximum, and 95th percentile on converted amounts; these are presented as descriptive statistics, not exact ledger totals.

Empty result sets return empty chart/report datasets and null statistical values instead of invented sample values.

## Validation and business rules

- Customer display names are required and capped at 100 characters.
- Account customers and account types must exist in the allowed set; opening balances cannot be negative.
- Transaction type must be Deposit or Withdrawal; amount must be positive and within `DECIMAL(15,2)` capacity.
- Transaction date must parse and cannot be in the future.
- Account must exist and be active; withdrawal amount cannot exceed available simulated balance.
- Amount remains positive in storage; type controls balance impact and display sign.
- A row lock protects concurrent MySQL transaction updates. Account balance and transaction insert commit or roll back together.
- One-time form tokens reduce accidental duplicate submissions. CSRF protection applies to all modifying POSTs.
- Review rules create unique flags for threshold-sized amounts, short-period account activity, and large deviations from account history. They never block accounts and do not claim fraud.
- Customer/account deletion is refused where relationships would be broken. Account status can instead be changed to inactive.

## Test cases

The pytest suite validates initialization, direct dashboard access, invalid customer and account input, deposit/withdrawal arithmetic, rejected amounts/types/statuses, excessive withdrawals, one-time submissions, threshold flags, analytics with known data and empty data, filtered CSV exports, and CSRF.

Run using `python -m pytest -q`. Tests create temporary SQLite databases and never point at the local MySQL database.

## Expected outputs

- Dashboard KPI totals and charts reflect database records only.
- Deposits add to and withdrawals subtract from simulated account balances.
- CSV files reflect active filters and use INR units.
- Review queue explains each matched rule and allows the demo administrator to mark it reviewed or dismissed.
- Matplotlib exports a titled monthly comparison chart from filtered data.

## Limitations and future enhancements

- There is no authentication or authorization. The development server binds to localhost only and the app must not be exposed to a network or used with real data.
- The database setup needs an accessible MySQL service for the full app; isolated tests use SQLite instead.
- Chart.js and Bootstrap assets are loaded from CDNs.
- Rule thresholds are illustrative, not statistically validated, and not suitable for fraud decisions.
- Future learning extensions could add report PDFs, audit-log history, role-based classroom accounts, stronger deployment guidance, configurable date windows, and more comprehensive integration tests against disposable MySQL instances.
