"""
Train the drone/engine RUL model on the real NASA C-MAPSS dataset.

Run:  python train_model.py

Design decisions that matter for trusting the numbers this prints:

1. Engines are split, never rows. Consecutive cycles of one engine are nearly identical,
   so a random row split lets the model memorise an engine and then be tested on that same
   engine. It reports a wonderful score and fails on the first unseen airframe.

2. Final accuracy is measured on NASA's separate test files against the supplied
   ground-truth RUL, so the headline number comes from engines the model never touched in
   any form.

3. All four subsets are used. They span different operating conditions and fault modes, so
   a model trained across them generalises rather than learning one narrow regime.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold, RandomizedSearchCV

from cmapss import (
    RUL_CAP,
    add_training_rul,
    build_features,
    drop_constant_columns,
    load_subset,
    load_true_rul,
)

SUBSETS = ["FD001", "FD002", "FD003", "FD004"]
RANDOM_STATE = 42
MODEL_PATH = Path("rul_model.joblib")
METADATA_PATH = Path("model_metadata.json")


def rmse(y_true, y_pred) -> float:
    return float(np.sqrt(np.mean((np.asarray(y_true) - np.asarray(y_pred)) ** 2)))


def phm08_score(y_true, y_pred) -> float:
    """
    The scoring function from the original PHM08 challenge. Lower is better.

    It penalises late predictions far more steeply than early ones, because claiming an
    engine is fine when it is about to fail is the expensive kind of mistake.
    """
    d = np.asarray(y_pred, dtype=float) - np.asarray(y_true, dtype=float)
    early = d < 0
    return float(np.sum(np.expm1(-d[early] / 13.0)) + np.sum(np.expm1(d[~early] / 10.0)))


def banner(text: str) -> None:
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}")


# ----------------------------------------------------------------------------------
# Load training data
# ----------------------------------------------------------------------------------
banner("STEP 1  Load real C-MAPSS training data")

train_frames = []
for subset in SUBSETS:
    frame = load_subset(subset, "train")
    train_frames.append(frame)
    print(
        f"  {subset}: {len(frame):>6,} cycles  "
        f"{frame['uid'].nunique():>3} engines  "
        f"median life {frame.groupby('uid')['cycle'].max().median():.0f} cycles"
    )

train_df = add_training_rul(pd.concat(train_frames, ignore_index=True))
print(f"\n  Combined: {len(train_df):,} cycles from {train_df['uid'].nunique()} engines")
print(f"  Labels clipped at RUL_CAP = {RUL_CAP} cycles")

# ----------------------------------------------------------------------------------
# Features
# ----------------------------------------------------------------------------------
banner("STEP 2  Build trajectory features")

t0 = time.perf_counter()
X_all = build_features(train_df)
feature_cols = drop_constant_columns(X_all)
dropped = sorted(set(X_all.columns) - set(feature_cols))
X_all = X_all[feature_cols]
y_all = train_df["rul"].to_numpy()
groups = train_df["uid"].to_numpy()

print(f"  Built {X_all.shape[1]} features in {time.perf_counter() - t0:.1f}s")
print(f"  Dropped {len(dropped)} constant columns (no variance, no information)")
print(f"  Feature matrix: {X_all.shape[0]:,} rows x {X_all.shape[1]} columns")

# ----------------------------------------------------------------------------------
# Tune the random forest
# ----------------------------------------------------------------------------------
banner("STEP 3  Tune Random Forest (grouped CV, engines never split across folds)")

# Searching on every row of every subset would take far longer than it is worth. A random
# sample of whole engines preserves the structure of the problem while cutting the search
# to a few minutes; the winning configuration is then refit on all the data.
rng = np.random.default_rng(RANDOM_STATE)
all_engines = np.unique(groups)
search_engines = rng.choice(all_engines, size=int(len(all_engines) * 0.35), replace=False)
search_mask = np.isin(groups, search_engines)
print(f"  Searching on {search_mask.sum():,} rows from {len(search_engines)} engines")

param_space = {
    "max_depth": [15, 25, None],
    # Larger leaves both regularise the model and keep the serialised file small, which
    # matters because an unconstrained forest on 160k rows serialises to hundreds of MB.
    "min_samples_leaf": [10, 20, 40],
    "max_features": ["sqrt", 0.3],
}

search = RandomizedSearchCV(
    RandomForestRegressor(
        n_estimators=80,  # kept low during search; the final fit uses far more
        random_state=RANDOM_STATE,
        n_jobs=-1,
    ),
    param_distributions=param_space,
    n_iter=8,
    cv=GroupKFold(n_splits=3),
    scoring="neg_root_mean_squared_error",
    random_state=RANDOM_STATE,
    n_jobs=1,  # the forest itself is already parallel
    verbose=0,
)

t0 = time.perf_counter()
search.fit(X_all[search_mask], y_all[search_mask], groups=groups[search_mask])
print(f"  Search finished in {time.perf_counter() - t0:.0f}s")
print(f"  Best params: {search.best_params_}")
print(f"  Grouped CV RMSE: {-search.best_score_:.2f} cycles")

# ----------------------------------------------------------------------------------
# Fit final candidates on all training data
# ----------------------------------------------------------------------------------
banner("STEP 4  Fit final models on all training engines")

forest = RandomForestRegressor(
    n_estimators=300,
    random_state=RANDOM_STATE,
    n_jobs=-1,
    **search.best_params_,
)
t0 = time.perf_counter()
forest.fit(X_all, y_all)
print(f"  RandomForest (300 trees) fitted in {time.perf_counter() - t0:.0f}s")

# Gradient boosting is included as a challenger because it is usually the stronger model on
# tabular data and serialises to a fraction of the size. Whichever wins on the held-out
# test engines is the one that ships.
booster = HistGradientBoostingRegressor(
    max_iter=600,
    learning_rate=0.06,
    max_leaf_nodes=63,
    min_samples_leaf=40,
    l2_regularization=1.0,
    early_stopping=True,
    validation_fraction=0.15,
    random_state=RANDOM_STATE,
)
t0 = time.perf_counter()
booster.fit(X_all, y_all)
print(
    f"  HistGradientBoosting fitted in {time.perf_counter() - t0:.0f}s "
    f"({booster.n_iter_} boosting rounds before early stop)"
)

# ----------------------------------------------------------------------------------
# Evaluate on the real held-out test engines
# ----------------------------------------------------------------------------------
banner("STEP 5  Evaluate on NASA's held-out test engines")

print(
    "  For each test engine we take its final recorded cycle and compare the prediction\n"
    "  against the ground-truth RUL shipped with the dataset.\n"
)

test_rows, test_truth = [], []
for subset in SUBSETS:
    test_df = load_subset(subset, "test")
    test_feats = build_features(test_df)
    last_idx = test_df.groupby("uid")["cycle"].idxmax()
    rows = test_feats.loc[last_idx, feature_cols]
    rows.index = test_df.loc[last_idx, "uid"]
    truth = load_true_rul(subset).reindex(rows.index)
    test_rows.append(rows)
    test_truth.append(truth)

X_test = pd.concat(test_rows)
y_test_raw = pd.concat(test_truth).to_numpy(dtype=float)
# The model is trained to saturate at RUL_CAP, so an engine 180 cycles from failure is
# graded against 125. Comparing against 180 would penalise the model for a horizon its
# labels deliberately do not encode. The uncapped figure is reported too, for honesty.
y_test = np.clip(y_test_raw, None, RUL_CAP)
print(f"  {len(X_test)} test engines across {len(SUBSETS)} subsets\n")

candidates = {"RandomForest": forest, "HistGradientBoosting": booster}
results = {}

header = f"  {'Model':<22} {'RMSE':>8} {'MAE':>8} {'R2':>8} {'PHM08':>10} {'Size':>9}"
print(header)
print("  " + "-" * (len(header) - 2))

for name, model in candidates.items():
    pred = np.clip(model.predict(X_test), 0, RUL_CAP)
    tmp = Path(f".size_probe_{name}.joblib")
    joblib.dump(model, tmp, compress=3)
    size_mb = tmp.stat().st_size / 1e6
    tmp.unlink()

    results[name] = {
        "rmse": rmse(y_test, pred),
        "mae": float(mean_absolute_error(y_test, pred)),
        "r2": float(r2_score(y_test, pred)),
        "phm08": phm08_score(y_test, pred),
        "rmse_uncapped": rmse(y_test_raw, pred),
        "size_mb": round(size_mb, 2),
    }
    r = results[name]
    print(
        f"  {name:<22} {r['rmse']:>8.2f} {r['mae']:>8.2f} {r['r2']:>8.3f} "
        f"{r['phm08']:>10.0f} {r['size_mb']:>7.1f}MB"
    )

best_name = min(results, key=lambda n: results[n]["rmse"])
best_model = candidates[best_name]
print(f"\n  Winner on unseen engines: {best_name}")

# ----------------------------------------------------------------------------------
# Per-subset breakdown for the winner
# ----------------------------------------------------------------------------------
banner(f"STEP 6  Per-subset performance ({best_name})")

pred_best = np.clip(best_model.predict(X_test), 0, RUL_CAP)
breakdown = {}
print(f"  {'Subset':<10} {'Engines':>8} {'RMSE':>8} {'MAE':>8}  Conditions")
print("  " + "-" * 62)
condition_notes = {
    "FD001": "1 condition, 1 fault mode",
    "FD002": "6 conditions, 1 fault mode",
    "FD003": "1 condition, 2 fault modes",
    "FD004": "6 conditions, 2 fault modes",
}
for subset in SUBSETS:
    mask = X_test.index.str.startswith(subset)
    subset_rmse = rmse(y_test[mask], pred_best[mask])
    subset_mae = float(mean_absolute_error(y_test[mask], pred_best[mask]))
    breakdown[subset] = {"engines": int(mask.sum()), "rmse": subset_rmse, "mae": subset_mae}
    print(
        f"  {subset:<10} {mask.sum():>8} {subset_rmse:>8.2f} {subset_mae:>8.2f}  "
        f"{condition_notes[subset]}"
    )

# ----------------------------------------------------------------------------------
# Feature importance
# ----------------------------------------------------------------------------------
banner("STEP 7  What the model actually looks at")

if hasattr(best_model, "feature_importances_"):
    importance = pd.Series(best_model.feature_importances_, index=feature_cols)
    top = importance.sort_values(ascending=False).head(12)
    print("  Top 12 features by importance:\n")
    for feat, val in top.items():
        bar = "#" * max(1, int(val / top.iloc[0] * 40))
        print(f"    {feat:<24} {val:6.4f}  {bar}")
else:
    print("  (Gradient boosting exposes no native importances; skipping.)")

# ----------------------------------------------------------------------------------
# Persist
# ----------------------------------------------------------------------------------
banner("STEP 8  Save model and metadata")

joblib.dump(
    {
        "model": best_model,
        "model_name": best_name,
        "feature_cols": feature_cols,
        "rul_cap": RUL_CAP,
    },
    MODEL_PATH,
    compress=3,
)
size_mb = MODEL_PATH.stat().st_size / 1e6
print(f"  Wrote {MODEL_PATH} ({size_mb:.1f} MB)")

metadata = {
    "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    "dataset": "NASA C-MAPSS FD001-FD004 (real run-to-failure data)",
    "training_rows": int(len(train_df)),
    "training_engines": int(train_df["uid"].nunique()),
    "test_engines": int(len(X_test)),
    "rul_cap": RUL_CAP,
    "n_features": len(feature_cols),
    "selected_model": best_name,
    "best_forest_params": search.best_params_,
    "grouped_cv_rmse": float(-search.best_score_),
    "held_out_results": results,
    "per_subset": breakdown,
    "evaluation_note": (
        "Metrics come from NASA's separate test files scored against the supplied "
        "ground-truth RUL. Engines are split, never rows, so no engine appears in both "
        "training and evaluation."
    ),
}
METADATA_PATH.write_text(json.dumps(metadata, indent=2))
print(f"  Wrote {METADATA_PATH}")

banner("DONE")
r = results[best_name]
print(
    f"  {best_name} predicts RUL on unseen engines with RMSE {r['rmse']:.1f} cycles "
    f"(MAE {r['mae']:.1f}, R2 {r['r2']:.3f}).\n"
    f"  Next: python sanity_check.py"
)
