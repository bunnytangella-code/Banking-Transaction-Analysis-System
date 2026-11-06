import csv
import io
import os
import secrets
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from flask import (
    Flask, Response, abort, flash, jsonify, make_response, redirect, render_template,
    request, send_file, session, url_for,
)
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from analytics import (
    account_summary, customer_summary, daily_volume, monthly_summary, overall_summary,
    statistics, transaction_type_summary, transactions_frame,
)
from config import Config
from db import Account, AppSetting, Customer, ReviewFlag, Transaction, db, initialize_database

csrf = CSRFProtect()
ACCOUNT_TYPES = ("Savings", "Current", "Fixed Deposit")
TRANSACTION_TYPES = ("Deposit", "Withdrawal")
REVIEW_STATUSES = ("Pending", "Reviewed", "Dismissed")


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    db.init_app(app)
    csrf.init_app(app)

    @app.template_filter("inr")
    def format_inr(value):
        try:
            amount = Decimal(str(value)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError, TypeError):
            amount = Decimal("0.00")
        sign = "-" if amount < 0 else ""
        whole, fraction = f"{abs(amount):.2f}".split(".")
        if len(whole) > 3:
            whole = f"{whole[:-3]},{whole[-3:]}"
            prefix, suffix = whole.rsplit(",", 1)
            groups = []
            while prefix:
                groups.insert(0, prefix[-2:])
                prefix = prefix[:-2]
            whole = ",".join(groups + [suffix])
        return f"{sign}₹{whole}.{fraction}"

    @app.context_processor
    def common_template_values():
        return {"current_year": datetime.now().year}

    def setting(key, default):
        row = db.session.get(AppSetting, key)
        return row.setting_value if row else str(default)

    def threshold_value():
        try:
            amount = Decimal(setting("unusual_amount_threshold", app.config["UNUSUAL_AMOUNT_THRESHOLD"]))
            if amount <= 0:
                raise InvalidOperation
            return amount
        except (InvalidOperation, ValueError):
            return Decimal("50000")

    def filtered_transactions():
        query = Transaction.query.join(Account).join(Customer)
        search = request.args.get("q", "").strip()
        if search:
            conditions = [Customer.display_name.ilike(f"%{search}%")]
            if search.isdigit():
                conditions += [Transaction.transaction_id == int(search), Account.account_id == int(search)]
            query = query.filter(or_(*conditions))
        account_id = request.args.get("account_id", type=int)
        if account_id:
            query = query.filter(Transaction.account_id == account_id)
        transaction_type = request.args.get("type", "")
        if transaction_type in TRANSACTION_TYPES:
            query = query.filter(Transaction.transaction_type == transaction_type)
        review_status = request.args.get("review_status", "")
        if review_status in REVIEW_STATUSES:
            query = query.filter(Transaction.review_flags.any(ReviewFlag.review_status == review_status))
        start = parse_date(request.args.get("start"))
        end = parse_date(request.args.get("end"), end=True)
        if start:
            query = query.filter(Transaction.transaction_date >= start)
        if end:
            query = query.filter(Transaction.transaction_date <= end)
        return query.order_by(Transaction.transaction_date.desc(), Transaction.transaction_id.desc())

    def filtered_review_flags():
        query = ReviewFlag.query.join(Transaction)
        account_id = request.args.get("account_id", type=int)
        if account_id:
            query = query.filter(Transaction.account_id == account_id)
        transaction_type = request.args.get("type", "")
        if transaction_type in TRANSACTION_TYPES:
            query = query.filter(Transaction.transaction_type == transaction_type)
        start = parse_date(request.args.get("start"))
        end = parse_date(request.args.get("end"), end=True)
        if start:
            query = query.filter(Transaction.transaction_date >= start)
        if end:
            query = query.filter(Transaction.transaction_date <= end)
        return query

    @app.get("/health")
    def health():
        try:
            db.session.execute(select(1))
            return jsonify(status="ok", database="connected")
        except SQLAlchemyError:
            db.session.rollback()
            return jsonify(status="error", database="unavailable"), 503

    @app.get("/login")
    def login():
        return redirect(url_for("dashboard"))

    @app.get("/")
    @app.get("/dashboard")
    def dashboard():
        totals = db.session.query(
            func.count(Transaction.transaction_id),
            func.coalesce(func.sum(
                case((Transaction.transaction_type == "Deposit", Transaction.amount), else_=0)
            ), 0),
            func.coalesce(func.sum(
                case((Transaction.transaction_type == "Withdrawal", Transaction.amount), else_=0)
            ), 0),
        ).one()
        frame = transactions_frame(Transaction.query.order_by(Transaction.transaction_date).all())
        metrics = {
            "customers": Customer.query.count(),
            "accounts": Account.query.count(),
            "deposits": totals[1],
            "withdrawals": totals[2],
            "transaction_count": totals[0],
            "balances": db.session.query(func.coalesce(func.sum(Account.current_balance), 0)).scalar(),
            "pending_reviews": ReviewFlag.query.filter_by(review_status="Pending").count(),
        }
        recent = Transaction.query.order_by(Transaction.transaction_date.desc()).limit(6).all()
        return render_template("dashboard.html", metrics=metrics, recent=recent,
                               has_data=not frame.empty)

    @app.get("/customers")
    def customers():
        query = Customer.query
        term = request.args.get("q", "").strip()
        if term:
            query = query.filter(or_(Customer.display_name.ilike(f"%{term}%"),
                                     Customer.customer_id == (int(term) if term.isdigit() else -1)))
        page = query.order_by(Customer.created_at.desc(), Customer.customer_id.desc()).paginate(
            page=max(request.args.get("page", 1, type=int), 1), per_page=12, error_out=False
        )
        return render_template("customers.html", page=page, search=term)

    @app.route("/customers/new", methods=["GET", "POST"])
    def customer_new():
        if request.method == "POST":
            name, error = validate_name(request.form.get("display_name", ""))
            if error:
                flash(error, "danger")
            else:
                db.session.add(Customer(display_name=name))
                db.session.commit()
                flash("Customer created.", "success")
                return redirect(url_for("customers"))
        return render_template("customer_form.html", customer=None)

    @app.get("/customers/<int:customer_id>")
    def customer_detail(customer_id):
        customer = db.get_or_404(Customer, customer_id)
        return render_template("customer_detail.html", customer=customer)

    @app.route("/customers/<int:customer_id>/edit", methods=["GET", "POST"])
    def customer_edit(customer_id):
        customer = db.get_or_404(Customer, customer_id)
        if request.method == "POST":
            name, error = validate_name(request.form.get("display_name", ""))
            if error:
                flash(error, "danger")
            else:
                customer.display_name = name
                db.session.commit()
                flash("Customer updated.", "success")
                return redirect(url_for("customer_detail", customer_id=customer_id))
        return render_template("customer_form.html", customer=customer)

    @app.post("/customers/<int:customer_id>/delete")
    def customer_delete(customer_id):
        customer = db.get_or_404(Customer, customer_id)
        if customer.accounts:
            flash("This customer has accounts and cannot be deleted.", "warning")
        else:
            db.session.delete(customer)
            db.session.commit()
            flash("Customer deleted.", "success")
        return redirect(url_for("customers"))

    @app.get("/accounts")
    def accounts():
        query = Account.query.join(Customer)
        term = request.args.get("q", "").strip()
        if term:
            conditions = [Customer.display_name.ilike(f"%{term}%")]
            if term.isdigit():
                conditions.append(Account.account_id == int(term))
            query = query.filter(or_(*conditions))
        status = request.args.get("status", "")
        if status in ("Active", "Inactive"):
            query = query.filter(Account.status == status)
        page = query.order_by(Account.created_at.desc()).paginate(
            page=max(request.args.get("page", 1, type=int), 1), per_page=12, error_out=False
        )
        return render_template("accounts.html", page=page, search=term, status=status)

    @app.route("/accounts/new", methods=["GET", "POST"])
    def account_new():
        customers_list = Customer.query.order_by(Customer.display_name).all()
        selected_customer_id = request.args.get("customer_id", type=int)
        if request.method == "POST":
            customer_id = request.form.get("customer_id", type=int)
            account_type = request.form.get("account_type", "")
            balance, error = validate_opening_balance(request.form.get("opening_balance", "0"))
            customer = db.session.get(Customer, customer_id) if customer_id else None
            if not customer:
                flash("Choose an existing customer.", "danger")
            elif account_type not in ACCOUNT_TYPES:
                flash("Choose a valid account type.", "danger")
            elif error:
                flash(error, "danger")
            else:
                db.session.add(Account(customer_id=customer.customer_id, account_type=account_type,
                                       opening_balance=balance, current_balance=balance))
                db.session.commit()
                flash("Account created.", "success")
                return redirect(url_for("customer_detail", customer_id=customer.customer_id))
        return render_template("account_form.html", customers=customers_list, account=None,
                               account_types=ACCOUNT_TYPES, selected_customer_id=selected_customer_id)

    @app.get("/accounts/<int:account_id>")
    def account_detail(account_id):
        account = db.get_or_404(Account, account_id)
        txns = Transaction.query.filter_by(account_id=account_id).order_by(
            Transaction.transaction_date.desc()
        ).limit(25).all()
        deposits = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter_by(
            account_id=account_id, transaction_type="Deposit"
        ).scalar()
        withdrawals = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter_by(
            account_id=account_id, transaction_type="Withdrawal"
        ).scalar()
        return render_template("account_detail.html", account=account, transactions=txns,
                               deposits=deposits, withdrawals=withdrawals)

    @app.post("/accounts/<int:account_id>/status")
    def account_status(account_id):
        account = db.get_or_404(Account, account_id)
        account.status = "Inactive" if account.status == "Active" else "Active"
        db.session.commit()
        flash(f"Account marked {account.status.lower()}.", "success")
        return redirect(url_for("account_detail", account_id=account_id))

    @app.post("/accounts/<int:account_id>/delete")
    def account_delete(account_id):
        account = db.get_or_404(Account, account_id)
        if account.transactions:
            flash("Accounts with transaction history cannot be deleted. Deactivate it instead.", "warning")
        else:
            db.session.delete(account)
            db.session.commit()
            flash("Account deleted.", "success")
        return redirect(url_for("accounts"))

    @app.get("/transactions")
    def transactions():
        page = filtered_transactions().paginate(
            page=max(request.args.get("page", 1, type=int), 1), per_page=15, error_out=False
        )
        account_options = Account.query.join(Customer).order_by(Account.account_id).all()
        return render_template("transactions.html", page=page, accounts=account_options,
                               current_filters=request.args)

    @app.route("/transactions/new", methods=["GET", "POST"])
    def transaction_new():
        accounts_list = Account.query.join(Customer).filter(Account.status == "Active").order_by(
            Account.account_id
        ).all()
        selected_account_id = request.args.get("account_id", type=int)
        if request.method == "POST":
            token = request.form.get("submission_token", "")
            allowed_tokens = session.get("transaction_tokens", [])
            if not token or token not in allowed_tokens:
                abort(409, description="This form was already submitted or has expired. Reload it and try again.")
            account_id = request.form.get("account_id", type=int)
            transaction_type = request.form.get("transaction_type", "")
            amount, amount_error = validate_amount(request.form.get("amount", ""))
            tx_date, date_error = parse_transaction_date(request.form.get("transaction_date", ""))
            account = db.session.execute(
                select(Account).where(Account.account_id == account_id).with_for_update()
            ).scalar_one_or_none() if account_id else None
            if not account or account.status != "Active":
                flash("Choose an existing active account.", "danger")
            elif transaction_type not in TRANSACTION_TYPES:
                flash("Choose Deposit or Withdrawal.", "danger")
            elif amount_error:
                flash(amount_error, "danger")
            elif date_error:
                flash(date_error, "danger")
            elif transaction_type == "Withdrawal" and amount > account.current_balance:
                flash("The withdrawal cannot exceed the available simulated balance.", "danger")
            else:
                try:
                    description = request.form.get("description", "").strip()
                    if len(description) > 255:
                        flash("Description must be 255 characters or fewer.", "danger")
                        return render_template("transaction_form.html", accounts=accounts_list, token=token,
                                               selected_account_id=account_id,
                                               now=datetime.now().strftime("%Y-%m-%dT%H:%M"))
                    txn = Transaction(account_id=account.account_id, transaction_date=tx_date,
                                      transaction_type=transaction_type, amount=amount,
                                      description=description or None)
                    db.session.add(txn)
                    delta = amount if transaction_type == "Deposit" else -amount
                    account.current_balance = Decimal(account.current_balance) + delta
                    db.session.flush()
                    evaluate_review_rules(txn, account, threshold_value())
                    db.session.commit()
                    session["transaction_tokens"] = [value for value in allowed_tokens if value != token]
                    flash("Transaction recorded and simulated balance updated.", "success")
                    return redirect(url_for("transaction_detail", transaction_id=txn.transaction_id))
                except (IntegrityError, SQLAlchemyError):
                    db.session.rollback()
                    app.logger.exception("Transaction could not be committed.")
                    flash("The transaction could not be saved. No account balance was changed.", "danger")
        token = secrets.token_urlsafe(24)
        tokens = session.get("transaction_tokens", [])
        session["transaction_tokens"] = (tokens + [token])[-4:]
        return render_template("transaction_form.html", accounts=accounts_list, token=token,
                               selected_account_id=selected_account_id,
                               now=datetime.now().strftime("%Y-%m-%dT%H:%M"))

    def render_transfer_form(accounts_list, token, source_id=None, destination_id=None):
        return render_template(
            "transfer_form.html",
            accounts=accounts_list,
            token=token,
            selected_source_id=source_id,
            selected_destination_id=destination_id,
            now=datetime.now().strftime("%Y-%m-%dT%H:%M"),
        )

    @app.route("/transfers/new", methods=["GET", "POST"])
    def transfer_new():
        accounts_list = Account.query.join(Customer).filter(Account.status == "Active").order_by(
            Account.account_id
        ).all()
        selected_source_id = request.values.get("from_account_id", type=int)
        if request.method == "POST":
            token = request.form.get("submission_token", "")
            allowed_tokens = session.get("transfer_tokens", [])
            if not token or token not in allowed_tokens:
                abort(409, description="This transfer form was already submitted or has expired. Reload it and try again.")

            source_id = request.form.get("from_account_id", type=int)
            destination_id = request.form.get("to_account_id", type=int)
            amount, amount_error = validate_amount(request.form.get("amount", ""))
            tx_date, date_error = parse_transaction_date(request.form.get("transaction_date", ""))
            description = request.form.get("description", "").strip()
            if len(description) > 180:
                flash("Description must be 180 characters or fewer.", "danger")
                return render_transfer_form(accounts_list, token, source_id, destination_id)

            accounts_by_id = {}
            if source_id and destination_id and source_id != destination_id:
                locked_accounts = db.session.execute(
                    select(Account).where(Account.account_id.in_((source_id, destination_id)))
                    .order_by(Account.account_id).with_for_update()
                ).scalars().all()
                accounts_by_id = {account.account_id: account for account in locked_accounts}
            source = accounts_by_id.get(source_id)
            destination = accounts_by_id.get(destination_id)

            if not source or not destination:
                flash("Choose two different existing accounts.", "danger")
            elif source.status != "Active" or destination.status != "Active":
                flash("Both accounts must be active to transfer money.", "danger")
            elif amount_error:
                flash(amount_error, "danger")
            elif date_error:
                flash(date_error, "danger")
            elif amount > source.current_balance:
                flash("The transfer cannot exceed the source account's available balance.", "danger")
            else:
                try:
                    suffix = f" · {description}" if description else ""
                    debit = Transaction(
                        account_id=source.account_id,
                        transaction_date=tx_date,
                        transaction_type="Withdrawal",
                        amount=amount,
                        description=f"Transfer to account #{destination.account_id}{suffix}",
                    )
                    credit = Transaction(
                        account_id=destination.account_id,
                        transaction_date=tx_date,
                        transaction_type="Deposit",
                        amount=amount,
                        description=f"Transfer from account #{source.account_id}{suffix}",
                    )
                    db.session.add_all((debit, credit))
                    source.current_balance = Decimal(source.current_balance) - amount
                    destination.current_balance = Decimal(destination.current_balance) + amount
                    db.session.flush()
                    threshold = threshold_value()
                    evaluate_review_rules(debit, source, threshold)
                    evaluate_review_rules(credit, destination, threshold)
                    db.session.commit()
                    session["transfer_tokens"] = [
                        value for value in allowed_tokens if value != token
                    ]
                    flash(
                        f"Transfer completed: {amount} moved from account #{source.account_id} "
                        f"to account #{destination.account_id}.",
                        "success",
                    )
                    return redirect(url_for("transaction_detail", transaction_id=debit.transaction_id))
                except (IntegrityError, SQLAlchemyError):
                    db.session.rollback()
                    app.logger.exception("Account transfer could not be committed.")
                    flash("The transfer could not be saved. No account balances were changed.", "danger")

        token = secrets.token_urlsafe(24)
        tokens = session.get("transfer_tokens", [])
        session["transfer_tokens"] = (tokens + [token])[-4:]
        return render_transfer_form(accounts_list, token, selected_source_id,
                                    request.values.get("to_account_id", type=int))

    @app.get("/transactions/<int:transaction_id>")
    def transaction_detail(transaction_id):
        txn = db.get_or_404(Transaction, transaction_id)
        return render_template("transaction_detail.html", txn=txn)

    @app.get("/transactions/<int:transaction_id>/receipt")
    def transaction_receipt(transaction_id):
        txn = db.get_or_404(Transaction, transaction_id)
        return render_template("transaction_receipt.html", txn=txn)

    @app.get("/transactions/<int:transaction_id>/receipt/download")
    def download_transaction_receipt(transaction_id):
        txn = db.get_or_404(Transaction, transaction_id)
        if txn.description and txn.description.startswith("Transfer from account #"):
            transaction_label = "Transfer in"
        elif txn.description and txn.description.startswith("Transfer to account #"):
            transaction_label = "Transfer out"
        else:
            transaction_label = txn.transaction_type
        fig, axis = plt.subplots(figsize=(8.27, 11.69))
        axis.set_axis_off()
        axis.text(0.08, 0.92, "BankSight", fontsize=24, fontweight="bold", color="#192545",
                  transform=axis.transAxes)
        axis.text(0.08, 0.885, "SIMULATED TRANSACTION RECEIPT", fontsize=10, color="#68738a",
                  transform=axis.transAxes)
        axis.text(0.08, 0.82, f"Transaction #{txn.transaction_id}", fontsize=16, fontweight="bold",
                  transform=axis.transAxes)
        axis.text(0.08, 0.77, transaction_label, fontsize=12, color="#68738a",
                  transform=axis.transAxes)
        amount = app.jinja_env.filters["inr"](txn.amount).replace("₹", "INR ")
        axis.text(0.08, 0.72, f"{'+' if txn.transaction_type == 'Deposit' else '-'}{amount}",
                  fontsize=24, fontweight="bold", color="#258265" if txn.transaction_type == "Deposit"
                  else "#bb5263", transform=axis.transAxes)
        axis.plot([0.08, 0.92], [0.67, 0.67], color="#e6e9f0", transform=axis.transAxes)

        receipt_rows = (
            ("Customer", txn.account.customer.display_name),
            ("Account", f"#{txn.account_id} - {txn.account.account_type}"),
            ("Transaction type", transaction_label),
            ("Date and time", txn.transaction_date.strftime("%d %B %Y, %H:%M")),
            ("Description", txn.description or "No description"),
        )
        y_position = 0.62
        for label, value in receipt_rows:
            axis.text(0.08, y_position, label, fontsize=10, color="#68738a",
                      transform=axis.transAxes)
            axis.text(0.92, y_position, value, fontsize=11, ha="right", wrap=True,
                      transform=axis.transAxes)
            y_position -= 0.065

        axis.plot([0.08, 0.92], [y_position + 0.025, y_position + 0.025],
                  color="#e6e9f0", transform=axis.transAxes)
        axis.text(0.08, y_position - 0.03,
                  "Educational simulation only. This is not a real bank receipt and no real funds were transferred.",
                  fontsize=9, color="#68738a", wrap=True, transform=axis.transAxes)
        pdf = io.BytesIO()
        fig.savefig(pdf, format="pdf", bbox_inches="tight")
        plt.close(fig)
        pdf.seek(0)
        return send_file(pdf, mimetype="application/pdf", as_attachment=True,
                         download_name=f"banksight-receipt-{txn.transaction_id}.pdf")

    @app.get("/analytics")
    def analytics_page():
        frame = transactions_frame(filtered_transactions().all())
        return render_template("analytics.html", stats=statistics(frame), has_data=not frame.empty)

    @app.get("/api/dashboard")
    @app.get("/api/analytics/monthly")
    def api_monthly():
        frame = transactions_frame(filtered_transactions().all())
        balances = Account.query.join(Customer).order_by(Account.current_balance.desc()).limit(10).all()
        monthly = [{**item, "deposits": float(item["deposits"]),
                    "withdrawals": float(item["withdrawals"])} for item in monthly_summary(frame)]
        types = [{**item, "total": float(item["total"])} for item in transaction_type_summary(frame)]
        accounts = [{**item, "transaction_total": float(item["transaction_total"])}
                    for item in account_summary(frame)]
        return jsonify(monthly=monthly, volume=daily_volume(frame),
                       types=types, accounts=accounts,
                       balances=[{"account_id": item.account_id,
                                  "customer_name": item.customer.display_name,
                                  "balance": float(item.current_balance)} for item in balances])

    @app.get("/reports")
    def reports():
        frame = transactions_frame(filtered_transactions().all())
        customer_accounts = db.session.query(
            Customer.customer_id, Customer.display_name,
            func.count(Account.account_id).label("account_count"),
            func.coalesce(func.sum(Account.current_balance), 0).label("simulated_balance"),
        ).outerjoin(Account).group_by(Customer.customer_id, Customer.display_name).order_by(
            Customer.display_name
        ).all()
        return render_template("reports.html", summary=overall_summary(frame),
                               monthly=monthly_summary(frame), has_data=not frame.empty,
                               accounts=account_summary(frame),
                               types=transaction_type_summary(frame),
                               volume=daily_volume(frame),
                               customers=customer_summary(frame),
                               customer_accounts=customer_accounts,
                               review_count=filtered_review_flags().count(),
                               account_options=Account.query.join(Customer).order_by(Account.account_id).all(),
                               current_filters=request.args)

    @app.get("/exports/transactions.csv")
    def export_transactions():
        records = filtered_transactions().all()
        frame = transactions_frame(records)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Transaction ID", "Account ID", "Customer", "Date", "Type",
                         "Amount (INR)", "Description"])
        for row in frame.itertuples(index=False):
            writer.writerow([row.transaction_id, row.account_id, csv_safe(row.customer_name),
                             row.transaction_date.isoformat(), row.transaction_type,
                             f"{row.amount:.2f}", csv_safe(row.description)])
        return csv_response(output.getvalue(), "banksight-transactions.csv")

    @app.get("/exports/report.csv")
    def export_report():
        frame = transactions_frame(filtered_transactions().all())
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Report", "BankSight simulated transaction summary"])
        writer.writerow(["Generated at", datetime.now().isoformat(timespec="seconds")])
        writer.writerow(["Transactions", len(frame)])
        summary = overall_summary(frame)
        writer.writerow(["Deposits (INR)", f"{summary['deposits']:.2f}"])
        writer.writerow(["Withdrawals (INR)", f"{summary['withdrawals']:.2f}"])
        writer.writerow([])
        writer.writerow(["Month", "Deposits (INR)", "Withdrawals (INR)"])
        for row in monthly_summary(frame):
            writer.writerow([row["month"], f"{row['deposits']:.2f}", f"{row['withdrawals']:.2f}"])
        writer.writerow([])
        writer.writerow(["Account-wise summary"])
        writer.writerow(["Account ID", "Customer", "Transactions", "Amount volume (INR)"])
        for row in account_summary(frame):
            writer.writerow([row["account_id"], csv_safe(row["customer_name"]),
                             row["transaction_count"], f"{row['transaction_total']:.2f}"])
        writer.writerow([])
        writer.writerow(["Customer-wise summary"])
        writer.writerow(["Customer", "Transactions", "Amount volume (INR)"])
        for row in customer_summary(frame):
            writer.writerow([csv_safe(row["customer_name"]), row["transaction_count"],
                             f"{row['transaction_total']:.2f}"])
        writer.writerow([])
        writer.writerow(["Transaction-type breakdown"])
        writer.writerow(["Type", "Transactions", "Total (INR)"])
        for row in transaction_type_summary(frame):
            writer.writerow([row["type"], row["count"], f"{row['total']:.2f}"])
        writer.writerow([])
        writer.writerow(["Rule-based review report"])
        writer.writerow(["Review ID", "Transaction ID", "Rule", "Reason", "Status", "Created at"])
        for flag in filtered_review_flags().order_by(ReviewFlag.created_at.desc()).all():
            writer.writerow([flag.review_id, flag.transaction_id, csv_safe(flag.rule_name),
                             csv_safe(flag.reason), flag.review_status,
                             flag.created_at.isoformat() if flag.created_at else ""])
        return csv_response(output.getvalue(), "banksight-summary.csv")

    @app.get("/exports/monthly-chart.png")
    def export_chart():
        data = monthly_summary(transactions_frame(filtered_transactions().all()))
        if not data:
            flash("There is no transaction data to chart yet.", "warning")
            return redirect(url_for("reports"))
        fig, axis = plt.subplots(figsize=(9, 4.8))
        labels = [row["month"] for row in data]
        x = range(len(labels))
        axis.bar([i - 0.19 for i in x], [float(row["deposits"]) for row in data],
                 width=0.38, label="Deposits", color="#3f62d8")
        axis.bar([i + 0.19 for i in x], [float(row["withdrawals"]) for row in data],
                 width=0.38, label="Withdrawals", color="#19a889")
        axis.set_title("Monthly deposits and withdrawals — simulated INR")
        axis.set_ylabel("Amount (₹)")
        axis.set_xticks(list(x), labels, rotation=30, ha="right")
        axis.legend(frameon=False)
        axis.grid(axis="y", alpha=0.2)
        fig.tight_layout()
        image = io.BytesIO()
        fig.savefig(image, format="png", dpi=160)
        plt.close(fig)
        image.seek(0)
        return send_file(image, mimetype="image/png", as_attachment=True,
                         download_name="banksight-monthly-analysis.png")

    @app.get("/review-queue")
    def review_queue():
        query = ReviewFlag.query.join(Transaction).join(Account).join(Customer)
        status = request.args.get("status", "Pending")
        if status in REVIEW_STATUSES:
            query = query.filter(ReviewFlag.review_status == status)
        flags = query.order_by(ReviewFlag.created_at.desc()).paginate(
            page=max(request.args.get("page", 1, type=int), 1), per_page=15, error_out=False
        )
        return render_template("review_queue.html", page=flags, status=status)

    @app.post("/review-queue/<int:review_id>")
    def review_update(review_id):
        flag = db.get_or_404(ReviewFlag, review_id)
        status = request.form.get("review_status", "")
        if status not in ("Reviewed", "Dismissed"):
            abort(400, description="Choose Reviewed or Dismissed.")
        flag.review_status = status
        flag.reviewed_at = datetime.now()
        db.session.commit()
        flash(f"Review flag marked {status.lower()}.", "success")
        return redirect(url_for("review_queue"))

    @app.route("/settings", methods=["GET", "POST"])
    def settings():
        if request.method == "POST":
            amount, error = validate_amount(request.form.get("unusual_amount_threshold", ""))
            if error:
                flash("Enter a threshold greater than zero.", "danger")
            else:
                row = db.session.get(AppSetting, "unusual_amount_threshold")
                if not row:
                    row = AppSetting(setting_key="unusual_amount_threshold", setting_value=str(amount))
                    db.session.add(row)
                else:
                    row.setting_value = str(amount)
                db.session.commit()
                flash("Review threshold updated. It applies to future transactions.", "success")
                return redirect(url_for("settings"))
        return render_template("settings.html", threshold=threshold_value())

    @app.post("/demo-data")
    def load_demo_data():
        if db.session.get(AppSetting, "demo_data_loaded"):
            flash("Synthetic demonstration data has already been loaded.", "info")
            return redirect(url_for("dashboard"))
        try:
            seed_demo_data(threshold_value())
            db.session.commit()
            flash("Synthetic demonstration data loaded successfully.", "success")
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.exception("Synthetic demo data could not be loaded.")
            flash("Demo data could not be loaded. Check database logs and try again.", "danger")
        return redirect(url_for("dashboard"))

    @app.errorhandler(404)
    def not_found(error):
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        app.logger.error("Unhandled application error: %s", error)
        return render_template("500.html"), 500

    return app


def parse_date(value, end=False):
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
        return parsed.replace(hour=23, minute=59, second=59) if end else parsed
    except ValueError:
        return None


def parse_transaction_date(value):
    try:
        parsed = datetime.fromisoformat(value)
        if parsed > datetime.now() + timedelta(minutes=5):
            return None, "Transaction date cannot be in the future."
        return parsed, None
    except (ValueError, TypeError):
        return None, "Enter a valid transaction date and time."


def validate_name(value):
    name = " ".join(value.split())
    if not name or len(name) > 100:
        return None, "Display name is required and must be 100 characters or fewer."
    if any(ord(char) < 32 for char in name):
        return None, "Display name contains invalid characters."
    return name, None


def validate_amount(value):
    try:
        amount = Decimal(value).quantize(Decimal("0.01"))
        if not amount.is_finite() or amount <= 0 or amount > Decimal("9999999999999.99"):
            raise InvalidOperation
        return amount, None
    except (InvalidOperation, ValueError, TypeError):
        return None, "Enter a valid amount greater than ₹0.00."


def validate_opening_balance(value):
    try:
        amount = Decimal(value).quantize(Decimal("0.01"))
        if not amount.is_finite() or amount < 0 or amount > Decimal("9999999999999.99"):
            raise InvalidOperation
        return amount, None
    except (InvalidOperation, ValueError, TypeError):
        return None, "Enter a valid opening balance of ₹0.00 or more."


def evaluate_review_rules(txn, account, threshold):
    if txn.amount >= threshold:
        create_flag(txn, "Large amount", f"Amount is at or above the configurable threshold of ₹{threshold:,.2f}.")
    recent_count = Transaction.query.filter(
        Transaction.account_id == account.account_id,
        Transaction.transaction_date >= txn.transaction_date - timedelta(minutes=10),
        Transaction.transaction_id != txn.transaction_id,
    ).count()
    if recent_count >= 2:
        create_flag(txn, "Rapid activity", "At least three transactions occurred on this account within 10 minutes.")
    previous = Transaction.query.filter(
        Transaction.account_id == account.account_id,
        Transaction.transaction_id != txn.transaction_id,
    ).with_entities(func.avg(Transaction.amount)).scalar()
    if previous and txn.amount >= Decimal(str(previous)) * Decimal("3"):
        create_flag(txn, "Above account average", "Amount is at least three times this account's historical average.")


def create_flag(txn, name, reason):
    if not ReviewFlag.query.filter_by(transaction_id=txn.transaction_id, rule_name=name).first():
        db.session.add(ReviewFlag(transaction_id=txn.transaction_id, rule_name=name, reason=reason))


def seed_demo_data(unusual_threshold):
    names = ["Aarav Mehta", "Isha Nair", "Kabir Shah", "Mira Iyer", "Dev Patel"]
    customers = [Customer(display_name=name) for name in names]
    db.session.add_all(customers)
    db.session.flush()
    accounts = []
    for index, customer in enumerate(customers):
        account = Account(customer_id=customer.customer_id, account_type=ACCOUNT_TYPES[index % 3],
                          opening_balance=Decimal("25000.00"), current_balance=Decimal("25000.00"))
        accounts.append(account)
    db.session.add_all(accounts)
    db.session.flush()
    now = datetime.now().replace(second=0, microsecond=0)
    transactions_to_add = []
    for index, account in enumerate(accounts):
        for month in range(5, -1, -1):
            date = (now.replace(day=1) - timedelta(days=month * 30)).replace(day=min(4 + index, 28), hour=10)
            deposit = Decimal(str(3500 + (index * 900) + (month * 250))).quantize(Decimal("0.01"))
            withdrawal = Decimal(str(1200 + index * 250)).quantize(Decimal("0.01"))
            transactions_to_add.extend([
                Transaction(account_id=account.account_id, transaction_date=date,
                            transaction_type="Deposit", amount=deposit,
                            description="Demonstration monthly income"),
                Transaction(account_id=account.account_id, transaction_date=date + timedelta(days=8),
                            transaction_type="Withdrawal", amount=withdrawal,
                            description="Demonstration household expense"),
            ])
    transactions_to_add.append(Transaction(
        account_id=accounts[0].account_id, transaction_date=now - timedelta(days=3),
        transaction_type="Deposit", amount=Decimal("62500.00"),
        description="Demonstration large transfer",
    ))
    db.session.add_all(transactions_to_add)
    db.session.flush()
    for account in accounts:
        total_deposits = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter_by(
            account_id=account.account_id, transaction_type="Deposit"
        ).scalar()
        total_withdrawals = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter_by(
            account_id=account.account_id, transaction_type="Withdrawal"
        ).scalar()
        account.current_balance = account.opening_balance + Decimal(total_deposits) - Decimal(total_withdrawals)
    for txn in transactions_to_add:
        evaluate_review_rules(txn, txn.account, unusual_threshold)
    db.session.add(AppSetting(setting_key="demo_data_loaded", setting_value="true"))


def csv_response(contents, filename):
    response = make_response("\ufeff" + contents)
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def csv_safe(value):
    text_value = str(value or "")
    if text_value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text_value
    return text_value


app = create_app()


if __name__ == "__main__":
    try:
        initialize_database(app)
    except (RuntimeError, SQLAlchemyError) as exc:
        raise SystemExit(f"BankSight startup failed: {exc}") from exc
    print("BankSight development server: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=app.config["SESSION_COOKIE_SECURE"] is False)
