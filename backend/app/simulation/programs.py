"""Control programs ("ladder logic") for each PLC / RTU, and factory functions."""
from __future__ import annotations

from app.core.util import clamp
from app.network.protocols import mqtt_publish
from app.network.traffic import Message
from app.simulation.control import PID
from app.simulation.plant import DESIGN, Plant
from app.simulation.plc import PLC, HoldingSpec

HB = HoldingSpec("HEARTBEAT", 0.0, 0.0, 1e9, "", "SCADA watchdog heartbeat", "system")


# ----------------------------------------------------------------------------- PLC-1
def program_plc1(plc: PLC, t: float, dt: float) -> None:
    pid = plc.pid["TIC-101"]
    pid.kp, pid.ti = plc.h("TIC-101.KP"), plc.h("TIC-101.TI")
    tripped = plc.di.get("SIS.TRIP", 0.0) > 0.5
    if tripped:
        pid.init_output(0.0)
        out = 0.0
    elif plc.h("TIC-101.MODE") >= 0.5:
        out = pid.update(plc.h("TIC-101.SP"), plc.sensor("TT-101", plc.h("TIC-101.SP")), dt)
    else:
        out = plc.h("HTR-101.MAN")
        pid.init_output(out)
    plc.command("HTR-101", out)
    plc.state["TIC-101.OUT"] = out
    base = plc.h("P-101.SP")
    wm = plc.watermark_hook("P-101", t, base) if plc.watermark_hook else 0.0
    # The watermark lives inside the PLC's secured function block: the exported command
    # register reports the operator's base command, not the excitation.
    plc.command("P-101", base + wm, reported=base)
    vbase = plc.h("FCV-101.SP")
    wmv = plc.watermark_hook("FCV-101", t, vbase) if plc.watermark_hook else 0.0
    plc.command("FCV-101", vbase + wmv, reported=vbase)


def make_plc1(plant: Plant) -> PLC:
    holding = [
        HB,
        HoldingSpec("TIC-101.SP", DESIGN["TIC-101.SP"], 300, 520, "°C", "Hot-leg temperature setpoint"),
        HoldingSpec("TIC-101.MODE", 1.0, 0, 1, "", "Heater loop mode (1=auto, 0=manual)"),
        HoldingSpec("HTR-101.MAN", 60.0, 0, 100, "%", "Heater manual output"),
        HoldingSpec("P-101.SP", DESIGN["P-101.SP"], 30, 100, "%", "Primary pump speed command"),
        HoldingSpec("FCV-101.SP", DESIGN["FCV-101.SP"], 10, 100, "%", "Flow-control valve position"),
        HoldingSpec("TIC-101.KP", 3.0, 0.1, 20, "%/K", "Heater PID gain", "config"),
        HoldingSpec("TIC-101.TI", 60.0, 5, 600, "s", "Heater PID integral time", "config"),
    ]
    plc = PLC("PLC-1", "Primary loop controller", 1, "primary", ["TT-101", "TT-102", "TT-103", "FT-101", "PT-101",
                                                                  "PT-102", "JT-101"],
              ["HTR-101", "P-101", "FCV-101"], holding, ["TIC-101.OUT", "STATUS.SIS_TRIP", "STATUS.WATCHDOG"],
              program_plc1)
    pid = PID(3.0, 60.0, lo=0, hi=100)
    pid.init_output(plant.design_outputs["heater_pct"])
    plc.pid["TIC-101"] = pid
    _prime(plc, plant)
    return plc


# ----------------------------------------------------------------------------- PLC-2
def program_plc2(plc: PLC, t: float, dt: float) -> None:
    pid = plc.pid["TIC-201"]
    pid.kp, pid.ti = plc.h("TIC-201.KP"), plc.h("TIC-201.TI")
    out = pid.update(plc.h("TIC-201.SP"), plc.sensor("TT-201", plc.h("TIC-201.SP")), dt)
    plc.command("FAN-201", out)
    plc.state["TIC-201.OUT"] = out
    plc.command("P-201", plc.h("P-201.SP"))


def make_plc2(plant: Plant) -> PLC:
    holding = [
        HB,
        HoldingSpec("TIC-201.SP", DESIGN["TIC-201.SP"], 180, 250, "°C", "Secondary inlet temperature setpoint"),
        HoldingSpec("P-201.SP", DESIGN["P-201.SP"], 30, 100, "%", "Secondary pump speed command"),
        HoldingSpec("TIC-201.KP", 8.0, 0.1, 30, "%/K", "Fan PID gain", "config"),
        HoldingSpec("TIC-201.TI", 40.0, 5, 600, "s", "Fan PID integral time", "config"),
    ]
    plc = PLC("PLC-2", "Secondary loop & generator controller", 2, "secondary",
              ["TT-201", "TT-202", "FT-201", "JT-201", "ST-201"], ["P-201", "FAN-201"], holding,
              ["TIC-201.OUT", "STATUS.SIS_TRIP", "STATUS.WATCHDOG"], program_plc2)
    pid = PID(8.0, 40.0, lo=0, hi=100, direct=True)
    pid.init_output(plant.design_outputs["fan_pct"])
    plc.pid["TIC-201"] = pid
    _prime(plc, plant)
    return plc


# ----------------------------------------------------------------------------- PLC-3
def program_plc3(plc: PLC, t: float, dt: float) -> None:
    st = plc.state
    lvl_pid, cl_pid = plc.pid["LIC-302"], plc.pid["AIC-302"]
    raw = plc.sensor("LT-301", 3.0)
    if raw < 2.5:
        st["XV301.OPEN"] = 1.0
    elif raw > 4.0:
        st["XV301.OPEN"] = 0.0
    plc.command("XV-301", 100.0 * st.get("XV301.OPEN", 1.0))
    if st.get("SEQ.STATE", 0.0) < 0.5:
        if plc.sensor("PDT-301", 0.2) > plc.h("BW.DP_SP"):
            st["SEQ.STATE"] = 1.0
            st["BW.T0"] = t
            st["BW.COUNT"] = st.get("BW.COUNT", 0.0) + 1
    elif t - st.get("BW.T0", t) >= plc.h("BW.DURATION"):
        st["SEQ.STATE"] = 0.0
    if st.get("SEQ.STATE", 0.0) >= 0.5:
        plc.command("XV-303", 100.0)
        plc.command("P-301", 60.0)
        lvl_pid.init_output(55.0)
    else:
        plc.command("XV-303", 0.0)
        plc.command("P-301", lvl_pid.update(plc.h("LIC-302.SP"), plc.sensor("LT-302", 4.0), dt))
    plc.command("P-302", cl_pid.update(plc.h("AIC-302.SP"), plc.sensor("AT-302", 1.0), dt))


def make_plc3(plant: Plant) -> PLC:
    holding = [
        HB,
        HoldingSpec("LIC-302.SP", 4.0, 1.0, 5.5, "m", "Treated-water level setpoint"),
        HoldingSpec("AIC-302.SP", 1.0, 0.3, 2.5, "mg/L", "Chlorine residual setpoint"),
        HoldingSpec("BW.DP_SP", 0.85, 0.4, 1.2, "bar", "Backwash trigger dP", "config"),
        HoldingSpec("BW.DURATION", 40.0, 10, 120, "s", "Backwash duration", "config"),
    ]
    plc = PLC("PLC-3", "Water treatment controller", 3, "water",
              ["LT-301", "LT-302", "FT-301", "PDT-301", "AT-301", "AT-302", "AT-303"],
              ["P-301", "P-302", "XV-301", "XV-303"], holding, ["SEQ.STATE", "BW.COUNT", "STATUS.WATCHDOG"],
              program_plc3)
    lp = PID(60.0, 120.0, lo=0, hi=100)
    lp.init_output(55.0)
    cp = PID(15.0, 40.0, lo=0, hi=100)
    cp.init_output(25.0)
    plc.pid.update({"LIC-302": lp, "AIC-302": cp})
    plc.state.update({"SEQ.STATE": 0.0, "BW.COUNT": 0.0, "XV301.OPEN": 1.0})
    _prime(plc, plant)
    return plc


# ----------------------------------------------------------------------------- PLC-4
PHASES = ["IDLE", "FILL_A", "FILL_B", "REACT", "DRAIN"]


def program_plc4(plc: PLC, t: float, dt: float) -> None:
    st = plc.state
    phase = int(st.get("BATCH.PHASE", 0))
    lvl = plc.sensor("LT-401", 5.0)
    elapsed = t - st.get("BATCH.T0", 0.0)
    nxt = phase
    if plc.h("BATCH.ENABLE") < 0.5:
        nxt = 0
    elif phase == 0 and elapsed >= 5.0:
        nxt = 1
    elif phase == 1 and lvl >= 45.0:
        nxt = 2
    elif phase == 2 and lvl >= 85.0:
        nxt = 3
    elif phase == 3 and elapsed >= plc.h("BATCH.REACT_S"):
        nxt = 4
    elif phase == 4 and lvl <= 8.0:
        nxt = 0
        st["BATCH.COUNT"] = st.get("BATCH.COUNT", 0.0) + 1
    if nxt != phase:
        st["BATCH.PHASE"] = float(nxt)
        st["BATCH.T0"] = t
        phase = nxt
    st["BATCH.TIMER"] = t - st.get("BATCH.T0", 0.0)
    plc.command("XV-401", 100.0 if phase == 1 else 0.0)
    plc.command("XV-402", 100.0 if phase == 2 else 0.0)
    plc.command("XV-403", 100.0 if phase == 4 else 0.0)
    plc.command("M-401", 100.0 if phase == 3 else 30.0 if phase in (2, 4) else 0.0)
    plc.command("TCV-401", plc.pid["TIC-401"].update(plc.h("TIC-401.SP"), plc.sensor("TT-401", 35.0), dt))


def make_plc4(plant: Plant) -> PLC:
    holding = [
        HB,
        HoldingSpec("TIC-401.SP", 45.0, 20, 70, "°C", "Reactor temperature setpoint"),
        HoldingSpec("BATCH.REACT_S", 60.0, 10, 600, "s", "Reaction hold time", "config"),
        HoldingSpec("BATCH.ENABLE", 1.0, 0, 1, "", "Batch sequencer enable"),
    ]
    plc = PLC("PLC-4", "Chemical mixing controller", 4, "mixing",
              ["LT-401", "TT-401", "AT-401", "AT-402", "ST-401", "IT-401", "TT-402", "VT-401"],
              ["XV-401", "XV-402", "XV-403", "M-401", "TCV-401"], holding,
              ["BATCH.PHASE", "BATCH.COUNT", "BATCH.TIMER", "STATUS.WATCHDOG"], program_plc4)
    plc.pid["TIC-401"] = PID(8.0, 20.0, lo=0, hi=100, direct=True)
    plc.state.update({"BATCH.PHASE": 0.0, "BATCH.T0": 0.0, "BATCH.COUNT": 0.0})
    _prime(plc, plant)
    return plc


# ----------------------------------------------------------------------------- RTU-5
class RTU(PLC):
    """Remote terminal unit at the tank farm. Talks MQTT (publish/subscribe) instead of Modbus."""

    TOPIC_TELEMETRY = "site/tankfarm/RTU-5/telemetry"
    TOPIC_CMD = "site/tankfarm/RTU-5/cmd"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._pkt = 0
        self.publish_every = 5
        self.cmd_log: list[dict] = []

    def on_mqtt(self, msg: Message) -> None:
        p = msg.payload
        if p.get("topic") != self.TOPIC_CMD:
            return
        body = p.get("payload", {})
        name, value = body.get("register"), body.get("value")
        spec = self.holding_spec.get(name)
        ok = spec is not None and isinstance(value, (int, float)) and spec.lo <= value <= spec.hi
        if ok and self.allowlist_enforced and msg.src not in ("MQTT-01",):
            ok = False
        if ok:
            old = self.hold.values[name]
            self.hold.values[name] = float(value)
            self.write_log.append({"t": msg.t_deliver, "src": msg.src, "user": msg.user, "register": name,
                                   "old": old, "value": value, "accepted": True})
        else:
            self.write_log.append({"t": msg.t_deliver, "src": msg.src, "user": msg.user, "register": name,
                                   "value": value, "accepted": False, "reason": "invalid"})

    def scan(self, t: float, dt: float) -> None:
        super().scan(t, dt)
        if self.bus is not None and self.scan_count % self.publish_every == 0:
            self._pkt = (self._pkt % 65535) + 1
            body = {n: round(v, 4) for n, v in self.inp.values.items()}
            body.update({f"SP:{n}": v for n, v in self.hold.values.items() if n != "HEARTBEAT"})
            self.bus.send(Message(t + 0.001, self.id, "MQTT-01", "mqtt", "PUBLISH telemetry",
                                  mqtt_publish(self.TOPIC_TELEMETRY, self._pkt, body), seq=self._pkt))


def program_rtu5(plc: PLC, t: float, dt: float) -> None:
    st = plc.state
    plc.command("P-501", plc.pid["FIC-501"].update(plc.h("FIC-501.SP"), plc.sensor("FT-501", 80.0), dt))
    active = int(st.get("ROUTE.ACTIVE", 1))
    l1, l2 = plc.sensor("LT-501", 5.0), plc.sensor("LT-502", 4.0)
    la, lb = (l1, l2) if active == 1 else (l2, l1)
    if (la > plc.h("ROUTE.HI") and lb < plc.h("ROUTE.HI") - 1.0) or lb < plc.h("ROUTE.LO"):
        active = 2 if active == 1 else 1
    st["ROUTE.ACTIVE"] = float(active)
    plc.command("XV-501", 100.0 if active == 1 else 0.0)
    plc.command("XV-502", 100.0 if active == 2 else 0.0)


def make_rtu5(plant: Plant) -> RTU:
    holding = [
        HoldingSpec("FIC-501.SP", 80.0, 20, 115, "m³/h", "Pipeline flow setpoint"),
        HoldingSpec("ROUTE.HI", 8.5, 5, 9.5, "m", "Tank switch-over high level", "config"),
        HoldingSpec("ROUTE.LO", 2.0, 0.5, 4, "m", "Tank switch-over low level", "config"),
    ]
    rtu = RTU("RTU-5", "Tank farm RTU", 5, "pipeline",
              ["FT-501", "PT-501", "PT-502", "LT-501", "LT-502", "ST-501", "IT-501", "TT-501", "VT-501"],
              ["P-501", "XV-501", "XV-502"], holding, ["ROUTE.ACTIVE"], program_rtu5, protocol="mqtt")
    p = PID(0.3, 8.0, lo=0, hi=100)
    p.init_output(70.0)
    rtu.pid["FIC-501"] = p
    rtu.state["ROUTE.ACTIVE"] = 1.0
    _prime(rtu, plant)
    return rtu


def _prime(plc: PLC, plant: Plant) -> None:
    """Seed the PLC's input image with the initial plant state (as if it had been running)."""
    for sid in plc.sensor_ids:
        s = plant.sensors[sid]
        v = plant.physical[s.variable]
        plc.field[sid] = v
        plc.inp.values[sid] = v
    for a in plc.actuator_ids:
        act = plant.actuators[a]
        plc.fb[a] = act.feedback
        plc.cmd[a] = act.command
        plc.reported_cmd[a] = act.command


def build_controllers(plant: Plant) -> dict[str, PLC]:
    return {c.id: c for c in (make_plc1(plant), make_plc2(plant), make_plc3(plant), make_plc4(plant),
                              make_rtu5(plant))}


def clamp_pct(v: float) -> float:
    return clamp(v, 0.0, 100.0)
