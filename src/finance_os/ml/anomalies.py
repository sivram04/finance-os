"""Anomaly scoring for costs, against each series' own history instead of one fixed threshold:

- monthly ledger   every expense and COGS account x department: robust z-score of the month against the median
                   and MAD of its prior 12 closed months (min 6), plus an isolation forest across all series on
                   (robust z, ratio to the median, size); flagged when |z| >= 3.5, or the forest puts it in its top
                   2% with |z| >= 2
- daily cloud      every cloud service x team (untagged spend is its own team): robust z against the prior 28 days

Each flag gives the expected range (median +/- 3 robust standard deviations) and how far outside it the value is.
The backtest checks the planted anomalies in the history (seeds of the simulator, A-M5-01 unbudgeted legal fees
and A-M3-01 the untagged GPU cluster) and compares the number of flags with a fixed rule (month-on-month change
over 25% and $5K; daily cost over 2x its 28-day median).
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from finance_os.ml.features import frame, latest_closed

Z_FLAG, Z_FOREST, FOREST_SHARE = 3.5, 2.0, 0.02
MAD_K = 1.4826  # MAD to standard deviation for normal data


def _robust(hist, x, floor, tol=0.05):
    med = float(np.median(hist))
    mad = float(np.median(np.abs(hist - med))) * MAD_K
    scale = max(mad, abs(med) * tol, floor)  # a flat series still gets some tolerance
    return med, scale, (x - med) / scale


def monthly(wh):
    closed = latest_closed(wh)
    g = frame(wh, """select month, account_id, account_name, account_type, coalesce(department_id, '-') as department_id,
                            natural_amount as amount from marts.fct_gl_monthly
                     where account_type in ('opex', 'cogs') and month <= ?::date""", [str(closed.date())])
    g["month"] = pd.to_datetime(g["month"])
    g["amount"] = g["amount"].astype(float)
    rows = []
    for (acct, dept), s in g.groupby(["account_id", "department_id"]):
        s = s.sort_values("month").reset_index(drop=True)
        for i in range(6, len(s)):
            hist = s["amount"].iloc[max(0, i - 12):i].to_numpy()
            x = float(s["amount"].iloc[i])
            med, scale, z = _robust(hist, x, 250.0)
            prev = float(s["amount"].iloc[i - 1])
            # a new level that simply carried on from last month (a hire, a new asset) is flagged once, not every month
            persisted = abs(x - prev) <= max(3 * scale, 0.05 * abs(prev))
            rows.append({"month": str(s["month"].iloc[i].date())[:7], "account_id": acct, "persisted": bool(persisted), "account_name": s["account_name"].iloc[i],
                         "department_id": dept, "amount": round(x, 2), "expected": round(med, 2),
                         "expected_low": round(med - 3 * scale, 2), "expected_high": round(med + 3 * scale, 2),
                         "robust_z": round(float(z), 2), "ratio_to_median": round(x / med, 3) if med else None,
                         "fixed_rule": bool(prev and abs(x - prev) / abs(prev) > 0.25 and abs(x - prev) > 5000)})
    df = pd.DataFrame(rows)
    feats = np.column_stack([df["robust_z"].clip(-20, 20), np.log(df["ratio_to_median"].fillna(1).clip(0.05, 20)),
                             np.log1p(df["amount"].abs())])
    forest = IsolationForest(n_estimators=300, contamination=FOREST_SHARE, random_state=7).fit(feats)
    df["forest_score"] = -forest.score_samples(feats)
    df["forest_flag"] = forest.predict(feats) == -1
    df["flag"] = ((df["robust_z"].abs() >= Z_FLAG) | (df["forest_flag"] & (df["robust_z"].abs() >= Z_FOREST))) & ~df["persisted"]
    return df


def daily(wh):
    c = frame(wh, """select usage_date as d, service, case when is_tagged then coalesce(label_team, 'unlabelled') else 'untagged' end as team,
                            sum(cost) as cost from staging.stg_infra__cloud_costs_daily group by 1, 2, 3""")
    c["d"] = pd.to_datetime(c["d"])
    c["cost"] = c["cost"].astype(float)
    rows = []
    for (svc, team), s in c.groupby(["service", "team"]):
        s = s.set_index("d")["cost"].asfreq("D", fill_value=0.0)
        v = s.to_numpy()
        for i in range(28, len(v)):
            hist = v[i - 28:i]
            med, scale, z = _robust(hist, v[i], 20.0, tol=0.1)
            rows.append({"date": str(s.index[i].date()), "service": svc, "team": team, "cost": round(float(v[i]), 2),
                         "expected": round(med, 2), "expected_high": round(med + 3 * scale, 2), "robust_z": round(float(z), 2),
                         "fixed_rule": bool(v[i] > 2 * med and v[i] - med > 100),
                         "flag": bool(z >= Z_FLAG and v[i] - med > 100)})
    return pd.DataFrame(rows)


def run(wh):
    m, d = monthly(wh), daily(wh)
    # planted anomalies in the simulated history, to check recall
    legal = m[(m["account_id"] == "6400") & (m["department_id"] == "GA") & m["month"].isin(["2026-03", "2026-04", "2026-05"])]
    gpu_days = pd.date_range("2026-05-11", periods=9).strftime("%Y-%m-%d")
    cluster = d[(d["team"] == "untagged") & d["date"].isin(gpu_days)]
    checks = [
        {"anomaly": "A-M5-01 unbudgeted outside counsel, G&A 6400, 2026-03 to 05", "periods": int(len(legal)),
         "model_caught": int(legal["flag"].sum()), "fixed_rule_caught": int(legal["fixed_rule"].sum())},
        {"anomaly": "A-M3-01 untagged GPU cluster, 9 days from 2026-05-11", "periods": int(cluster["date"].nunique()),
         "model_caught": int(cluster.groupby("date")["flag"].any().sum()), "fixed_rule_caught": int(cluster.groupby("date")["fixed_rule"].any().sum())},
    ]
    evaluation = {
        "monthly_points_scored": int(len(m)), "monthly_flags": int(m["flag"].sum()), "monthly_fixed_rule_flags": int(m["fixed_rule"].sum()),
        "daily_points_scored": int(len(d)), "daily_flags": int(d["flag"].sum()), "daily_fixed_rule_flags": int(d["fixed_rule"].sum()),
        "planted_anomalies": checks,
    }
    recent = sorted(m["month"].unique())[-6:]
    flagged_m = m[m["flag"] & m["month"].isin(recent)].sort_values(["month", "robust_z"], ascending=[False, False])
    last_day = d["date"].max()
    recent_days = sorted(d["date"].unique())[-30:]
    flagged_d = d[d["flag"] & d["date"].isin(recent_days)].sort_values(["date", "robust_z"], ascending=[False, False])
    caught = sum(c["model_caught"] for c in checks)
    total = sum(c["periods"] for c in checks)
    rule_caught = sum(c["fixed_rule_caught"] for c in checks)
    card = {
        "model": "robust z-score per series + isolation forest (monthly); robust z-score (daily cloud)",
        "target": "cost lines out of line with their own history",
        "evaluation": evaluation,
        "headline": (f"planted anomalies caught {caught}/{total} periods (fixed rule {rule_caught}/{total}); flags: "
                     f"{evaluation['monthly_flags']} monthly vs {evaluation['monthly_fixed_rule_flags']} for the fixed rule, "
                     f"{evaluation['daily_flags']} daily vs {evaluation['daily_fixed_rule_flags']}"),
        "caveat": "Unsupervised: a flag means unusual for that line, not wrong. Only two planted cost anomalies exist to "
                  "measure recall; precision is judged by review.",
    }
    keep_m = ["month", "account_id", "account_name", "department_id", "amount", "expected", "expected_low", "expected_high", "robust_z", "forest_flag", "fixed_rule"]
    keep_d = ["date", "service", "team", "cost", "expected", "expected_high", "robust_z", "fixed_rule"]
    return {"as_of": last_day, "card": card,
            "rows": flagged_m[keep_m].to_dict("records"), "daily": flagged_d[keep_d].head(50).to_dict("records")}
