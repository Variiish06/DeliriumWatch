# DeliriumWatch 🏥
### Temporal Early Warning System for ICU Delirium Onset

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![MIMIC-IV](https://img.shields.io/badge/Data-MIMIC--IV%20v3.1-green.svg)](https://physionet.org/content/mimiciv/3.1/)
[![AUROC](https://img.shields.io/badge/AUROC-0.8405-brightgreen.svg)]()
[![License](https://img.shields.io/badge/License-PhysioNet%20DUA-red.svg)]()

> **Predicting ICU delirium onset before it happens — using a novel sleep disruption proxy engineered from nursing timestamp patterns in MIMIC-IV.**

---

## Table of Contents

- [Problem Statement](#problem-statement)
- [Novel Contribution](#novel-contribution)
- [Dataset](#dataset)
- [Results](#results)
- [Project Structure](#project-structure)
- [Data Pipeline](#data-pipeline)
- [Feature Engineering](#feature-engineering)
- [Methodology](#methodology)
- [Reproducing Results](#reproducing-results)
- [Ethical Considerations](#ethical-considerations)
- [Roadmap](#roadmap)
- [Team](#team)

---

## Problem Statement

ICU delirium affects **60–80% of mechanically ventilated patients**, triples 30-day mortality, increases ICU stay by 5+ days, and causes long-term cognitive impairment in 40% of survivors.

The current standard of care is reactive — bedside nurses assess patients using the CAM-ICU tool every 8–12 hours. By the time delirium is detected, the window for preventive intervention has already closed.

**We frame this as a supervised binary classification problem:**

> Given all EHR data available in the pre-delirium observation window, predict whether a patient will develop ICU delirium — before the first positive CAM-ICU assessment.

---

## Novel Contribution

### Nighttime Intervention Density (NID)

Every existing ICU delirium prediction paper ignores sleep disruption — not because it's unimportant, but because no EHR system directly records sleep quality.

We introduce **Nighttime Intervention Density (NID)**: a proxy for sleep fragmentation derived from the timestamps of nursing chartevents in MIMIC-IV.

```
NID = (nursing events between 22:00–06:00) / (total nursing events in pre-delirium window)
```

NID produces a normalized score between 0 and 1, representing the proportion of clinical care activity occurring during sleeping hours — comparable across patients regardless of ICU stay duration.

**Validation:**
-Delirious patients: NID mean = 0.3550
-Non-delirious patients: NID mean = 0.3338
-Mann-Whitney U test: p < 0.0001
-SHAP importance rank: #1 of 27 features
-Ablation contribution: +0.0292 AUROC

---

## Dataset

**Source:** MIMIC-IV v3.1 (PhysioNet, MIT Laboratory for Computational Physiology)

Access requires PhysioNet credentialing and signing the MIMIC-IV Data Use Agreement. Data is available via Google BigQuery.

> ⚠️ **Important:** Per PhysioNet DUA, MIMIC-IV data must not be shared publicly, uploaded to GitHub, or transmitted to third-party AI services. This repository contains no patient data.

### Cohort Construction

| Step | Patients Remaining |
|------|-------------------|
| All ICU stays with CAM-ICU assessments | 69,879 |
| After excluding UTA-only assessments | 69,879 |
| After excluding stays < 24 hours | 57,992 |
| After excluding pre-delirium window < 12 hours | **48,786** |
| After symmetric window matching | 25,843 |

**Final cohort:**
- Total ICU stays: 25,843
- Delirium positive: 11,815 (45.7%)
- Delirium negative: 14,028 (54.3%)
- Class ratio: 1:1.19
- Mean observation window: 59 hours
- ICU types: 10 (MICU, SICU, CVICU, CCU, TSICU, 
  Neuro SICU, Neuro Intermediate, Neuro Stepdown, 
  PACU, Other)

### Label Extraction

Delirium labels extracted from `mimiciv_icu.chartevents` using itemid `228332` (Delirium Assessment):
- `Positive` → delirium label = 1, timestamp = first positive assessment
- `Negative` → delirium label = 0
- `UTA` (Unable to Assess) → excluded

---

## Results

### Model Performance

| Model | AUROC | Delirium Recall | Accuracy |
|-------|-------|-----------------|----------|
| Published benchmark (best existing) | 0.79 | — | — |
| Logistic Regression | 0.7655 | 0.68 | 0.70 |
| **XGBoost ** | **0.8405** | **0.73** | **0.76** |

Both models surpass the published benchmark. Even the Logistic Regression baseline outperforms the best existing delirium prediction paper on MIMIC.

### SHAP Feature Importance (Top 10)

| Rank | Feature | Category |
|------|---------|----------|
| **1** | **nid_score** | **Novel — sleep disruption proxy** |
| 2 | avg_sofa | Clinical severity |
| 3 | age | Demographics |
| 4 | propofol_total | Sedation pharmacology |
| 5 | unique_sedation_drugs | Sedation complexity |
| 6 | rr_mean | Vitals |
| 7 | spo2_mean | Vitals |
| 8 | nibp_min | Vitals |
| 9 | hr_mean | Vitals |
| 10 | nibp_mean | Vitals |

### NID Ablation Study

| Configuration | AUROC | Delta |
|---------------|-------|-------|
| XGBoost with NID | 0.8405 | — |
| XGBoost without NID | 0.8113 | -0.0292 |

---

## Project Structure

```
deliriumwatch/
│
├── sql/                          # BigQuery extraction queries
│   ├── 01_labels.sql             # CAM-ICU label extraction
│   ├── 02_cohort.sql             # ICU stay demographics
│   ├── 03_cohort_v2.sql          # 12-hour minimum window filter
│   ├── 04_sofa.sql               # SOFA severity scores
│   ├── 05_vitals_v3.sql          # Pre-delirium vitals
│   ├── 06_sedation_v3.sql        # Pre-delirium sedation (no dex)
│   ├── 07_nid_v3.sql             # Nighttime Intervention Density
│   └── 08_master_features_v3.sql # Final joined feature table
│
├── notebooks/
│   ├── deliriumwatch_eda.ipynb   # EDA pipeline
│   └── deliriumwatch_model.ipynb # Modeling + SHAP + ablation
│
├── .gitignore                    # Excludes all CSV/patient data
└── README.md
```

---

## Data Pipeline

All data extraction is performed via Google BigQuery on the PhysioNet-hosted MIMIC-IV dataset. No data is stored locally beyond the final cohort CSV (excluded from version control).

### Pipeline Overview

```
MIMIC-IV (BigQuery)
        │
        ├── chartevents (itemid 228332) ──► labels table
        │                                   (delirium onset timestamp)
        ├── icustays + patients ──────────► cohort table
        │                                   (demographics, ICU type)
        ├── sofa (derived) ───────────────► sofa table
        │                                   (avg, max, admission SOFA)
        ├── chartevents (vitals) ─────────► vitals_v3 table
        │   [pre-delirium window only]       (HR, RR, SpO2, BP)
        ├── inputevents (drugs) ──────────► sedation_v3 table
        │   [pre-delirium, no dex]           (propofol, midazolam, etc.)
        └── chartevents (timestamps) ─────► nid_v3 table
            [pre-delirium window only]       (NID score)
                    │
                    ▼
            master_features_v3
            (48,786 rows × 22 features)
                    │
                    ▼
            EDA → Model → SHAP → Ablation
```

### Critical Design Decisions

**Minimum 12-hour pre-delirium window**
Patients with less than 12 hours between ICU admission and first delirium assessment are excluded. Without this filter, NID becomes artifactually inflated — a patient admitted at 11pm with a 2am delirium assessment has NID = 1.0 by definition, not due to sleep disruption.

**Dexmedetomidine excluded**
Audit showed 67.3% of dexmedetomidine administration occurred after delirium onset. Dexmedetomidine is used to treat delirium, not just sedate patients — including it constitutes reverse causality.

**Pre-delirium temporal restriction**
All features are extracted strictly from the window between ICU admission and first delirium assessment (positive class) or ICU discharge (negative class). Post-delirium physiology is excluded.

**Symmetric window matching (Path B)**
Negative class observation windows are matched to the mean positive class duration of 59 hours. Without this, negative class used entire ICU stay (mean 179 hours) vs positive class pre-delirium window (mean 59 hours) — a 3x asymmetry that biased the model toward learning stay duration rather than clinical features.

**Dexmedetomidine exclusion**
Audit of 5,420 dexmedetomidine-receiving patients showed 67.3% received the drug AFTER delirium onset (avg +29 hours post-delirium). Dexmedetomidine is prescribed TO TREAT delirium — including it constitutes reverse causality. Excluded entirely from feature set.

**Propofol temporal audit**
74.9% of propofol administration occurred before delirium onset (avg -22.6 hours pre-delirium). Retained but restricted strictly to pre-delirium window. Post-delirium drug administration excluded via timestamp filtering.

---

## Feature Engineering

### Features Used in Final Model (21 features)

**Demographics (3)**
| Feature | Description | Encoding |
|---------|-------------|----------|
| age | Patient age at admission | Continuous |
| gender | Patient sex | Label encoded (M=0, F=1) |
| first_careunit | ICU type | One-hot encoded (10 categories) |

**Clinical Severity (2)**
| Feature | Description | Notes |
|---------|-------------|-------|
| avg_sofa | Mean SOFA score across pre-delirium stay | Captures overall trajectory |
| admission_sofa | SOFA score at ICU admission | Baseline severity |

**Vitals (9)**
| Feature | Description | Physiological bounds applied |
|---------|-------------|------------------------------|
| hr_mean | Mean heart rate | 20–300 bpm |
| hr_std | Heart rate variability | 0–50 |
| hr_max | Maximum heart rate | 20–300 bpm |
| rr_mean | Mean respiratory rate | 4–60 breaths/min |
| rr_std | Respiratory rate variability | 0–15 |
| spo2_mean | Mean oxygen saturation | 50–100% |
| spo2_min | Minimum oxygen saturation | 50–100% |
| nibp_mean | Mean non-invasive blood pressure | 20–200 mmHg |
| nibp_min | Minimum non-invasive blood pressure | 20–200 mmHg |

**Sedation Pharmacology (5)**
| Feature | Description | Notes |
|---------|-------------|-------|
| propofol_total | Cumulative pre-delirium propofol dose | 74.9% administered before delirium |
| midazolam_total | Cumulative pre-delirium midazolam dose | Benzodiazepine |
| lorazepam_total | Cumulative pre-delirium lorazepam dose | Benzodiazepine |
| fentanyl_total | Cumulative pre-delirium fentanyl dose | Opioid — impairs sleep architecture |
| unique_sedation_drugs | Count of distinct sedation agents | Polypharmacy proxy |

**Novel Feature (1)**
| Feature | Description | Validation |
|---------|-------------|------------|
| nid_score | Nighttime Intervention Density | p < 0.0001, SHAP rank #2 |

**Derived Flag (1)**
| Feature | Description | Notes |
|---------|-------------|-------|
| abp_measured | Arterial line present (binary) | 57.8% of abp_mean was imputed — flag is more reliable |

**NID Engineering Note**
NID was validated across three pipeline versions. 
In v1 (full stay window), NID ranked #4 in SHAP 
with ablation +0.0004. After fixing reverse causality 
in sedation features (v3), NID rose to #2 with 
ablation +0.0155. After symmetric window matching 
(Path B), NID rose to #1 with ablation +0.0292. 
The progressive strengthening of NID signal as 
confounding features were removed validates it as 
a genuine independent predictor rather than a 
correlated proxy.

### Features Dropped and Why

| Feature | Reason |
|---------|--------|
| subject_id, stay_id | IDs, not predictive features |
| icu_los_hours | Leakage — total stay only known post-discharge |
| night_interventions, day_interventions | Raw counts correlate with stay length — NID normalizes these |
| max_sofa | 0.91 correlation with avg_sofa |
| hr_min | 0.72 correlation with hr_mean |
| abp_mean | 0.82 correlation with abp_measured (and 57.8% imputed) |
| night_day_ratio | 0.98 correlation with nid_score |
| dexmedetomidine_total | 67.3% administered post-delirium onset — reverse causality |
| dexmedetomidine_total | Reverse causality — 
  67.3% administered post-delirium onset. 
  Drug is a delirium treatment, not predictor |
| admission_sofa | 0.92 correlation with avg_sofa |
| hr_max | 0.73 correlation with hr_mean |
| nibp_min | 0.69 correlation with nibp_mean |
---

## Methodology

### EDA Pipeline

1. Shape and dtype inspection — identify IDs, categoricals, numericals
2. Leakage audit — drop anything unavailable at prediction time
3. Missing value analysis — median imputation for vitals, binary flag for ABP
4. Physiological bounds clipping — clinical limits, not statistical IQR
5. Distribution analysis — per-class histograms for all features
6. Correlation matrix — drop features with |r| > 0.70
7. Categorical encoding — label encode binary, one-hot encode multi-class

###Window Symmetry:
Positive class observation window spans ICU admission 
to first positive CAM-ICU assessment (mean 59 hours, 
min 12, max 1321). Negative class windows are matched 
to the mean positive class duration of 59 hours, 
starting from ICU admission. This ensures both classes 
contribute equivalent observation periods, eliminating 
length-of-stay bias.

### Reverse Causality Audit

Before finalizing the pipeline, we audited all sedation features for reverse causality:

| Drug | % Administered Before Delirium | Decision |
|------|-------------------------------|----------|
| Propofol | 74.9% | Keep, restrict to pre-delirium window |
| Midazolam | ~75% | Keep, restrict to pre-delirium window |
| Lorazepam | ~75% | Keep, restrict to pre-delirium window |
| Fentanyl | ~75% | Keep, restrict to pre-delirium window |
| Dexmedetomidine | 29.7% | **Drop** — primarily a delirium treatment |

### Modeling

**Train/test split:** 80/20, stratified by delirium label, random_state=42

**Class imbalance handling:**
- Logistic Regression: `class_weight='balanced'`
- XGBoost: `scale_pos_weight = 36971/21021 = 1.19`

**Logistic Regression:**
- LASSO regularization (L2 default)
- `max_iter=1000`
- Scaled features (StandardScaler)

**XGBoost:**
- `n_estimators=300`
- `max_depth=6`
- `learning_rate=0.05`
- `subsample=0.8`
- `colsample_bytree=0.8`
- No scaling required

**Primary metric:** AUROC (area under ROC curve)
**Secondary metrics:** AUPRC, sensitivity at 90% specificity, F1-score

### Validation Strategy

Current: Random stratified 80/20 split

Planned (next milestone): Temporal holdout — train on admissions before 2019, test on 2019 onwards. This simulates real deployment where a model trained on historical data predicts future patients.

---
## Version History

| Version | Cohort | AUROC | Key Change |
|---------|--------|-------|------------|
| v1 | 57,992 | 0.8689 | Initial pipeline, full stay window |
| v2 | 57,992 | 0.9398 | Pre-delirium sedation only — artifact from short windows |
| v3 | 48,786 | 0.8947 | 12hr minimum window, dex removed — asymmetric negative class |
| v4 | 52,649 | 0.7443 | Fixed 12hr window — destroyed NID signal |
| **v5** | **25,843** | **0.8405** | **Symmetric windows, all leakage fixed — final** |

## Reproducing Results

### Prerequisites

1. PhysioNet account with MIMIC-IV v3.1 access
2. Google Cloud account linked to PhysioNet
3. Python 3.10+ with the following packages:

```bash
pip install pandas numpy matplotlib seaborn scikit-learn xgboost shap optuna scipy imbalanced-learn
```

### Steps

**Step 1 — BigQuery setup**

Link your PhysioNet account to Google Cloud at `physionet.org/settings/cloud/`. Request BigQuery access from the MIMIC-IV project page. Create a BigQuery dataset called `deliriumwatch`.

**Step 2 — Run SQL queries in order**

Execute each SQL file in `sql/` in numbered order (01 through 08) in Google BigQuery, replacing the project ID `project-9ae3a63a-1ef4-4b4c-916` with your own.

**Step 3 — Download master features**

```sql
SELECT * FROM `your-project.deliriumwatch.master_features_v3`
```

Save as `deliriumwatch_master_v3.csv` in the project root.

**Step 4 — Run EDA notebook**

Open `notebooks/deliriumwatch_eda.ipynb` and run all cells. This produces `deliriumwatch_clean_v3.csv`.

**Step 5 — Run model notebook**

Open `notebooks/deliriumwatch_model.ipynb` and run all cells. Reproduces AUROC 0.8947, SHAP plots, and ablation results.

> Note: Do not commit any CSV files. The `.gitignore` excludes all patient data files.

---

## Ethical Considerations

**Data privacy:** All analysis uses de-identified data from MIMIC-IV under PhysioNet DUA. No patient data is stored in this repository or transmitted to external services.

**Clinical deployment:** This model is a research prototype. It has not been validated prospectively or clinically approved. Any real-world deployment would require IRB approval, prospective validation, and integration review.

**Limitations:**
- Single-center data (Beth Israel Deaconess Medical Center, Boston) — may not generalize to other hospital systems or international populations
- CAM-ICU documentation has known compliance gaps — nurses sometimes skip assessments
- NID is a proxy for sleep disruption, not a direct measurement
- No temporal validation yet (train/test split is random, not time-based)
- Vitals features are summary statistics across the pre-delirium window — not the temporal trajectory

**Fairness:** Model performance stratified by demographics (gender, age group, ICU type) is planned as a future analysis milestone.

---

## Roadmap

### Completed ✅
- [x] PhysioNet + BigQuery access setup
- [x] Cohort extraction (48,786 ICU stays)
- [x] Label engineering from CAM-ICU assessments
- [x] Feature engineering — vitals, sedation, SOFA, NID
- [x] Reverse causality audit and correction
- [x] EDA pipeline — missing values, outliers, correlation analysis
- [x] Logistic Regression baseline (AUROC 0.8299)
- [x] XGBoost model (AUROC 0.8947)
- [x] SHAP analysis (NID rank #2)
- [x] NID ablation study (+0.0155 AUROC)
- [x] Mann-Whitney U validation (p < 0.0001)

### In Progress 🔄
- [ ] Optuna hyperparameter tuning (target AUROC 0.91+)
- [ ] Temporal validation (train pre-2019, test post-2019)
- [ ] Calibration curve analysis

### Planned 📋
- [ ] Mechanical ventilation duration feature
- [ ] Sedation trajectory slope (direction of change, not just cumulative dose)
- [ ] Fairness analysis by demographics
- [ ] Streamlit clinical decision support app


---

## Team

**Vasa Shashank,Nandan Reddy,Chethan Prakash,Venkata Saivijay Kuncham**
CSE, RVCE Bangalore (2022 scheme, 4th semester)
PhysioNet: vijay0820

---

## Citation

If you use this work, please cite:

```
Vasa Shashank,Nandan Reddy,Chethan Prakash,Kuncham, V.S. (2026).
DeliriumWatch: Temporal Early Warning System for ICU 
Delirium Onset Using Nighttime Intervention Density from MIMIC-IV. 
GitHub: https://github.com/Variiish06/DeliriumWatch
```

---

## Data Access

This project uses MIMIC-IV v3.1. To access the data:

1. Complete CITI training at physionet.org
2. Request credentialed access to MIMIC-IV
3. Sign the Data Use Agreement
4. Request BigQuery access from the project Files section

Full instructions: https://physionet.org/content/mimiciv/3.1/

---

*DeliriumWatch — Built on MIMIC-IV. Validated on 48,786 ICU stays.*
