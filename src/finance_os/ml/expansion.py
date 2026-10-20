"""Expansion propensity: will a customer's revenue over the next 3 months average 20%+ above its last closed month?

Same weekly panel and features as churn. The rule it is compared with is the one an account team uses today:
usage up 20%+ (30 days vs the prior 60).
"""
from finance_os.ml import classify, customer_panel


def rule(f):
    return 1 if f["usage_trend"] >= 0.20 else 0


def _signals(r):
    s = []
    if r["usage_trend"] >= 0.1:
        s.append(f"usage up {r['usage_trend']:.0%} (30d vs prior 60d)")
    if r["req_trend_7d"] >= 0.15:
        s.append(f"API requests last 7 days {r['req_trend_7d']:.0%} above the 30-day pace")
    if r["active_keys_change"] >= 0.5:
        s.append(f"{r['active_keys_change']:.1f} more active API keys")
    if r["rate_limited_rate_30d"] >= 0.003:
        s.append(f"hitting rate limits on {r['rate_limited_rate_30d'] * 100:.1f}% of requests")
    if r["expansions_3m"] >= 2:
        s.append(f"{int(r['expansions_3m'])} of the last 3 months expanded")
    return s


def run(wh):
    panel, today, piv, months, seg = customer_panel.build(wh)
    card, cur, best = classify.train(panel, "expanded", rule, today)
    rows = []
    for r in cur.sort_values("p", ascending=False).to_dict("records"):
        arr = float(r["revenue_last_closed"]) * 12
        rows.append({"customer_id": r["customer_id"], "segment": seg.get(r["customer_id"]),
                     "expansion_probability_3m": round(r["p"], 4), "arr": round(arr, 2),
                     "usage_trend": round(float(r["usage_trend"]), 3), "rule_says_expanding": bool(rule(r)), "signals": _signals(r)})
    ev, cmp = card["evaluation"], card["same_budget_comparison"]
    card.update({
        "target": "revenue over the next 3 months averaging 20%+ above the last closed month",
        "headline": (f"{card['model']}: holdout ROC AUC {ev[best]['roc_auc']} vs usage-trend rule {ev['current_rule']['roc_auc']}; "
                     f"flagging {cmp['flagged_by_rule']}, it finds {cmp['model']['caught']} of {card['holdout_positives']} "
                     f"expansions vs {cmp['rule']['caught']} for the rule"),
        "caveat": "Usage-priced revenue moves with usage, so expansion is partly visible already; the model ranks who is next.",
    })
    return {"as_of": str(today.date()), "card": card, "rows": rows}
