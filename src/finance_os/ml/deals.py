"""Deal win probability for open opportunities: regularised logistic regression on every closed deal (won or lost)
using only what is known when a deal is created (segment, size, rep, quarter created). Left out on purpose
because they leak the outcome: deal age (for a closed deal it is the whole cycle) and the customer id (the CRM
only links a customer once a deal is won).

Only a few dozen deals have closed, so the model is checked with leave-one-out cross-validation against the
segment's historical win rate, and the CRM stage probability is shown next to it for open deals.
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import LeaveOneOut, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from finance_os.ml.features import frame, today


def _features(df, reps, won_cycle):
    f = pd.DataFrame(index=df.index)
    f["log_amount"] = np.log1p(df["amount_arr"].astype(float))
    f["enterprise"] = (df["segment"] == "enterprise").astype(int)
    f["q4_created"] = (pd.to_datetime(df["created_date"]).dt.quarter == 4).astype(int)
    for r in reps:
        f[f"rep_{r}"] = (df["rep_id"] == r).astype(int)
    return f


def run(wh):
    now = today(wh)
    o = frame(wh, """select opportunity_id, customer_id, account_name, segment, rep_id, created_date, close_date, stage,
                            is_closed, is_won, probability, amount_arr from staging.stg_crm__opportunities""")
    o["created_date"], o["close_date"] = pd.to_datetime(o["created_date"]), pd.to_datetime(o["close_date"])
    closed = o[o["is_closed"]].copy()
    won = closed[closed["is_won"]]
    won_cycle = ((won["close_date"] - won["created_date"]).dt.days).groupby(won["segment"]).median().to_dict()
    closed["age_days"] = (closed["close_date"] - closed["created_date"]).dt.days  # at close, the whole cycle
    reps = sorted(o["rep_id"].dropna().unique())
    X, y = _features(closed, reps, won_cycle), closed["is_won"].astype(int).to_numpy()
    model = make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=5000))
    p_cv = cross_val_predict(model, X.to_numpy(float), y, cv=LeaveOneOut(), method="predict_proba")[:, 1]
    # baseline: the segment's win rate (in-sample, which flatters the baseline slightly)
    seg_rate = closed["segment"].map(closed.groupby("segment")["is_won"].mean()).to_numpy(float)
    ev = {"closed_deals": int(len(closed)), "won": int(y.sum()),
          "model": {"roc_auc": round(roc_auc_score(y, p_cv), 3), "brier": round(brier_score_loss(y, p_cv), 4)},
          "segment_win_rate": {"roc_auc": round(roc_auc_score(y, seg_rate), 3), "brier": round(brier_score_loss(y, seg_rate), 4)}}
    model.fit(X.to_numpy(float), y)
    coefs = sorted(zip(X.columns, model[-1].coef_[0]), key=lambda x: -abs(x[1]))
    op = o[~o["is_closed"]].copy()
    op["age_days"] = (now - op["created_date"]).dt.days
    op["p"] = model.predict_proba(_features(op, reps, won_cycle).to_numpy(float))[:, 1]
    rows = [{"opportunity_id": r["opportunity_id"], "account_name": r["account_name"], "segment": r["segment"], "rep_id": r["rep_id"],
             "stage": r["stage"], "amount_arr": float(r["amount_arr"]), "crm_probability": float(r["probability"]),
             "ml_win_probability": round(float(r["p"]), 4), "close_date": str(r["close_date"].date()),
             "ml_weighted_arr": round(float(r["amount_arr"]) * float(r["p"]), 2),
             "crm_weighted_arr": round(float(r["amount_arr"]) * float(r["probability"]), 2)}
            for r in op.sort_values("p", ascending=False).to_dict("records")]
    better = ev["model"]["brier"] < ev["segment_win_rate"]["brier"]
    card = {"model": "logistic regression (L2), leave-one-out validated", "target": "deal won",
            "evaluation": ev, "drivers": [{"feature": k, "weight": round(float(v), 3)} for k, v in coefs[:6]],
            "headline": (f"{ev['closed_deals']} closed deals: LOO ROC AUC {ev['model']['roc_auc']} vs segment win rate "
                         f"{ev['segment_win_rate']['roc_auc']}; Brier {ev['model']['brier']} vs {ev['segment_win_rate']['brier']}"),
            "verdict": "the model beats the segment win rate" if better else "no better than the segment win rate: too few closed deals",
            "caveat": "Only a few dozen closed deals and no stage history: use it to rank deals, alongside the CRM stage."}
    return {"as_of": str(now.date()), "card": card, "rows": rows,
            "pipeline": {"open_deals": len(rows), "amount": round(sum(r["amount_arr"] for r in rows), 2),
                         "ml_weighted": round(sum(r["ml_win_probability"] * r["amount_arr"] for r in rows), 2),
                         "crm_weighted": round(sum(r["crm_weighted_arr"] for r in rows), 2)}}
