import os
from io import BytesIO
from typing import Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd
from flask import Flask, render_template, request

try:
    import shap  # type: ignore
except Exception:  # optional
    shap = None

app = Flask(__name__)

# ---- Config ----

# Expected pickle filenames (rename your files to these or edit here)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
XGB_PATH = os.environ.get("DW_XGB_PATH", os.path.join(BASE_DIR, "..", "xgb_model.pkl"))
LR_PATH = os.environ.get("DW_LR_PATH", os.path.join(BASE_DIR, "..", "lr_model.pkl"))
ENSEMBLE_PATH = os.environ.get("DW_ENSEMBLE_PATH", os.path.join(BASE_DIR, "..", "deliriumwatch_ensemble.pkl"))
FEATURE_NAMES_PATH = os.environ.get("DW_FEATS_PATH", os.path.join(BASE_DIR, "..", "feature_names.pkl"))

ICU_OPTIONS = [
    "Medical Intensive Care Unit (MICU)",
    "Surgical Intensive Care Unit (SICU)",
    "Cardiac Vascular Intensive Care Unit (CVICU)",
    "Coronary Care Unit (CCU)",
    "Trauma SICU (TSICU)",
    "Neuro SICU",
    "Neuro Intermediate",
    "Neuro Stepdown",
    "PACU",
    "Other",
]

# Hard-coded best AUROCs from temporal notebook
METRICS = {
    "xgb": 0.8511,           # XGBoost Temporal AUROC
    "lr": 0.76,              # approx baseline
    "ensemble": 0.8526,      # Voting Ensemble Temporal AUROC
}


def safe_load(path: str):
    if not path or not os.path.exists(path):
        return None
    try:
        return joblib.load(path)
    except Exception:
        return None


def load_feature_names() -> List[str]:
    feats = safe_load(FEATURE_NAMES_PATH)
    if isinstance(feats, (list, tuple)):
        return list(feats)
    return []


XGB_MODEL = safe_load(XGB_PATH)
LR_MODEL = safe_load(LR_PATH)
ENSEMBLE_MODEL = safe_load(ENSEMBLE_PATH)
FEATURE_NAMES = load_feature_names()


def make_default_values() -> Dict[str, float]:
    return {
        "age": 65.0,
        "gender": 0.0,
        "avg_sofa": 6.0,
        "admission_sofa": 5.0,
        "hr_mean": 92.0,
        "hr_std": 12.0,
        "rr_mean": 21.0,
        "rr_std": 4.0,
        "spo2_mean": 96.0,
        "spo2_min": 90.0,
        "nibp_mean": 78.0,
        "abp_measured": 1.0,
        "propofol_total": 400.0,
        "midazolam_total": 10.0,
        "lorazepam_total": 4.0,
        "fentanyl_total": 800.0,
        "unique_sedation_drugs": 2.0,
        "nid_score": 0.35,
    }


def build_row_from_form(form) -> Tuple[pd.DataFrame, Dict[str, float], str]:
    values = make_default_values()
    for key in values.keys():
        try:
            raw = form.get(key, None)
            if raw is not None and raw != "":
                values[key] = float(raw)
        except Exception:
            continue

    gender_str = form.get("gender_select", "Male")
    values["gender"] = 0.0 if gender_str == "Male" else 1.0

    icu_sel = form.get("icu_select", ICU_OPTIONS[0])

    # Build dataframe in FEATURE_NAMES order
    if not FEATURE_NAMES:
        # Fallback: simple order from values + ICU
        cols = list(values.keys())
        row = pd.DataFrame([[values[c] for c in cols]], columns=cols)
    else:
        data = {}
        for col in FEATURE_NAMES:
            if col in values:
                data[col] = values[col]
            elif col.startswith("icu_"):
                # one-hot ICU
                icu_name = col.replace("icu_", "")
                data[col] = 1.0 if icu_name == icu_sel else 0.0
            else:
                data[col] = 0.0
        row = pd.DataFrame([data])

    return row, values, icu_sel


def predict_proba_model(model_name: str, X: pd.DataFrame) -> float:
    model = {
        "xgb": XGB_MODEL,
        "lr": LR_MODEL,
        "ensemble": ENSEMBLE_MODEL,
    }.get(model_name)
    if model is None or not hasattr(model, "predict_proba"):
        return float("nan")
    prob = model.predict_proba(X)[:, 1][0]
    return float(prob)


def risk_label(prob: float, threshold: float = 0.7) -> str:
    if not np.isfinite(prob):
        return "UNKNOWN"
    if prob >= threshold:
        return "HIGH" if prob >= 0.8 else "MEDIUM"
    return "LOW"


def compute_shap_dict(X: pd.DataFrame) -> Dict[str, float]:
    if shap is None or XGB_MODEL is None:
        return {}
    try:
        explainer = shap.TreeExplainer(XGB_MODEL)
        vals = explainer.shap_values(X)
        if isinstance(vals, list):
            vals = vals[1][0]
        else:
            vals = vals[0]
            if getattr(vals, "ndim", 1) > 1 and vals.shape[1] == 2:
                vals = vals[:, 1]
        return {feat: float(v) for feat, v in zip(X.columns, vals)}
    except Exception:
        return {}


@app.route("/", methods=["GET", "POST"])
def index():
    selected_model = "ensemble"
    prob = None
    label = None
    shap_items: List[Tuple[str, float]] = []
    values = make_default_values()
    icu_sel = ICU_OPTIONS[0]

    shap_max = 0.01

    if request.method == "POST":
        selected_model = request.form.get("model_select", "ensemble")
        X_row, values, icu_sel = build_row_from_form(request.form)
        prob = predict_proba_model(selected_model, X_row)
        label = risk_label(prob)

        shap_dict = compute_shap_dict(X_row)
        shap_items = sorted(shap_dict.items(), key=lambda kv: abs(kv[1]), reverse=True)[:8]
        shap_max = max((abs(v) for k, v in shap_items), default=0.01)

    return render_template(
        "index.html",
        values=values,
        icu_options=ICU_OPTIONS,
        icu_sel=icu_sel,
        selected_model=selected_model,
        aurocs=METRICS,
        prob=prob,
        label=label,
        shap_items=shap_items,
        shap_max=shap_max,
        shap_available=bool(shap_items),
        shap_json=__import__("json").dumps([{"name": k, "value": v} for k, v in shap_items]) if shap_items else "[]",
        models_loaded={
            "xgb": XGB_MODEL is not None,
            "lr": LR_MODEL is not None,
            "ensemble": ENSEMBLE_MODEL is not None,
        },
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5040, debug=True)
