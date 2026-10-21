# SCADA Digital-Twin Security Platform

A **live, interactive cyber-physical security research demonstrator**. It simulates a
liquid‑metal boiler plant with a realistic industrial control network, a real‑time
SCADA/HMI, an **independent digital twin**, a **multi‑layer intrusion‑detection system**,
a **physical‑watermarking** engine, a **cyber‑attack laboratory**, and an **automated
defensive‑response** engine — plus an experiment dashboard that measures and compares
detection performance.

> ⚠️ **Educational simulation only.** Every device, sensor reading, network packet and
> attack is synthetic and runs locally. The physics is a simplified, plausible, *hypothetical*
> model — **not** a validated nuclear, thermal or industrial‑engineering model. Nothing here
> connects to real industrial equipment or external control networks.

The UI has eight pages: **Plant Overview** (animated P&ID + live telemetry), **Device Explorer**,
**Network Topology**, **Digital Twin**, **Security Center**, **Watermarking**, **Attack Lab**
and **Experiment Analytics**.

---

## What it does

- **Simulates a plant**: liquid‑metal boiler + intermediate heat exchanger + secondary loop +
  turbine‑generator, a water‑treatment plant, a chemical‑mixing batch reactor, and a
  pipeline/tank‑farm — 37 sensors, 17 actuators, 5 PLCs/RTU, a hard‑wired safety system.
- **Simulates the network**: a Purdue‑zoned graph with Modbus TCP (spec‑conformant ADU bytes),
  OPC UA and MQTT (application‑level emulation), latency/jitter/loss, authentication, and a
  SPAN mirror feeding the IDS.
- **Runs an independent digital twin**: its own RK4 physics with datasheet parameters that
  differ from the plant, gated measurement fusion, and residual/CUSUM anomaly detection.
- **Detects attacks on four layers**: network, process, digital‑twin and physical‑watermark,
  correlated into deduplicated incidents with transparent classification.
- **Injects 10 reproducible attack scenarios** that change the *simulation* (not just the UI),
  with recorded seeds and ground‑truth labels kept out of the detectors' reach.
- **Responds** in monitor / operator‑approval / automatic modes against simulated components.
- **Evaluates** detection with precision/recall/F1, latency, process deviation and recovery
  time across six detector configurations from a single recorded run.

---

## Quick start

### One command (serves API **and** the built UI on http://127.0.0.1:8000)

```bash
# Windows PowerShell
./start.ps1
```
```bash
# Git Bash / Linux / macOS
./start.sh
```

The script creates the Python virtual environment (if missing), installs backend
dependencies, builds the frontend, and launches a single Uvicorn process that serves both
the REST/WebSocket API and the compiled React UI. Open **http://127.0.0.1:8000**.

### Development mode (hot‑reload UI on :5173, API on :8000)

```bash
./dev.sh
```
Then open **http://localhost:5173** (Vite proxies `/api` and `/ws` to the backend).

### Manual setup

```bash
# Backend
cd backend
py -3 -m venv .venv                       # python -m venv .venv on Linux/macOS
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```
```bash
# Frontend (in a second terminal)
cd frontend
npm install
npm run dev        # or: npm run build  (then the backend serves dist/ on :8000)
```

**Requirements:** Python 3.11+ and Node.js 18+. Docker is optional and not required.

---

## The end‑to‑end demonstration (walkthrough)

1. Open the dashboard and press **Start** (top bar). Watch temperatures, flow, pressure,
   pump state and generator output update live on **Plant Overview**.
2. Open **Network Topology** — inspect the Purdue‑zoned graph and the live SPAN traffic
   (Modbus polls, MQTT telemetry, field I/O).
3. Open **Digital Twin** — predicted vs observed values track within noise; residuals are flat.
4. Open **Watermarking** → **Enable watermark**. After calibration the decision reads
   **CONSISTENT** (the injected PRBS shows up in the measured flow/pressure response).
5. Open **Experiments**, run **Normal operation** → zero false positives.
6. Open **Attack Lab**, set response mode to **auto**, and **launch “False sensor data
   injection”** (TT‑101, bias −18 °C).
7. Back on **Plant Overview / Digital Twin**: the *real* hot‑leg temperature keeps rising
   (the heater over‑drives chasing the falsified‑low reading) while SCADA shows the fake value —
   the twin prediction and the observation **diverge** (residual z ≈ −26, CUSUM saturated).
8. On **Security Center**: the **process** (energy‑balance) and **twin** (sudden‑residual)
   layers fire — **not** the network layer — correlated into a critical *“False data injection”*
   incident; the auto‑response executes *mark‑suspicious*, *failover‑secure‑channel* and
   *preserve‑evidence*.
9. **Stop & recover** the scenario; approved setpoints are restored.
10. In **Experiments**, run the same attack and read the A–F comparison: **Network‑IDS‑only
    detects nothing**, while Network+Process and the full stack catch it (F1 ≈ 0.94).
11. Press **Reset** to return to the baseline.

Sample outputs for all six configurations are in [`experiments/`](experiments/).

---

## Architecture (one‑minute version)

```
                         ┌──────────────── FRONTEND (React/TS/Vite/Tailwind) ───────────────┐
  Browser  ◀── WebSocket │  8 HMI pages · Recharts time‑series · React‑Flow topology         │
           ◀── REST      └──────────────────────────────────────────────────────────────────┘
                                             │  /api  /ws
  ┌──────────────────────────────── BACKEND (FastAPI + Uvicorn) ───────────────────────────────┐
  │  Simulation engine (10 Hz tick):                                                            │
  │    attack lab → PHYSICAL PLANT (ground truth) → hard‑wired SAFETY → field I/O → PLC scans   │
  │       → NETWORK bus (routed, SPAN‑mirrored) → SCADA polling → DIGITAL TWIN + WATERMARK      │
  │       → IDS (network·process·twin·watermark) → CORRELATION → RESPONSE engine → snapshot     │
  │  Storage: SQLite (alerts/incidents/events/responses/experiments) · rolling telemetry buffers│
  │  Experiment runner: headless, deterministic, scores one trace under 4 detector configs      │
  └─────────────────────────────────────────────────────────────────────────────────────────────┘
```

Key design invariants (checked by tests):
- The **attacker** can only touch the network and field‑device firmware hooks — never the
  safety system, the twin, the IDS or the watermark engine.
- The **digital twin** never reads the plant's ground‑truth state; falsified telemetry can only
  influence it through a gated correction, so a stealthy lie is *detectable*, not invisible.
- The **safety system** is independent of the network and the response engine; an emergency
  trip hard‑cuts the final element regardless of any firmware tampering.
- **Ground‑truth labels** reach the experiment evaluator only — never the detectors.

Full details and data‑flow: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Tests

```bash
cd backend
./.venv/Scripts/python.exe -m pytest        # 56 tests
```

Covers: process‑model calculations, safety constraints & independence, device transitions,
twin independence & residuals, watermark signal/response, false‑data injection, IDS detection
& correlation, defensive responses, API validation, WebSocket telemetry, DB persistence and
experiment metrics.

---

## Project layout

```
backend/   FastAPI app, simulation engine, twin, IDS, watermarking, attacks, response, storage, tests
frontend/  React + TypeScript HMI (8 pages), Recharts, React‑Flow, Tailwind
docs/      Architecture & data‑flow documentation
experiments/  Sample experiment configs and actual outputs (A–F matrix)
start.ps1 / start.sh / dev.sh   Launch scripts
```
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the module‑by‑module map.

---

## API

Interactive docs at **http://127.0.0.1:8000/docs**. Highlights: `GET /api/health`,
`/api/plant/state`, `/api/network/topology`, `/api/twin/state`, `/api/ids/alerts`,
`/api/ids/incidents`, `/api/watermarking/state`, `/api/attacks`, `/api/experiments`;
`POST /api/simulation/{start,pause,reset,speed}`, `/api/attacks/{start,stop}`,
`/api/watermarking/{enable,disable,config}`, `/api/control/setpoint`,
`/api/response/{mode,approve}`, `/api/experiments/run`; WebSocket `/ws` (live snapshots ~5–10 Hz).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| UI shows “Connecting to backend…” | Backend not up on :8000. Start it (`./start.sh` or the manual uvicorn command). In dev mode the Vite proxy expects the backend on :8000. |
| `py` not found (Windows) | Use `python` instead, or install Python 3.11+ from python.org. |
| Port 8000 already in use | `uvicorn app.main:app --port 8001` and open that port (dev mode: edit `frontend/vite.config.ts` proxy target). |
| Frontend build fails | Delete `frontend/node_modules`, run `npm install`, then `npm run build`. Needs Node 18+. |
| Network topology briefly blank | It fits once the first topology poll returns (~1 s); it then renders and stays interactive. |
| Simulation reset to t=0 | Restarting the backend creates a fresh, deterministic engine. Press **Start**. |
| Watermark stays “inconclusive” | It needs ~45 s (sim time) to calibrate; speed up with the ×8 control. It also self‑suspends during a safety trip or when a monitored channel's quality is poor. |
| A detector “misses” an attack | That can be correct — e.g. network‑IDS‑only cannot see a field‑bus sensor lie. The UI shows this honestly; use the Experiments page to compare configurations. |

---

## Reproducibility

Every stochastic component draws from its own seeded stream (master seed default `1337`,
set via `SCADA_SEED`). Attack scenarios record their seed and parameters. The headless
experiment runner is fully deterministic for a given seed, so results replay exactly.
