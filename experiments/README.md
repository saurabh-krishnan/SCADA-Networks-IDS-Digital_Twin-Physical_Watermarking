# Experiment outputs

These are **actual outputs** from the headless, deterministic experiment runner
(`backend/app/experiments/runner.py`, master seed `1337`). Each `*.json` holds the full
result for one scenario, scored under four detector configurations from a single recorded run.
Regenerate them any time with the snippet at the bottom, or run experiments interactively on
the **Experiment Analytics** page.

## Summary (detection F1 by configuration)

| Run | Scenario | Network only | Net+Process | Net+Proc+Twin | Full+Watermark | Latency (full) |
|---|---|---|---|---|---|---|
| A_normal | normal operation | — F1=1.00 | — F1=1.00 | — F1=1.00 | — F1=1.00 | n/a |
| B_fdi_no_wm | false data injection | ❌ 0.00 | ✅ 0.94 | ✅ 0.94 | ✅ 0.94 | 0.2 s |
| C_wm_interf | watermark interference | ❌ 0.00 | ❌ 0.00 | ✅ 0.71 | ✅ 0.96 | 1.1 s |
| D_unauth_setpt | unauthorized setpoint | ✅ 0.91 | ✅ 0.91 | ✅ 0.91 | ✅ 0.91 | 0.0 s |
| E_replay | command replay | ✅ 0.93 | ✅ 0.93 | ✅ 0.93 | ✅ 0.93 | 0.5 s |
| F_coordinated | coordinated proc+net | ✅ 0.91 | ✅ 0.91 | ✅ 0.91 | ✅ 0.91 | 0.5 s |

✅ = detected, ❌ = missed. For **A (normal)** there is nothing to detect: the configurations
raise no sustained alerts (no false positives), so "F1=1.00" reflects zero FP / zero FN over
zero attack windows — the honest reading is *"no detection, no false alarms."*

### What the matrix shows

- **Network‑IDS‑only misses telemetry falsification** (B, C): a field‑bus sensor lie or a
  watermark‑erasing replay produces no network‑layer evidence. This is the core motivation for
  the extra layers — and it is an emergent result of the detection logic, not a hardcoded one.
- **Process + twin recover the sensor‑falsification cases** (B): energy‑balance redundancy and
  the independent twin residual catch the lie within ~0.2 s.
- **The watermark layer adds real value for watermark interference** (C): process alone sees
  nothing (0.00), the twin partially catches the slow drift (0.71), and adding the physical
  watermark raises detection to 0.96 — because the attacker smoothed away the injected
  signature while keeping the mean plausible.
- **Network layer is sufficient for command‑path attacks** (D, E, F): unauthorized writes,
  replays and the coordinated attack all leave direct network evidence, so even network‑only
  detects them (the extra layers still corroborate and classify).

The few false positives in B–F are mostly **post‑attack recovery transients** — after a strong
disturbance the real process is still settling when ground truth goes inactive, so process
limits can briefly fire. This is physically honest and visible in the per‑run JSON.

## File format

Each `*.json` contains:
- `config` — the exact experiment configuration (seed, scenario, params, timing).
- `overall` — metrics with all layers enabled.
- `by_detector_config` — metrics for `network_only`, `network_process`, `network_process_twin`,
  `full`; each has `tp/fp/tn/fn`, `precision/recall/f1`, `detection_latency_s`,
  `process_deviation_rms/max`, `recovery_time_s`, `detected`.
- `final_incidents`, `responses` — incident records and any executed responses.

`sample_config.json` is a ready‑to‑POST body for `POST /api/experiments/run`.

## Regenerate

```bash
cd backend
./.venv/Scripts/python.exe - <<'PY'
import json
from app.experiments.runner import run_experiment, ExperimentConfig
r = run_experiment(ExperimentConfig(label="demo", scenario="false_data_injection",
        scenario_params={"tag":"TT-101","mode":"bias","bias":-18.0},
        duration=210, attack_at=63, attack_stop=151))
print(json.dumps(r["by_detector_config"], indent=2))
PY
```

Or via the API:

```bash
curl -s http://127.0.0.1:8000/api/experiments/run -H "Content-Type: application/json" \
  -d @experiments/sample_config.json | python -m json.tool
```
