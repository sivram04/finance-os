"""Shared training for the customer classifiers (churn, expansion) on the weekly panel: two candidates (gradient
boosting and regularised logistic regression), time-based holdout with a label-horizon gap, comparison with the
current rule at the same number of customers flagged, permutation importance, then a refit on all labelled weeks
and scores for today."""
import numpy as np
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from finance_os.ml.customer_panel import FEATURES, LABELS, holdout_split


def _at_k(y, score, k):
    top = np.argsort(-score, kind="stable")[:k]
    hit = int(y[top].sum())
    return {"flagged": int(k), "caught": hit, "precision": round(hit / k, 3) if k else None,
            "recall": round(float(hit / y.sum()), 3) if y.sum() else None}


def train(panel, label, rule, today):
    train_df, test_df, cut = holdout_split(panel)
    Xtr, ytr = train_df[FEATURES].to_numpy(float), train_df[label].astype(int).to_numpy()
    Xte, yte = test_df[FEATURES].to_numpy(float), test_df[label].astype(int).to_numpy()
    cands = {
        "gradient_boosting": HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=300, l2_regularization=1.0,
                                                            min_samples_leaf=40, random_state=7),
        "logistic_regression": make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=5000)),
    }
    ev, sc = {}, {}
    for name, m in cands.items():
        m.fit(Xtr, ytr)
        p = m.predict_proba(Xte)[:, 1]
        sc[name] = p
        ev[name] = {"roc_auc": round(roc_auc_score(yte, p), 3), "average_precision": round(average_precision_score(yte, p), 3),
                    "brier": round(brier_score_loss(yte, p), 4)}
    r = np.array([rule(x) for x in test_df[FEATURES].to_dict("records")], float)
    ev["current_rule"] = {"roc_auc": round(roc_auc_score(yte, r), 3), "average_precision": round(average_precision_score(yte, r), 3)}
    best = max(cands, key=lambda n: ev[n]["average_precision"])
    k = int((r > 0).sum())
    jitter = np.random.default_rng(0).random(len(r)) * 1e-6
    comparison = {"flagged_by_rule": k, "rule": _at_k(yte, r + jitter, k), "model": _at_k(yte, sc[best], k)}
    imp = permutation_importance(cands[best], Xte, yte, scoring="average_precision", n_repeats=5, random_state=7)
    importance = sorted(({"feature": LABELS.get(f, f.replace("seg_", "segment: ")), "importance": round(float(v), 4)}
                         for f, v in zip(FEATURES, imp.importances_mean)), key=lambda x: -x["importance"])
    lab = panel[panel["labelled"]]
    final = clone(cands[best]).fit(lab[FEATURES].to_numpy(float), lab[label].astype(int).to_numpy())
    cur = panel[panel["asof"] == today].copy()
    cur["p"] = final.predict_proba(cur[FEATURES].to_numpy(float))[:, 1]
    card = {
        "model": best.replace("_", " "), "features": len(FEATURES),
        "training_rows": int(len(train_df)), "training_positives": int(ytr.sum()),
        "training_customers": int(train_df["customer_id"].nunique()),
        "holdout_rows": int(len(test_df)), "holdout_positives": int(yte.sum()),
        "holdout_from": str(cut.date()), "evaluation": ev, "same_budget_comparison": comparison,
        "feature_importance": importance[:10],
    }
    return card, cur, best
