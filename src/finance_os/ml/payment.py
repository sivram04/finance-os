"""Payment timing: how many days before or after its due date each invoice will be paid, as P10 / P50 / P90 (quantile
gradient boosting), from the invoice (segment, type, terms, size, month) and the customer's payment record before
that invoice.

Backtest: train on invoices dated before the holdout start, test on later invoices that have been paid, and
compare with the 13-week cash forecast's rule (due date + the customer's average days late so far). Invoices still
unpaid are not in the test set, so slow payers are under-represented there.
"""
from datetime import timedelta

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from finance_os.ml.features import frame, today

HOLDOUT_FROM = pd.Timestamp("2026-04-01")
SEGMENTS = ("enterprise", "mid_market", "self_serve", "federal")
FEATURES = ["terms_days", "log_amount", "is_project", "invoice_month", "prior_count", "prior_mean_late",
            "prior_max_late", "prior_mean_late_3", *[f"seg_{s}" for s in SEGMENTS]]
QUANTILES = (0.1, 0.5, 0.9)


def _table(wh):
    inv = frame(wh, """select invoice_ref, customer_id, segment, invoice_type, invoice_date, due_date, paid_date, amount,
                              balance, is_disputed from marts.fct_ar_invoices where amount > 0""")
    for c in ("invoice_date", "due_date", "paid_date"):
        inv[c] = pd.to_datetime(inv[c])
    inv["amount"] = inv["amount"].astype(float)
    inv["balance"] = inv["balance"].astype(float)
    inv["terms_days"] = (inv["due_date"] - inv["invoice_date"]).dt.days
    inv["days_to_pay"] = (inv["paid_date"] - inv["invoice_date"]).dt.days
    inv["late"] = (inv["paid_date"] - inv["due_date"]).dt.days  # signed: early payment is negative
    return inv.sort_values("invoice_date").reset_index(drop=True)


def _features(inv, row, asof):
    """Features for one invoice from the customer's invoices paid before `asof` (the invoice date when training)."""
    prior = inv[(inv["customer_id"] == row["customer_id"]) & inv["paid_date"].notna() & (inv["paid_date"] < asof)]
    late = prior["late"].clip(lower=0)
    f = {"terms_days": row["terms_days"], "log_amount": float(np.log1p(row["amount"])), "is_project": int(row["invoice_type"] == "project"),
         "invoice_month": int(row["invoice_date"].month), "prior_count": int(len(prior)),
         "prior_mean_late": float(late.mean()) if len(late) else np.nan, "prior_max_late": float(late.max()) if len(late) else np.nan,
         "prior_mean_late_3": float(late.tail(3).mean()) if len(late) else np.nan}
    for s in SEGMENTS:
        f[f"seg_{s}"] = int(row["segment"] == s)
    return f


def _rule_days(f):
    """The cash forecast's rule: due date + the customer's average days late (0 with no history)."""
    return f["terms_days"] + (0.0 if np.isnan(f["prior_mean_late"]) else f["prior_mean_late"])


def run(wh):
    inv = _table(wh)
    paid = inv[inv["paid_date"].notna()].copy()
    X = pd.DataFrame([_features(inv, r, r["invoice_date"]) for r in paid.to_dict("records")], index=paid.index)
    tr, te = paid["invoice_date"] < HOLDOUT_FROM, paid["invoice_date"] >= HOLDOUT_FROM
    models = {}
    for q in QUANTILES:
        m = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_depth=3, learning_rate=0.05, max_iter=300,
                                          min_samples_leaf=15, random_state=7)
        m.fit(X[tr][FEATURES].to_numpy(float), paid[tr]["late"].to_numpy(float))
        models[q] = m
    Xte, terms = X[te][FEATURES].to_numpy(float), X[te]["terms_days"].to_numpy(float)
    yte = paid[te]["days_to_pay"].to_numpy(float)
    p10, p50, p90 = (terms + models[q].predict(Xte) for q in QUANTILES)
    rule = np.array([_rule_days(f) for f in X[te].to_dict("records")])
    terms_only = terms
    big = paid[te]["amount"].to_numpy() >= 10_000

    def mae(pred, mask=None):
        mask = np.ones(len(yte), bool) if mask is None else mask
        return round(float(np.abs(pred[mask] - yte[mask]).mean()), 2) if mask.any() else None

    evaluation = {
        "holdout_invoices": int(te.sum()), "training_invoices": int(tr.sum()),
        "mae_days": {"model_p50": mae(p50), "rule_due_plus_avg_late": mae(rule), "due_date_only": mae(terms_only)},
        "mae_days_invoices_10k_plus": {"model_p50": mae(p50, big), "rule_due_plus_avg_late": mae(rule, big), "count": int(big.sum())},
        "range_coverage_p10_p90": round(float(((yte >= p10) & (yte <= p90)).mean()), 3),
        "dollar_weighted_mae_days": {
            "model_p50": round(float(np.average(np.abs(p50 - yte), weights=paid[te]["amount"])), 2),
            "rule_due_plus_avg_late": round(float(np.average(np.abs(rule - yte), weights=paid[te]["amount"])), 2)},
    }

    # refit on every paid invoice, then predict the open ones as of today
    for q in QUANTILES:
        models[q].fit(X[FEATURES].to_numpy(float), paid["late"].to_numpy(float))
    now = today(wh)
    open_ = inv[inv["balance"] > 0]
    rows = []
    for r in open_.to_dict("records"):
        f = _features(inv, r, now + timedelta(days=1))
        x = np.array([[f[k] for k in FEATURES]], float)
        d10, d50, d90 = sorted(f["terms_days"] + float(models[q].predict(x)[0]) for q in QUANTILES)
        exp = r["invoice_date"] + timedelta(days=round(d50))
        overdue_vs_model = exp < now
        rows.append({"invoice_ref": r["invoice_ref"], "customer_id": r["customer_id"], "segment": r["segment"],
                     "balance": round(r["balance"], 2), "invoice_date": str(r["invoice_date"].date()), "due_date": str(r["due_date"].date()),
                     "is_disputed": bool(r["is_disputed"]),
                     "expected_pay_date": str(max(exp, now + timedelta(days=1)).date()),
                     "earliest_p10": str((r["invoice_date"] + timedelta(days=round(d10))).date()),
                     "latest_p90": str(max(r["invoice_date"] + timedelta(days=round(d90)), now + timedelta(days=1)).date()),
                     "rule_pay_date": str((r["invoice_date"] + timedelta(days=round(_rule_days(f)))).date()),
                     "note": "already past the model's expected date; treat as at risk" if overdue_vs_model else
                             ("disputed: payment waits on the dispute" if r["is_disputed"] else "")})
    rows.sort(key=lambda x: x["expected_pay_date"])
    weeks = {}
    for r in rows:
        if r["is_disputed"]:
            continue
        wk = str((pd.Timestamp(r["expected_pay_date"]) - timedelta(days=pd.Timestamp(r["expected_pay_date"]).weekday())).date())
        weeks[wk] = round(weeks.get(wk, 0) + r["balance"], 2)
    ev = evaluation["mae_days"]
    card = {
        "model": "quantile gradient boosting (P10 / P50 / P90)", "target": "days paid before (-) or after (+) the due date",
        "evaluation": evaluation,
        "headline": (f"holdout error {ev['model_p50']} days (model) vs {ev['rule_due_plus_avg_late']} days (due date + average "
                     f"lateness) on {evaluation['holdout_invoices']} invoices; P10-P90 range held the actual "
                     f"{evaluation['range_coverage_p10_p90']:.0%} of the time (target 80%)"),
        "caveat": "Most invoices are self-serve card payments; there are few enterprise invoices, and unpaid invoices are "
                  "not in the test set.",
    }
    return {"as_of": str(now.date()), "card": card, "rows": rows,
            "expected_collections_by_week": [{"week_of": k, "amount": v} for k, v in sorted(weeks.items())]}
