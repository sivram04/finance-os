"""Churn probability: will an active customer churn (revenue to zero) within the next 3 months?

Trained on weekly customer snapshots (customer_panel) with features from daily usage, the API request log
(~200M requests summarised per customer-day), revenue and invoices. Compared on held-out weeks with the health
rules it would replace (fct_customer_health: at risk = usage down 40%+ or idle 14+ days; watch = down 20%+ or
30+ days overdue), at the same number of customers flagged.
"""
from finance_os.ml import classify, customer_panel


def rule(f):
    """The current health rules as a level: 2 at risk, 1 watch, 0 healthy."""
    if f["usage_trend"] <= -0.40 or f["days_since_usage"] >= 14:
        return 2
    if f["usage_trend"] <= -0.20 or f["overdue_30_count"] > 0:
        return 1
    return 0


def _signals(r):
    s = []
    if r["usage_trend"] <= -0.15:
        s.append(f"usage down {-r['usage_trend']:.0%} (30d vs prior 60d)")
    if r["days_since_usage"] >= 7:
        s.append(f"no usage for {int(r['days_since_usage'])} days")
    if r["req_trend_7d"] <= -0.3:
        s.append(f"API requests last 7 days {-r['req_trend_7d']:.0%} below the 30-day pace")
    if r["error_rate_change"] >= 0.01:
        s.append(f"API error rate up {r['error_rate_change'] * 100:.1f} pts")
    if r["active_keys_change"] <= -0.5:
        s.append(f"{-r['active_keys_change']:.1f} fewer active API keys")
    if r["revenue_trend_3m"] <= -0.15:
        s.append(f"revenue down {-r['revenue_trend_3m']:.0%} over 3 months")
    if r["contractions_3m"] >= 2:
        s.append(f"{int(r['contractions_3m'])} of the last 3 months contracted")
    if r["avg_days_late_6"] >= 7:
        s.append(f"pays {r['avg_days_late_6']:.0f} days late on average")
    if r["overdue_30_count"]:
        s.append(f"{int(r['overdue_30_count'])} invoice(s) 30+ days overdue")
    return s


def run(wh):
    panel, today, piv, months, seg = customer_panel.build(wh)
    card, cur, best = classify.train(panel, "churned", rule, today)
    rows = []
    for r in cur.sort_values("p", ascending=False).to_dict("records"):
        arr = float(r["revenue_last_closed"]) * 12
        rows.append({"customer_id": r["customer_id"], "segment": seg.get(r["customer_id"]), "churn_probability_3m": round(r["p"], 4),
                     "arr": round(arr, 2), "arr_at_risk": round(arr * r["p"], 2),
                     "rule_level": ["healthy", "watch", "at_risk"][rule(r)], "signals": _signals(r)})
    ev, cmp = card["evaluation"], card["same_budget_comparison"]
    card.update({
        "target": "churn (revenue to zero) within 3 months",
        "headline": (f"{card['model']} on {card['training_rows']:,} weekly snapshots ({card['features']} features incl. the API log): "
                     f"holdout ROC AUC {ev[best]['roc_auc']} vs rules {ev['current_rule']['roc_auc']}; flagging "
                     f"{cmp['flagged_by_rule']}, it catches {cmp['model']['caught']} of {card['holdout_positives']} vs "
                     f"{cmp['rule']['caught']} for the rules"),
        "caveat": "Weekly snapshots multiply rows, not churn events: about a hundred customers have churned in the history. "
                  "Treat probabilities as a ranking signal and read the reasons alongside.",
    })
    return {"as_of": str(today.date()), "card": card, "rows": rows,
            "expected_arr_lost_3m": round(sum(r["arr_at_risk"] for r in rows), 2)}
