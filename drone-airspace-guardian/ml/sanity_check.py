"""
Sanity checks for the health model. Run before wiring anything into the backend.

Run:  python sanity_check.py

Four checks, in order of how much they would embarrass us if they failed:

  1. Real engine  - stream a held-out engine's actual run-to-failure trace and confirm
                    health declines. The model never saw this engine in training.
  2. Clock control - hold every sensor at its healthy value while the cycle counter climbs.
                    `cycle` is one of the model's features, so it could in principle be
                    reading the clock rather than the sensors and still look convincing on
                    check 1. A flat trace must stay materially healthier than a degrading
                    one at the same cycle, or the model has learned nothing about wear.
  3. Fleet-wide   - across every held-out engine, predicted health should correlate with
                    true remaining life.
  4. Simulated    - the synthetic telemetry the backend will use for demos behaves sanely.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from cmapss import (
    RAW_COLS,
    RUL_CAP,
    build_features,
    load_subset,
    load_true_rul,
    rul_to_health,
)
from predict import HealthMonitor, _feature_cols, _model, simulate_drone_telemetry

PASS, FAIL = "PASS", "FAIL"
results: dict[str, str] = {}


def banner(text: str) -> None:
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}")


def verdict(name: str, ok: bool, detail: str) -> None:
    results[name] = PASS if ok else FAIL
    print(f"\n  [{results[name]}] {name}")
    print(f"        {detail}")


# ----------------------------------------------------------------------------------
banner("CHECK 1  Real held-out engine, streamed cycle by cycle")

test_df = load_subset("FD001", "test")
truth = load_true_rul("FD001")

# Pick the test engine with the longest recorded history so there is a full trajectory to
# watch, rather than an engine cut off after a handful of cycles.
lengths = test_df.groupby("uid")["cycle"].max()
engine_uid = str(lengths.idxmax())
engine = test_df[test_df["uid"] == engine_uid].sort_values("cycle")
true_final_rul = float(truth[engine_uid])

print(f"\n  Engine {engine_uid}: {len(engine)} recorded cycles")
print(f"  Ground-truth RUL at its final cycle: {true_final_rul:.0f} more cycles")
print("  This engine is in NASA's test file and was never seen during training.\n")

monitor = HealthMonitor(drone_id=engine_uid)
real_health = []
for _, row in engine.iterrows():
    reading = {"cycle": int(row["cycle"])}
    reading.update({c: float(row[c]) for c in RAW_COLS})
    result = monitor.update(reading)
    real_health.append(result["health"])

step = max(1, len(real_health) // 8)
print(f"  {'Cycle':>6} {'Health':>8}  Trend")
print("  " + "-" * 40)
for i in range(0, len(real_health), step):
    bar = "#" * max(1, int(real_health[i] / 100 * 28))
    print(f"  {int(engine['cycle'].iloc[i]):>6} {real_health[i]:>7.1f}%  {bar}")

start_health = float(np.mean(real_health[:5]))
end_health = float(np.mean(real_health[-5:]))
drop = start_health - end_health

# Compare the final prediction against the ground truth for this engine.
final_feats = build_features(
    engine.assign(uid=engine_uid)
).iloc[[-1]].reindex(columns=_feature_cols, fill_value=0.0)
final_pred_rul = float(np.clip(_model.predict(final_feats)[0], 0, RUL_CAP))

print(f"\n  Health at start (mean of first 5 cycles): {start_health:.1f}%")
print(f"  Health at end   (mean of last 5 cycles):  {end_health:.1f}%")
print(f"  Predicted RUL at final cycle: {final_pred_rul:.1f} cycles "
      f"(truth {true_final_rul:.0f}, capped target {min(true_final_rul, RUL_CAP):.0f})")

verdict(
    "Real engine health declines",
    drop > 15.0,
    f"Health fell {drop:.1f} points across this engine's real degradation history.",
)

# ----------------------------------------------------------------------------------
banner("CHECK 2  Clock control: healthy sensors, climbing cycle counter")

print(
    "\n  Two traces run to the same cycle count. One degrades, one holds every sensor at\n"
    "  its healthy value. If the model were merely counting cycles both would fall\n"
    "  together, and the health score would be worthless on real hardware.\n"
)

TICKS = 120
degrading = simulate_drone_telemetry(num_ticks=TICKS, failure_at=TICKS, seed=7)
# noise_scale keeps a little jitter so the flat trace is not unnaturally perfect, and
# failure_at far beyond the trace length holds severity near zero throughout.
flat = simulate_drone_telemetry(num_ticks=TICKS, failure_at=10**6, seed=7)

deg_monitor, flat_monitor = HealthMonitor("degrading"), HealthMonitor("flat")
deg_health, flat_health = [], []
for d_read, f_read in zip(degrading, flat):
    deg_health.append(deg_monitor.update(d_read)["health"])
    flat_health.append(flat_monitor.update(f_read)["health"])

print(f"  {'Cycle':>6} {'Degrading':>11} {'Flat':>9} {'Gap':>8}")
print("  " + "-" * 40)
for i in range(14, TICKS, 15):
    gap = flat_health[i] - deg_health[i]
    print(f"  {i + 1:>6} {deg_health[i]:>10.1f}% {flat_health[i]:>8.1f}% {gap:>7.1f}")

final_gap = flat_health[-1] - deg_health[-1]
verdict(
    "Model reads sensors, not the clock",
    final_gap > 25.0,
    f"At cycle {TICKS} the flat trace scores {flat_health[-1]:.1f}% versus "
    f"{deg_health[-1]:.1f}% for the degrading trace, a {final_gap:.1f} point gap.",
)

# ----------------------------------------------------------------------------------
banner("CHECK 3  Fleet-wide agreement with ground truth")

rows, truths = [], []
for subset in ["FD001", "FD002", "FD003", "FD004"]:
    sub_test = load_subset(subset, "test")
    feats = build_features(sub_test)
    last = sub_test.groupby("uid")["cycle"].idxmax()
    frame = feats.loc[last, _feature_cols]
    frame.index = sub_test.loc[last, "uid"]
    rows.append(frame)
    truths.append(load_true_rul(subset).reindex(frame.index))

X_fleet = pd.concat(rows)
y_fleet = pd.concat(truths).to_numpy(float)
pred_rul = np.clip(_model.predict(X_fleet), 0, RUL_CAP)
pred_health = rul_to_health(pred_rul)
true_health = rul_to_health(np.clip(y_fleet, None, RUL_CAP))

rho = float(spearmanr(pred_health, true_health).statistic)
mae = float(np.mean(np.abs(pred_health - true_health)))

print(f"\n  Engines evaluated: {len(X_fleet)}")
print(f"  Spearman correlation, predicted vs true health: {rho:.3f}")
print(f"  Mean absolute health error: {mae:.1f} points")

print(f"\n  {'True health band':<22} {'Engines':>8} {'Mean predicted':>16}")
print("  " + "-" * 48)
bands = [(0, 25, "0-25 (critical)"), (25, 50, "25-50 (service)"),
         (50, 75, "50-75 (monitor)"), (75, 101, "75-100 (healthy)")]
for lo, hi, label in bands:
    mask = (true_health >= lo) & (true_health < hi)
    if mask.any():
        print(f"  {label:<22} {int(mask.sum()):>8} {pred_health[mask].mean():>15.1f}%")

verdict(
    "Predictions track true remaining life",
    rho > 0.75,
    f"Spearman rho {rho:.3f} across {len(X_fleet)} unseen engines, "
    f"mean health error {mae:.1f} points.",
)

# ----------------------------------------------------------------------------------
banner("CHECK 4  Simulated telemetry behaves sanely")

sim_health = deg_health  # reuse the degrading run from check 2
# Smooth before checking direction: cycle-to-cycle noise makes a strictly monotonic
# requirement unrealistic, but the underlying trend must be downward.
smoothed = pd.Series(sim_health).rolling(10, min_periods=1).mean()
falling_fraction = float((np.diff(smoothed) <= 0).mean())

print(f"\n  Start health: {sim_health[0]:.1f}%")
print(f"  End health:   {sim_health[-1]:.1f}%")
print(f"  Smoothed trend is non-increasing across {falling_fraction * 100:.0f}% of steps")

verdict(
    "Simulated trace declines smoothly",
    sim_health[0] - sim_health[-1] > 40 and falling_fraction > 0.85,
    f"Simulated drone fell from {sim_health[0]:.1f}% to {sim_health[-1]:.1f}% "
    f"with a consistently downward trend.",
)

# ----------------------------------------------------------------------------------
banner("SUMMARY")

width = max(len(k) for k in results)
for name, outcome in results.items():
    print(f"  {name:<{width}}  {outcome}")

all_passed = all(v == PASS for v in results.values())
print()
if all_passed:
    print("  All checks passed. The health score responds to real degradation and is")
    print("  safe to wire into the backend.")
else:
    print("  One or more checks FAILED. Do not integrate until resolved.")

# ----------------------------------------------------------------------------------
# Chart
try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    ax1.plot(engine["cycle"].to_numpy(), real_health, lw=2, color="#B03A2E")
    ax1.set_title(f"Real held-out engine {engine_uid}", fontweight="bold")
    ax1.set_xlabel("Flight cycle")
    ax1.set_ylabel("Health (%)")

    ax2.plot(range(1, TICKS + 1), deg_health, lw=2, label="Degrading", color="#B03A2E")
    ax2.plot(range(1, TICKS + 1), flat_health, lw=2, label="Healthy (control)",
             color="#1E8449", ls="--")
    ax2.set_title("Degrading vs healthy at equal cycle count", fontweight="bold")
    ax2.set_xlabel("Simulated tick")
    ax2.legend()

    for ax in (ax1, ax2):
        ax.set_ylim(0, 105)
        ax.grid(alpha=0.3)
        for level, colour in ((75, "#1E8449"), (50, "#B7950B"), (25, "#B03A2E")):
            ax.axhline(level, color=colour, ls=":", alpha=0.5)

    fig.tight_layout()
    fig.savefig("health_degradation.png", dpi=140)
    print("\n  Chart written to health_degradation.png")
except ImportError:
    print("\n  (matplotlib not installed; skipping chart)")

raise SystemExit(0 if all_passed else 1)
