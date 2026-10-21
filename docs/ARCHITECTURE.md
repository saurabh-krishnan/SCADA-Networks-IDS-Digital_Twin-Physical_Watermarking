# Architecture & Data Flow

This document describes how the SCADA Digital‑Twin Security Platform is put together, the
per‑tick data flow, the physics/detection models, and the design invariants that make the
cyber‑physical security story honest.

> Educational simulation only. The models are simplified, plausible and hypothetical — not
> validated engineering or safety models.

---

## 1. Component map

```
backend/app/
├── core/
│   ├── rng.py            Deterministic, per‑component seeded RNG streams + counter‑based hashing
│   └── util.py           Rolling stats, severity helpers, id generators, JSON rounding
├── simulation/
│   ├── boiler.py         Liquid‑metal boiler + IHX + secondary loop + generator (lumped ODEs)
│   ├── subsystems.py     Induction motor, water treatment, chemical mixing, pipeline/tank farm
│   ├── devices.py        Sensor / Actuator / Device abstractions + firmware/output hooks
│   ├── control.py        PI(D) controller with anti‑windup
│   ├── plant.py          Plant assembly: physics + sensor/actuator inventory, steady‑state init
│   ├── plc.py            Generic PLC/RTU runtime with a Modbus register model + server
│   ├── programs.py       Control programs ("ladder") for PLC‑1..4 and RTU‑5
│   ├── safety.py         Hard‑wired Safety Instrumented System (independent trips)
│   ├── scada.py          SCADA server, HMI/EWS workstations, historian, MQTT broker, auth/directory
│   ├── wiring.py         Static wiring: register maps, allowed flows, authorised writers, inventory
│   └── engine.py         The per‑tick orchestrator + snapshot/chart views
├── network/
│   ├── topology.py       Purdue‑zoned node/link graph + routing + fixed HMI layout
│   ├── protocols.py      Modbus TCP (real ADU bytes) + OPC UA / MQTT (app‑level emulation)
│   └── traffic.py        Discrete‑event message bus: routing, loss, delay, MITM, SPAN mirror
├── digital_twin/
│   ├── model.py          Independent RK4 physics + actuator datasheet models
│   ├── prediction.py     Twin service: propagate, gated correction, health/sync status, forecast
│   └── residuals.py      Residual tracker: z‑score, two‑sided CUSUM, sudden‑error, calibration
├── ids/
│   ├── base.py           Condition → Finding lifecycle (dedup, hold, clear)
│   ├── network_detector.py   Flows, rates, floods, replay, unauthorised/out‑of‑envelope writes…
│   ├── process_detector.py   Limits, frozen, rate‑of‑change, setpoint deviation, pump‑flow, energy
│   ├── consistency.py    Analytical‑redundancy energy balances (design datasheet)
│   ├── twin_detector.py  Persistent/sudden residuals + correlated multi‑sensor anomalies
│   ├── watermark_detector.py  Turns watermark decisions into IDS conditions
│   ├── correlation.py    Incident correlation, classification, response recommendation
│   └── manager.py        Orchestrates the four layers each tick
├── watermarking/
│   ├── signal.py         Reproducible, bounded PRBS/uniform excitation (seed‑derived)
│   ├── detector.py       Per‑channel correlation / gain / SNR decision (consistent/suspicious/inconclusive)
│   └── engine.py         Injection into the control path, shadow‑model expected response, suspension logic
├── attacks/
│   ├── context.py        The narrow capability set handed to the attacker
│   ├── scenarios.py      10 reproducible scenarios + ground‑truth effect labels
│   └── injector.py       Attack lab manager (start/stop, seeds, ground‑truth query)
├── response/
│   └── engine.py         Monitor / approval / auto response modes against simulated components
├── storage/
│   └── database.py       SQLite persistence (alerts, incidents, events, responses, experiments)
├── experiments/
│   ├── metrics.py        Ground‑truth labelling + precision/recall/F1/latency/deviation/recovery
│   └── runner.py         Headless deterministic runner; scores one trace under 4 detector configs
├── api/
│   ├── models.py         Pydantic request models (validation for every control endpoint)
│   └── runtime.py        Live loop, WebSocket hub, event persistence, experiment execution
└── main.py               FastAPI app: REST + WebSocket (+ serves the built frontend)
```

Frontend mirrors this with one page per subsystem (`frontend/src/pages/*`), a typed API client
(`services/api.ts`), a WebSocket hook (`hooks/useWebSocket.ts`), and shared chart/UI components.

---

## 2. Per‑tick data flow (default dt = 0.1 s, 10 Hz)

`SimulationEngine._tick()` runs this fixed order every step:

1. **Attack lab** applies any active manipulations (installs interceptors, injects packets,
   sets firmware hooks). Nothing here touches defensive components.
2. **Physical plant** integrates one step from the *real* actuator outputs (ground truth).
3. **Safety system** reads the real state directly and may trip final elements.
4. **Field I/O**: each sensor samples the true value (noise, quantisation, range clamp, optional
   attacker output hook) and reports it over the field bus; PLCs run their scan and command actuators.
5. **Network bus** delivers all messages scheduled up to this tick (routing, loss, delay,
   MITM interceptors, SPAN mirror to the IDS).
6. **SCADA** polls PLC input/holding registers (Modbus), ingests MQTT telemetry, feeds the
   historian and the twin; evaluates HMI alarms and comms health.
7. **Digital twin** propagates its own state and computes residuals; the **watermark engine**
   updates its expected (shadow‑model) and observed responses.
8. **IDS** runs the four detection layers on SCADA observations and the SPAN mirror; findings
   feed the **correlation engine**; the **response engine** acts per its mode.
9. A compact **snapshot** is assembled for the WebSocket and chart buffers.

The live API runs this loop in a background asyncio task at a wall‑clock rate scaled by the
speed multiplier, broadcasting snapshots to all WebSocket clients and persisting
alerts/incidents/responses/events to SQLite.

---

## 3. Process model (educational)

Lumped‑parameter, explicit‑Euler (sub‑stepped) primary + secondary loop:

```
Boiler vessel  C_b dT_b/dt  = Q_heater − m·cp·(T_b − T_cl) − UA_loss·(T_b − T_amb)
Hot leg            dT_hl/dt  = (T_b − T_hl)·m / M_hl                  (transport lag)
IHX primary    C_x dT_cl/dt  = m·cp·(T_hl − T_cl) − Q_hx
IHX secondary  C_so dT_so/dt = C_s·(T_si − T_so) + Q_hx
Heat sinks     C_si dT_si/dt = C_s·(T_so − T_si) − Q_turbine − Q_cooler
Q_hx = ε(NTU,Cr)·C_min·(T_hl − T_si)      (counter‑flow effectiveness‑NTU)
```

Primary hydraulics relax to the pump/valve operating point (`H0·s² − Kp·m² = (Ksys+Kv/v²)·m²`);
cover‑gas pressure rises with bulk temperature. Auxiliary subsystems (motor affinity‑law
current/vibration, filtration fouling/turbidity/chlorine, batch reactor exotherm,
pipeline/tank hydraulics) use the same reusable abstractions. Parameters are configurable and
hypothetical.

---

## 4. The digital twin is independent

- It integrates its **own** RK4 copy of the physics with **datasheet** parameters that differ
  from the plant by a few percent (realistic model error).
- It is driven by **issued commands** (plus the trusted watermark offset) and a few **measured
  inputs** (heater power, fan speed, generator power). It never reads `plant.physical`.
- Measurements are fused via a **gated correction**: a one‑step‑ahead prediction, then a small
  move toward each measurement **only if** its normalised innovation `|z| < gate`. Readings that
  jump outside the gate are rejected, so a falsified sensor cannot silently drag the twin along —
  which is exactly why a stealthy lie produces a growing, *detectable* residual.
- Residuals feed a two‑sided **CUSUM** (persistence) and a sudden‑error counter, with an initial
  calibration window that estimates residual bias/spread. Anomaly score = CUSUM / threshold.

---

## 5. Multi‑layer IDS

| Layer | Evidence source | Example rules |
|---|---|---|
| **Network** | SPAN mirror (`Mirror` records, no ground truth) | unknown device, MAC/ARP spoof, unexpected flow, abnormal rate, flood, bad sequence/replay, unauthorised/out‑of‑envelope/policy write, comms degradation, integrity failure |
| **Process** | SCADA observations | alarm limits, frozen (stuck‑at), implausible rate‑of‑change, setpoint deviation vs approved, pump‑flow inconsistency, actuator command/feedback mismatch, energy‑balance / redundancy violation |
| **Twin** | Residual trackers | persistent residual, sudden prediction error, correlated multi‑sensor anomaly (with a model‑vs‑measurement consistency hint) |
| **Watermark** | Watermark engine decision | missing/abnormal correlation, excessive response error, inconclusive |

A detector reports **conditions**; the `FindingManager` deduplicates them into alert records
(first report raises, repeats update, silence clears). The **correlation engine** groups
findings in the same zone/time window into incidents, combines confidence as
`1 − ∏(1 − c_layer)`, raises severity per corroborating layer, classifies transparently, and
recommends responses — never double‑counting duplicates.

---

## 6. Physical watermarking

A reproducible, bounded PRBS excitation (pure function of seed + slot) is added to an eligible
actuator command (default P‑101) **inside the PLC's secured function block** — the exported
command register still reports the operator's base value. Two shadow copies of the twin's
hydraulics predict the **expected** response; SCADA telemetry gives the **observed** response
(both high‑pass filtered). Per channel the detector computes correlation ρ, response gain vs a
calibrated baseline, and SNR, yielding **consistent / suspicious / inconclusive**.

Injection self‑suspends on a safety trip, actuator saturation, proximity to process limits, or
poor measurement quality, and it is never forced to produce a positive detection.

---

## 7. Attack laboratory & isolation

The attacker is handed an `AttackContext` with exactly: the network bus, the topology, the
sensor/actuator firmware hooks, a compromised engineering workstation, a narrow physical‑
degradation handle, and lab clean‑up callbacks. It has **no reference** to the safety system,
the twin, the IDS or the watermark engine (enforced by `tests/test_isolation.py`).

Ten scenarios (false data injection, frozen sensor, actuator manipulation, unauthorised
setpoint, command replay, network DoS, insider misuse, twin model tamper, watermark
interference, coordinated). Each records its seed/params, produces real simulation changes,
exposes `effect_active(t)` as the **ground‑truth label**, and supports stop/recover. Crucially,
during telemetry falsification the **physical process keeps evolving from real actuator action**
while only the *observed* values are altered — the gap the twin/redundancy/watermark expose.

---

## 8. Defensive responses (simulated only)

Monitor (record), operator‑approved (confirm then act), or automatic. Actions act through narrow
simulated effects: quarantine an endpoint (drop at the switch), enable a PLC write allow‑list,
restore an approved setpoint (trusted internal write), disable a directory account, mark a device
suspicious, fail over to an authenticated anti‑replay channel, enter a reduced‑load safe state,
resync the twin, preserve evidence, pause. The response engine never issues real control and is
kept separate from the safety interlocks.

---

## 9. Experiment evaluation

The headless runner plays a fresh, deterministic engine through `[baseline → attack → recovery]`
and records a per‑sample trace of ground‑truth labels, active findings (by layer/asset),
setpoint deviation and incident state. The **same** trace is then scored under four detector
configurations (network‑only, network+process, network+process+twin, full+watermark) so the
comparison is apples‑to‑apples. Metrics: TP/FP/TN/FN, precision/recall/F1, detection latency
(first detection after onset), process‑deviation RMS/max, and recovery time, over aligned
evaluation windows. Ground‑truth labels are used **only** here — never by the detectors.

See [`../experiments/`](../experiments/) for the A–F sample outputs and
[`../experiments/README.md`](../experiments/README.md) for how to read them.
