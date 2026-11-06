import re
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect

from analytics import account_summary, monthly_summary, overall_summary, statistics, transactions_frame
from app import create_app
from db import Account, Customer, ReviewFlag, Transaction, db, initialize_database


@pytest.fixture()
def app(tmp_path):
    database_path = tmp_path / "test.sqlite"
    test_app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "test-key-not-for-production",
        "UNUSUAL_AMOUNT_THRESHOLD": "1000",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
    })
    initialize_database(test_app)
    yield test_app
    with test_app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def sign_in(client):
    response = client.get("/")
    assert response.status_code == 200


def add_account(app, balance="1000.00", status="Active"):
    with app.app_context():
        customer = Customer(display_name="Fictional Customer")
        db.session.add(customer)
        db.session.flush()
        account = Account(customer_id=customer.customer_id, account_type="Savings",
                          opening_balance=Decimal(balance), current_balance=Decimal(balance),
                          status=status)
        db.session.add(account)
        db.session.commit()
        return account.account_id


def transaction_form_token(client):
    response = client.get("/transactions/new")
    assert response.status_code == 200
    match = re.search(rb'name="submission_token" value="([^"]+)"', response.data)
    assert match
    return match.group(1).decode()


def transfer_form_token(client):
    response = client.get("/transfers/new")
    assert response.status_code == 200
    match = re.search(rb'name="submission_token" value="([^"]+)"', response.data)
    assert match
    return match.group(1).decode()


def post_transaction(client, token, **overrides):
    payload = {
        "submission_token": token,
        "account_id": "1",
        "transaction_type": "Deposit",
        "amount": "25.50",
        "transaction_date": datetime.now().strftime("%Y-%m-%dT%H:%M"),
        "description": "Synthetic test",
    }
    payload.update(overrides)
    return client.post("/transactions/new", data=payload)


def post_transfer(client, token, source_id, destination_id, **overrides):
    payload = {
        "submission_token": token,
        "from_account_id": str(source_id),
        "to_account_id": str(destination_id),
        "amount": "125.50",
        "transaction_date": datetime.now().strftime("%Y-%m-%dT%H:%M"),
        "description": "Test transfer",
    }
    payload.update(overrides)
    return client.post("/transfers/new", data=payload)


def test_schema_initialization_creates_required_tables(app):
    with app.app_context():
        names = set(inspect(db.engine).get_table_names())
    assert {"customers", "accounts", "transactions", "review_flags", "app_settings"} <= names


def test_currency_formatter_uses_indian_grouping(app):
    formatter = app.jinja_env.filters["inr"]
    assert formatter("1250000") == "\u20b912,50,000.00"
    assert formatter("850") == "\u20b9850.00"


def test_dashboard_and_data_pages_open_without_login(client):
    for path in ("/", "/customers", "/accounts", "/transactions", "/analytics", "/reports",
                 "/review-queue", "/settings"):
        response = client.get(path)
        assert response.status_code == 200, path
    assert b"Sign in to BankSight" not in client.get("/").data


def test_internal_errors_return_safe_response(client, app):
    app.add_url_rule("/_test-failure", view_func=lambda: 1 / 0)
    response = client.get("/_test-failure")
    assert response.status_code == 500
    assert b"Something went wrong" in response.data
    assert b"ZeroDivisionError" not in response.data


def test_legacy_login_url_redirects_to_dashboard(client):
    response = client.get("/login")
    assert response.status_code == 302
    assert response.location.endswith("/dashboard")


def test_customer_creation_and_validation(client, app):
    sign_in(client)
    response = client.post("/customers/new", data={"display_name": "Asha Iyer"})
    assert response.status_code == 302
    invalid = client.post("/customers/new", data={"display_name": " "})
    assert invalid.status_code == 200
    with app.app_context():
        assert Customer.query.count() == 1
        assert Customer.query.one().display_name == "Asha Iyer"


def test_new_customer_appears_first_when_creation_timestamps_match(client, app):
    sign_in(client)
    same_timestamp = datetime(2024, 1, 1)
    with app.app_context():
        db.session.add_all([
            Customer(display_name=f"Existing Customer {index}", created_at=same_timestamp)
            for index in range(13)
        ])
        db.session.commit()

    form = client.get("/customers/new")
    assert form.status_code == 200
    assert b"Add a customer" in form.data
    created = client.post("/customers/new", data={"display_name": "New Customer"})
    assert created.status_code == 302
    with app.app_context():
        new_customer = Customer.query.filter_by(display_name="New Customer").one()
        new_customer.created_at = same_timestamp
        db.session.commit()

    customers_page = client.get(created.location)
    assert customers_page.status_code == 200
    assert b"New Customer" in customers_page.data
    assert b"Existing Customer 0" not in customers_page.data
    with app.app_context():
        assert Customer.query.count() == 14


def test_account_creation_requires_existing_customer(client, app):
    sign_in(client)
    client.post("/customers/new", data={"display_name": "Ravi Sen"})
    response = client.post("/accounts/new", data={
        "customer_id": "9999", "account_type": "Savings", "opening_balance": "100.00",
    })
    assert response.status_code == 200
    with app.app_context():
        assert Account.query.count() == 0
    response = client.post("/accounts/new", data={
        "customer_id": "1", "account_type": "Savings", "opening_balance": "100.00",
    })
    assert response.status_code == 302
    with app.app_context():
        assert Account.query.one().current_balance == Decimal("100.00")


def test_transfer_moves_funds_atomically_between_accounts(client, app):
    source_id = add_account(app)
    destination_id = add_account(app)

    source_detail = client.get(f"/accounts/{source_id}")
    assert source_detail.status_code == 200
    assert f"/transfers/new?from_account_id={source_id}".encode() in source_detail.data

    form = client.get(f"/transfers/new?from_account_id={source_id}")
    assert form.status_code == 200
    assert f'<option value="{source_id}" selected>'.encode() in form.data
    assert b"Transfer money" in client.get("/transactions").data

    response = post_transfer(client, transfer_form_token(client), source_id, destination_id)
    assert response.status_code == 302
    assert response.location.startswith("/transactions/")
    with app.app_context():
        source = db.session.get(Account, source_id)
        destination = db.session.get(Account, destination_id)
        transfer_records = Transaction.query.order_by(Transaction.transaction_id).all()
        assert source.current_balance == Decimal("874.50")
        assert destination.current_balance == Decimal("1125.50")
        assert len(transfer_records) == 2
        assert transfer_records[0].transaction_type == "Withdrawal"
        assert transfer_records[0].account_id == source_id
        assert transfer_records[0].description.startswith(f"Transfer to account #{destination_id}")
        assert transfer_records[1].transaction_type == "Deposit"
        assert transfer_records[1].account_id == destination_id
        assert transfer_records[1].description.startswith(f"Transfer from account #{source_id}")
        assert transfer_records[0].amount == transfer_records[1].amount == Decimal("125.50")
    transactions = client.get("/transactions")
    assert b"Transfer out" in transactions.data
    assert b"Transfer in" in transactions.data


def test_invalid_transfers_do_not_change_balances_or_add_transactions(client, app):
    source_id = add_account(app, balance="100.00")
    destination_id = add_account(app, balance="50.00")
    sign_in(client)

    same_account = post_transfer(client, transfer_form_token(client), source_id, source_id)
    assert same_account.status_code == 200
    insufficient = post_transfer(
        client, transfer_form_token(client), source_id, destination_id, amount="100.01"
    )
    assert insufficient.status_code == 200
    with app.app_context():
        assert Transaction.query.count() == 0
        assert db.session.get(Account, source_id).current_balance == Decimal("100.00")
        assert db.session.get(Account, destination_id).current_balance == Decimal("50.00")


def test_new_customer_can_complete_account_to_transaction_flow(client, app):
    created = client.post("/customers/new", data={"display_name": "New Transaction Customer"})
    assert created.status_code == 302
    with app.app_context():
        customer = Customer.query.filter_by(display_name="New Transaction Customer").one()
        customer_id = customer.customer_id

    customer_profile = client.get(f"/customers/{customer_id}")
    assert customer_profile.status_code == 200
    assert f"/accounts/new?customer_id={customer_id}".encode() in customer_profile.data

    account_form = client.get(f"/accounts/new?customer_id={customer_id}")
    assert account_form.status_code == 200
    assert f'<option value="{customer_id}" selected>'.encode() in account_form.data
    account_response = client.post("/accounts/new", data={
        "customer_id": str(customer_id),
        "account_type": "Savings",
        "opening_balance": "100.00",
    })
    assert account_response.status_code == 302
    assert account_response.location.endswith(f"/customers/{customer_id}")
    with app.app_context():
        account = Account.query.filter_by(customer_id=customer_id).one()
        account_id = account.account_id

    account_detail = client.get(f"/accounts/{account_id}")
    assert account_detail.status_code == 200
    assert f"/transactions/new?account_id={account_id}".encode() in account_detail.data

    transaction_form = client.get(f"/transactions/new?account_id={account_id}")
    assert transaction_form.status_code == 200
    assert f'<option value="{account_id}" selected>'.encode() in transaction_form.data
    token = re.search(rb'name="submission_token" value="([^"]+)"', transaction_form.data).group(1).decode()
    transaction = post_transaction(client, token, account_id=str(account_id))
    assert transaction.status_code == 302
    with app.app_context():
        saved = Transaction.query.one()
        assert saved.account.customer_id == customer_id
        assert db.session.get(Account, account_id).current_balance == Decimal("125.50")


def test_deposit_increases_balance_and_records_transaction(client, app):
    account_id = add_account(app)
    sign_in(client)
    token = transaction_form_token(client)
    response = post_transaction(client, token, account_id=str(account_id))
    assert response.status_code == 302
    with app.app_context():
        account = db.session.get(Account, account_id)
        txn = Transaction.query.one()
        assert account.current_balance == Decimal("1025.50")
        assert txn.amount == Decimal("25.50")
        assert txn.transaction_type == "Deposit"
        transaction_id = txn.transaction_id
    detail = client.get(f"/transactions/{transaction_id}")
    assert detail.status_code == 200
    assert f"/transactions/{transaction_id}/receipt".encode() in detail.data
    receipt = client.get(f"/transactions/{transaction_id}/receipt")
    assert receipt.status_code == 200
    assert b"Print / Save as PDF" in receipt.data
    assert b"Fictional Customer" in receipt.data
    assert b"+\xe2\x82\xb925.50" in receipt.data
    transactions = client.get("/transactions")
    assert f"/transactions/{transaction_id}/receipt/download".encode() in transactions.data
    assert f"/transactions/{transaction_id}/receipt".encode() in transactions.data
    downloaded_receipt = client.get(f"/transactions/{transaction_id}/receipt/download")
    assert downloaded_receipt.status_code == 200
    assert downloaded_receipt.mimetype == "application/pdf"
    assert downloaded_receipt.headers["Content-Disposition"] == (
        f"attachment; filename=banksight-receipt-{transaction_id}.pdf"
    )
    assert downloaded_receipt.data.startswith(b"%PDF-")


def test_withdrawal_decreases_balance(client, app):
    account_id = add_account(app)
    sign_in(client)
    token = transaction_form_token(client)
    response = post_transaction(client, token, account_id=str(account_id),
                                transaction_type="Withdrawal", amount="40.00")
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Account, account_id).current_balance == Decimal("960.00")


@pytest.mark.parametrize("amount", ["0", "-1", "not-money"])
def test_invalid_amount_is_rejected_without_database_changes(client, app, amount):
    account_id = add_account(app)
    sign_in(client)
    token = transaction_form_token(client)
    response = post_transaction(client, token, account_id=str(account_id), amount=amount)
    assert response.status_code == 200
    with app.app_context():
        assert Transaction.query.count() == 0
        assert db.session.get(Account, account_id).current_balance == Decimal("1000.00")


def test_invalid_type_and_excess_withdrawal_are_rejected(client, app):
    account_id = add_account(app)
    sign_in(client)
    token = transaction_form_token(client)
    response = post_transaction(client, token, account_id=str(account_id), transaction_type="Transfer")
    assert response.status_code == 200
    token = transaction_form_token(client)
    response = post_transaction(client, token, account_id=str(account_id),
                                transaction_type="Withdrawal", amount="1000.01")
    assert response.status_code == 200
    with app.app_context():
        assert Transaction.query.count() == 0


def test_inactive_accounts_reject_transactions(client, app):
    account_id = add_account(app, status="Inactive")
    add_account(app, status="Active")
    sign_in(client)
    token = transaction_form_token(client)
    response = post_transaction(client, token, account_id=str(account_id))
    assert response.status_code == 200
    with app.app_context():
        assert Transaction.query.count() == 0


def test_successful_transaction_is_one_time_submission(client, app):
    account_id = add_account(app)
    sign_in(client)
    token = transaction_form_token(client)
    assert post_transaction(client, token, account_id=str(account_id)).status_code == 302
    assert post_transaction(client, token, account_id=str(account_id)).status_code == 409
    with app.app_context():
        assert Transaction.query.count() == 1


def test_large_transaction_creates_unique_review_flag(client, app):
    account_id = add_account(app, balance="10000.00")
    sign_in(client)
    token = transaction_form_token(client)
    response = post_transaction(client, token, account_id=str(account_id), amount="1500.00")
    assert response.status_code == 302
    with app.app_context():
        assert ReviewFlag.query.count() == 1
        flag = ReviewFlag.query.one()
        assert flag.rule_name == "Large amount"
        assert flag.review_status == "Pending"


def test_analytics_return_correct_results_and_handle_empty_data(app):
    with app.app_context():
        empty = transactions_frame([])
        assert monthly_summary(empty) == []
        assert statistics(empty)["count"] == 0
        assert overall_summary(empty)["deposits"] == Decimal("0.00")
        customer = Customer(display_name="Sample Person")
        db.session.add(customer)
        db.session.flush()
        account = Account(customer_id=customer.customer_id, account_type="Current",
                          opening_balance=Decimal("0.00"), current_balance=Decimal("30.00"))
        db.session.add(account)
        db.session.flush()
        db.session.add_all([
            Transaction(account_id=account.account_id, transaction_date=datetime(2026, 3, 1),
                        transaction_type="Deposit", amount=Decimal("100.00")),
            Transaction(account_id=account.account_id, transaction_date=datetime(2026, 3, 2),
                        transaction_type="Withdrawal", amount=Decimal("70.00")),
        ])
        db.session.commit()
        frame = transactions_frame(Transaction.query.all())
        assert overall_summary(frame)["deposits"] == Decimal("100.00")
        assert overall_summary(frame)["withdrawals"] == Decimal("70.00")
        assert monthly_summary(frame) == [{"month": "2026-03", "deposits": Decimal("100.00"),
                                           "withdrawals": Decimal("70.00")}]
        assert account_summary(frame)[0]["transaction_count"] == 2
        assert statistics(frame)["median"] == 85.0


def test_csv_exports_are_available_and_respect_filters(client, app):
    account_id = add_account(app)
    sign_in(client)
    token = transaction_form_token(client)
    post_transaction(client, token, account_id=str(account_id), transaction_type="Deposit", amount="20.00")
    token = transaction_form_token(client)
    post_transaction(client, token, account_id=str(account_id), transaction_type="Withdrawal", amount="10.00")
    response = client.get("/exports/transactions.csv?type=Deposit")
    assert response.status_code == 200
    assert b"Deposit" in response.data
    assert b"Withdrawal" not in response.data
    anon = app.test_client().get("/exports/transactions.csv")
    assert anon.status_code == 200


def test_dashboard_analytics_and_reports_render_database_data(client, app):
    account_id = add_account(app)
    sign_in(client)
    token = transaction_form_token(client)
    post_transaction(client, token, account_id=str(account_id), amount="250.00")
    for path in ("/", "/analytics", f"/reports?account_id={account_id}&type=Deposit",
                 "/review-queue", "/accounts", "/transactions"):
        response = client.get(path)
        assert response.status_code == 200, path
    response = client.get("/api/dashboard?type=Deposit")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["monthly"][0]["deposits"] == 250.0
    assert payload["balances"][0]["balance"] == 1250.0


def test_demo_seed_is_idempotent(client, app):
    sign_in(client)
    first = client.post("/demo-data")
    assert first.status_code == 302
    with app.app_context():
        customer_count = Customer.query.count()
        transaction_count = Transaction.query.count()
    second = client.post("/demo-data")
    assert second.status_code == 302
    with app.app_context():
        assert Customer.query.count() == customer_count
        assert Transaction.query.count() == transaction_count
        assert customer_count == 5
        assert transaction_count == 61


def test_csrf_rejects_state_changing_post():
    app = create_app({
        "TESTING": True, "SECRET_KEY": "csrf-test-key",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
    })
    client = app.test_client()
    response = client.post("/customers/new", data={"display_name": "Asha Iyer"})
    assert response.status_code == 400
