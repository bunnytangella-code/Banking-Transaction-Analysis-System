from decimal import Decimal

import numpy as np
import pandas as pd


def transactions_frame(records):
    columns = ["transaction_id", "account_id", "customer_name", "transaction_date",
               "transaction_type", "amount", "description"]
    rows = []
    for item in records:
        rows.append({
            "transaction_id": item.transaction_id,
            "account_id": item.account_id,
            "customer_name": item.account.customer.display_name,
            "transaction_date": item.transaction_date,
            "transaction_type": item.transaction_type,
            "amount": Decimal(item.amount),
            "description": item.description or "",
        })
    frame = pd.DataFrame(rows, columns=columns)
    if not frame.empty:
        frame["transaction_date"] = pd.to_datetime(frame["transaction_date"])
        frame["month"] = frame["transaction_date"].dt.to_period("M").astype(str)
        frame["day"] = frame["transaction_date"].dt.strftime("%Y-%m-%d")
        frame["amount_numeric"] = frame["amount"].map(float)
    return frame


def monthly_summary(frame):
    if frame.empty:
        return []
    grouped = frame.groupby(["month", "transaction_type"])["amount"].sum()
    months = sorted(frame["month"].unique())
    return [{
        "month": str(month),
        "deposits": grouped.get((month, "Deposit"), Decimal("0.00")),
        "withdrawals": grouped.get((month, "Withdrawal"), Decimal("0.00")),
    } for month in months]


def daily_volume(frame):
    if frame.empty:
        return []
    grouped = frame.groupby("day").size()
    return [{"day": str(day), "count": int(count)} for day, count in grouped.items()]


def transaction_type_summary(frame):
    if frame.empty:
        return []
    grouped = frame.groupby("transaction_type").agg(
        total=("amount", "sum"), count=("transaction_id", "count")
    )
    return [{"type": str(kind), "total": row["total"], "count": int(row["count"])}
            for kind, row in grouped.iterrows()]


def account_summary(frame):
    if frame.empty:
        return []
    grouped = frame.groupby(["account_id", "customer_name"]).agg(
        transaction_count=("transaction_id", "count"), transaction_total=("amount", "sum")
    ).reset_index()
    grouped = grouped.sort_values(["transaction_count", "transaction_total"], ascending=False)
    return grouped.head(10).to_dict(orient="records")


def customer_summary(frame):
    if frame.empty:
        return []
    grouped = frame.groupby("customer_name").agg(
        transaction_count=("transaction_id", "count"),
        transaction_total=("amount", "sum"),
    ).reset_index().sort_values(["transaction_count", "transaction_total"], ascending=False)
    return grouped.to_dict(orient="records")


def statistics(frame):
    if frame.empty:
        return {"count": 0, "mean": None, "median": None, "std_dev": None,
                "minimum": None, "maximum": None, "p95": None}
    amounts = frame["amount_numeric"].to_numpy(dtype=float)
    return {
        "count": int(amounts.size),
        "mean": round(float(np.mean(amounts)), 2),
        "median": round(float(np.median(amounts)), 2),
        "std_dev": round(float(np.std(amounts)), 2),
        "minimum": round(float(np.min(amounts)), 2),
        "maximum": round(float(np.max(amounts)), 2),
        "p95": round(float(np.percentile(amounts, 95)), 2),
    }


def overall_summary(frame):
    if frame.empty:
        return {"transaction_count": 0, "deposits": Decimal("0.00"),
                "withdrawals": Decimal("0.00"), "average_amount": None}
    deposit_total = sum(
        (value for value, kind in zip(frame["amount"], frame["transaction_type"]) if kind == "Deposit"),
        Decimal("0.00"),
    )
    withdrawal_total = sum(
        (value for value, kind in zip(frame["amount"], frame["transaction_type"]) if kind == "Withdrawal"),
        Decimal("0.00"),
    )
    return {
        "transaction_count": len(frame),
        "deposits": deposit_total,
        "withdrawals": withdrawal_total,
        "average_amount": statistics(frame)["mean"],
    }
