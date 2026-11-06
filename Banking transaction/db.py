from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, UniqueConstraint, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

db = SQLAlchemy()


class Customer(db.Model):
    __tablename__ = "customers"

    customer_id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(100), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.current_timestamp())
    accounts = db.relationship("Account", back_populates="customer", passive_deletes=True)


class Account(db.Model):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("opening_balance >= 0", name="ck_accounts_opening_balance"),
        CheckConstraint("current_balance >= 0", name="ck_accounts_current_balance"),
        CheckConstraint("account_type IN ('Savings', 'Current', 'Fixed Deposit')", name="ck_accounts_type"),
        CheckConstraint("status IN ('Active', 'Inactive')", name="ck_accounts_status"),
    )

    account_id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(
        db.Integer, db.ForeignKey("customers.customer_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    account_type = db.Column(db.String(20), nullable=False)
    opening_balance = db.Column(db.Numeric(15, 2), nullable=False, default=Decimal("0.00"))
    current_balance = db.Column(db.Numeric(15, 2), nullable=False, default=Decimal("0.00"))
    status = db.Column(db.String(10), nullable=False, default="Active")
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.current_timestamp())
    customer = db.relationship("Customer", back_populates="accounts")
    transactions = db.relationship("Transaction", back_populates="account", passive_deletes=True)


class Transaction(db.Model):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("transaction_type IN ('Deposit', 'Withdrawal')", name="ck_transactions_type"),
        CheckConstraint("amount > 0", name="ck_transactions_amount"),
    )

    transaction_id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(
        db.Integer, db.ForeignKey("accounts.account_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    transaction_date = db.Column(db.DateTime, nullable=False, index=True)
    transaction_type = db.Column(db.String(10), nullable=False, index=True)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.current_timestamp())
    account = db.relationship("Account", back_populates="transactions")
    review_flags = db.relationship("ReviewFlag", back_populates="transaction", passive_deletes=True)


class ReviewFlag(db.Model):
    __tablename__ = "review_flags"
    __table_args__ = (
        UniqueConstraint("transaction_id", "rule_name", name="uq_review_transaction_rule"),
        CheckConstraint(
            "review_status IN ('Pending', 'Reviewed', 'Dismissed')", name="ck_review_flags_status"
        ),
    )

    review_id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(
        db.Integer, db.ForeignKey("transactions.transaction_id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_name = db.Column(db.String(80), nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    review_status = db.Column(db.String(10), nullable=False, default="Pending", index=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.current_timestamp())
    reviewed_at = db.Column(db.DateTime, nullable=True)
    transaction = db.relationship("Transaction", back_populates="review_flags")


class AppSetting(db.Model):
    __tablename__ = "app_settings"

    setting_key = db.Column(db.String(80), primary_key=True)
    setting_value = db.Column(db.String(255), nullable=False)
    updated_at = db.Column(
        db.DateTime, nullable=False, server_default=db.func.current_timestamp(), onupdate=db.func.current_timestamp()
    )


def initialize_database(app):
    """Create the configured database when possible, then create missing tables."""
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if uri.startswith("sqlite"):
        with app.app_context():
            db.create_all()
        return

    parsed = urlsplit(uri)
    database_name = parsed.path.lstrip("/")
    if not database_name:
        raise RuntimeError("DATABASE_URL must include a database name.")
    admin_uri = urlunsplit((parsed.scheme, parsed.netloc, "/", parsed.query, parsed.fragment))
    engine = create_engine(admin_uri, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(f"CREATE DATABASE IF NOT EXISTS `{database_name.replace('`', '')}` "
                     "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            )
    except SQLAlchemyError as exc:
        raise RuntimeError(
            "Could not connect to MySQL or create the configured database. Check MySQL is running "
            "and that DB_USER has permission to create databases, or create it manually."
        ) from exc
    finally:
        engine.dispose()
    with app.app_context():
        db.create_all()
        db.session.execute(
            db.insert(AppSetting).prefix_with("IGNORE"),
            [{"setting_key": "unusual_amount_threshold",
              "setting_value": str(app.config["UNUSUAL_AMOUNT_THRESHOLD"])}],
        )
        db.session.commit()


def money_value(value):
    return Decimal(value).quantize(Decimal("0.01"))
