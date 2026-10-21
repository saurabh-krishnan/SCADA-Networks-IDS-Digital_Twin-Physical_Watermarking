"""Plant assembly: physical subsystem models + field-device inventory.

``Plant.physical`` is the ground-truth process state.  Only sensors (through
``Sensor.sample``) and the hard-wired safety system read it.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.rng import SeedBank
from app.simulation.boiler import BoilerLoop, BoilerParams, load_profile
from app.simulation.devices import Actuator, AlarmLimits, DeviceRegistry, Sensor
from app.simulation.subsystems import ChemicalMixing, PipelineTankFarm, WaterTreatment

SUBSYSTEMS = {
    "primary": "Liquid-metal boiler & primary loop",
    "secondary": "Heat exchanger, secondary loop & turbine-generator",
    "water": "Water treatment plant",
    "mixing": "Chemical mixing tank",
    "pipeline": "Pipeline & storage tank farm",
}


@dataclass
class SensorSpec:
    id: str
    name: str
    subsystem: str
    controller: str
    variable: str
    unit: str
    sigma: float
    resolution: float
    rng: tuple[float, float]
    limits: tuple  # (lo_lo, lo, hi, hi_hi)
    max_rate: float
    every: int = 1


SENSORS = [
    # Primary loop (PLC-1) — reported every tick (10 Hz)
    SensorSpec("TT-101", "Hot-leg temperature", "primary", "PLC-1", "boiler.T_hl", "°C", 0.35, 0.01, (0, 700), (None, 400, 480, 520), 3.0),
    SensorSpec("TT-102", "Cold-leg temperature", "primary", "PLC-1", "boiler.T_cl", "°C", 0.35, 0.01, (0, 700), (None, 330, 430, 470), 3.0),
    SensorSpec("TT-103", "Boiler bulk temperature", "primary", "PLC-1", "boiler.T_b", "°C", 0.30, 0.01, (0, 700), (None, 400, 480, 520), 3.0),
    SensorSpec("FT-101", "Primary LM flow", "primary", "PLC-1", "boiler.m", "kg/s", 0.08, 0.001, (0, 35), (8, 12, 26, None), 8.0),
    SensorSpec("PT-101", "Pump discharge pressure", "primary", "PLC-1", "boiler.P_dis", "bar", 0.012, 0.001, (0, 10), (None, 2.4, 4.6, 5.0), 3.0),
    SensorSpec("PT-102", "Cover-gas pressure", "primary", "PLC-1", "boiler.P_cover", "bar", 0.004, 0.0001, (0, 5), (None, 1.4, 2.2, 2.4), 0.5),
    SensorSpec("JT-101", "Heater electrical power", "primary", "PLC-1", "boiler.Q_heater", "kW", 4.0, 0.1, (0, 3000), (None, None, 2400, None), 2000.0),
    # Secondary loop + generator (PLC-2)
    SensorSpec("TT-201", "Secondary inlet temperature", "secondary", "PLC-2", "sec.T_si", "°C", 0.30, 0.01, (0, 400), (None, 190, 245, 260), 3.0),
    SensorSpec("TT-202", "Secondary outlet temperature", "secondary", "PLC-2", "sec.T_so", "°C", 0.30, 0.01, (0, 400), (None, 210, 285, 300), 3.0),
    SensorSpec("FT-201", "Secondary water flow", "secondary", "PLC-2", "sec.m_s", "kg/s", 0.05, 0.001, (0, 20), (4, 6, None, None), 8.0),
    SensorSpec("JT-201", "Generator electrical output", "secondary", "PLC-2", "gen.P", "kW", 2.0, 0.1, (0, 600), (None, None, 430, None), 200.0),
    SensorSpec("ST-201", "Generator speed", "secondary", "PLC-2", "gen.speed", "rpm", 0.6, 0.1, (0, 3600), (None, 2940, 3060, 3100), 30.0),
    # Water treatment (PLC-3) — 2 Hz
    SensorSpec("LT-301", "Raw-water tank level", "water", "PLC-3", "wt.L_raw", "m", 0.01, 0.001, (0, 6), (0.3, 0.8, 5.0, None), 0.5, 5),
    SensorSpec("LT-302", "Treated-water tank level", "water", "PLC-3", "wt.L_tw", "m", 0.01, 0.001, (0, 6), (0.5, 1.0, 5.6, None), 0.5, 5),
    SensorSpec("FT-301", "Filtered-water flow", "water", "PLC-3", "wt.Q_filt", "m³/h", 0.5, 0.01, (0, 150), (None, None, None, None), 40.0, 5),
    SensorSpec("PDT-301", "Filter differential pressure", "water", "PLC-3", "wt.dP", "bar", 0.005, 0.001, (0, 2), (None, None, 1.0, 1.3), 5.0, 5),
    SensorSpec("AT-301", "Treated-water turbidity", "water", "PLC-3", "wt.turb_out", "NTU", 0.01, 0.001, (0, 10), (None, None, 1.0, 4.0), 5.0, 5),
    SensorSpec("AT-302", "Chlorine residual", "water", "PLC-3", "wt.cl", "mg/L", 0.02, 0.001, (0, 5), (0.2, 0.4, 2.0, 4.0), 1.0, 5),
    SensorSpec("AT-303", "Treated-water pH", "water", "PLC-3", "wt.ph", "pH", 0.01, 0.001, (0, 14), (6.0, 6.5, 8.5, 9.0), 1.0, 5),
    # Chemical mixing (PLC-4) — 2 Hz
    SensorSpec("LT-401", "Mixing tank level", "mixing", "PLC-4", "mix.level", "%", 0.2, 0.01, (0, 100), (None, None, 95, 98), 15.0, 5),
    SensorSpec("TT-401", "Reactor temperature", "mixing", "PLC-4", "mix.T", "°C", 0.1, 0.01, (0, 150), (None, None, 65, 75), 5.0, 5),
    SensorSpec("AT-401", "Reactor pH", "mixing", "PLC-4", "mix.ph", "pH", 0.02, 0.001, (0, 14), (None, None, None, None), 20.0, 5),
    SensorSpec("AT-402", "Product concentration", "mixing", "PLC-4", "mix.conc", "%", 0.2, 0.01, (0, 100), (None, None, None, None), 60.0, 5),
    SensorSpec("ST-401", "Agitator speed", "mixing", "PLC-4", "mix.agit_rpm", "rpm", 2.0, 0.1, (0, 1800), (None, None, None, None), 2000.0, 5),
    SensorSpec("IT-401", "Agitator motor current", "mixing", "PLC-4", "mix.motor_I", "A", 0.3, 0.01, (0, 200), (None, None, 60, 80), 500.0, 5),
    SensorSpec("TT-402", "Agitator winding temperature", "mixing", "PLC-4", "mix.motor_T", "°C", 0.1, 0.01, (0, 200), (None, None, 110, 130), 5.0, 5),
    SensorSpec("VT-401", "Agitator vibration", "mixing", "PLC-4", "mix.motor_vib", "mm/s", 0.03, 0.001, (0, 20), (None, None, 4.5, 7.1), 10.0, 5),
    # Pipeline / tank farm (RTU-5) — 2 Hz
    SensorSpec("FT-501", "Pipeline flow", "pipeline", "RTU-5", "pipe.Q", "m³/h", 0.4, 0.01, (0, 150), (None, 20, 120, None), 40.0, 5),
    SensorSpec("PT-501", "Pump discharge pressure", "pipeline", "RTU-5", "pipe.P1", "bar", 0.02, 0.001, (0, 16), (None, 1.0, 9.0, 11.0), 6.0, 5),
    SensorSpec("PT-502", "Delivery-end pressure", "pipeline", "RTU-5", "pipe.P2", "bar", 0.02, 0.001, (0, 16), (None, None, 8.0, None), 6.0, 5),
    SensorSpec("LT-501", "Storage tank 501 level", "pipeline", "RTU-5", "pipe.L1", "m", 0.01, 0.001, (0, 10), (0.5, 0.8, 9.2, 9.7), 0.5, 5),
    SensorSpec("LT-502", "Storage tank 502 level", "pipeline", "RTU-5", "pipe.L2", "m", 0.01, 0.001, (0, 10), (0.5, 0.8, 9.2, 9.7), 0.5, 5),
    SensorSpec("ST-501", "Transfer motor speed", "pipeline", "RTU-5", "pipe.motor_rpm", "rpm", 2.0, 0.1, (0, 3600), (None, None, None, None), 2500.0, 5),
    SensorSpec("IT-501", "Transfer motor current", "pipeline", "RTU-5", "pipe.motor_I", "A", 0.5, 0.01, (0, 400), (None, None, 120, 150), 800.0, 5),
    SensorSpec("TT-501", "Transfer motor winding temperature", "pipeline", "RTU-5", "pipe.motor_T", "°C", 0.1, 0.01, (0, 200), (None, None, 110, 130), 5.0, 5),
    SensorSpec("VT-501", "Transfer motor vibration", "pipeline", "RTU-5", "pipe.motor_vib", "mm/s", 0.03, 0.001, (0, 20), (None, None, 4.5, 7.1), 10.0, 5),
]

ACTUATORS = [
    # id, name, subsystem, controller, kind, unit, lo, hi, rate_limit, tau
    ("HTR-101", "Boiler heater (SCR)", "primary", "PLC-1", "heater", "%", 0, 100, 20.0, 0.0),
    ("P-101", "Primary LM pump (VFD)", "primary", "PLC-1", "pump_vfd", "%", 0, 100, 6.0, 0.4),
    ("FCV-101", "Primary flow-control valve", "primary", "PLC-1", "valve", "%", 0, 100, 10.0, 0.3),
    ("P-201", "Secondary water pump (VFD)", "secondary", "PLC-2", "pump_vfd", "%", 0, 100, 6.0, 0.4),
    ("FAN-201", "Air-cooler fan (VFD)", "secondary", "PLC-2", "fan", "%", 0, 100, 8.0, 1.0),
    ("P-301", "Filter feed pump (VFD)", "water", "PLC-3", "pump_vfd", "%", 0, 100, 10.0, 0.5),
    ("P-302", "Chlorine dosing pump", "water", "PLC-3", "dosing_pump", "%", 0, 100, 20.0, 0.0),
    ("XV-301", "Raw-water inlet valve", "water", "PLC-3", "onoff_valve", "%", 0, 100, 50.0, 0.0),
    ("XV-303", "Filter backwash valve", "water", "PLC-3", "onoff_valve", "%", 0, 100, 50.0, 0.0),
    ("XV-401", "Reagent A feed valve", "mixing", "PLC-4", "onoff_valve", "%", 0, 100, 50.0, 0.0),
    ("XV-402", "Reagent B feed valve", "mixing", "PLC-4", "onoff_valve", "%", 0, 100, 50.0, 0.0),
    ("XV-403", "Reactor drain valve", "mixing", "PLC-4", "onoff_valve", "%", 0, 100, 50.0, 0.0),
    ("M-401", "Agitator motor (VFD)", "mixing", "PLC-4", "motor_vfd", "%", 0, 100, 25.0, 0.0),
    ("TCV-401", "Reactor cooling valve", "mixing", "PLC-4", "valve", "%", 0, 100, 15.0, 0.0),
    ("P-501", "Pipeline transfer pump (VFD)", "pipeline", "RTU-5", "pump_vfd", "%", 0, 100, 8.0, 0.0),
    ("XV-501", "Tank 501 inlet valve", "pipeline", "RTU-5", "onoff_valve", "%", 0, 100, 25.0, 0.0),
    ("XV-502", "Tank 502 inlet valve", "pipeline", "RTU-5", "onoff_valve", "%", 0, 100, 25.0, 0.0),
]

# Design operating point (also used for steady-state initialisation)
DESIGN = {
    "TIC-101.SP": 450.0,
    "P-101.SP": 85.0,
    "FCV-101.SP": 80.0,
    "TIC-201.SP": 220.0,
    "P-201.SP": 80.0,
}


class Plant:
    def __init__(self, seeds: SeedBank, boiler_params: BoilerParams | None = None):
        self.params = boiler_params or BoilerParams()
        self.boiler = BoilerLoop(self.params, seeds.noise("plant.boiler.disturbance"))
        self.water = WaterTreatment(seeds.noise("plant.water.disturbance"))
        self.mixing = ChemicalMixing(seeds.noise("plant.mixing.disturbance"))
        self.pipeline = PipelineTankFarm(seeds.noise("plant.pipeline.disturbance"))
        self.registry = DeviceRegistry()
        self.sensors: dict[str, Sensor] = {}
        self.actuators: dict[str, Actuator] = {}
        for sp in SENSORS:
            s = Sensor(id=sp.id, name=sp.name, subsystem=sp.subsystem, controller=sp.controller,
                       variable=sp.variable, unit=sp.unit, noise_sigma=sp.sigma, resolution=sp.resolution,
                       range_lo=sp.rng[0], range_hi=sp.rng[1], limits=AlarmLimits(*sp.limits),
                       max_rate=sp.max_rate, sample_every=sp.every, noise=seeds.noise(f"sensor.{sp.id}"))
            s.params = {"sigma": sp.sigma, "resolution": sp.resolution, "max_rate": sp.max_rate,
                        "report_hz": round(10 / sp.every, 1)}
            s.auth_state = "unauthenticated (field bus)"
            self.registry.add(s)
            self.sensors[s.id] = s
        for (aid, name, sub, ctrl, kind, unit, lo, hi, rate, tau) in ACTUATORS:
            a = Actuator(id=aid, name=name, subsystem=sub, controller=ctrl, kind=kind, unit=unit, lo=lo, hi=hi,
                         rate_limit=rate, tau=tau)
            a.params = {"rate_limit": rate, "tau": tau}
            a.auth_state = "unauthenticated (field bus)"
            self.registry.add(a)
            self.actuators[aid] = a
        self.t = 0.0
        self.physical: dict[str, float] = {}
        self._init_steady_state()
        self._refresh_state()

    def _init_steady_state(self) -> None:
        out = self.boiler.init_steady_state(DESIGN["TIC-101.SP"], DESIGN["TIC-201.SP"], DESIGN["P-101.SP"],
                                            DESIGN["FCV-101.SP"], DESIGN["P-201.SP"], load_profile(0.0))
        init = {
            "HTR-101": out["heater_pct"], "P-101": DESIGN["P-101.SP"], "FCV-101": DESIGN["FCV-101.SP"],
            "P-201": DESIGN["P-201.SP"], "FAN-201": out["fan_pct"], "P-301": 55.0, "P-302": 25.0,
            "XV-301": 100.0, "XV-303": 0.0, "XV-401": 0.0, "XV-402": 0.0, "XV-403": 0.0, "M-401": 0.0,
            "TCV-401": 0.0, "P-501": 70.0, "XV-501": 100.0, "XV-502": 0.0,
        }
        for aid, v in init.items():
            a = self.actuators[aid]
            a.command = a.output = a.feedback = v
        self.pipeline.motor.speed = self.pipeline.motor.rated_rpm * 0.70
        self.design_outputs = out

    def step(self, dt: float) -> None:
        for a in self.actuators.values():
            a.step(dt)
        A = self.actuators
        self.t += dt
        self.boiler.step(dt, A["HTR-101"].output, A["P-101"].output, A["FCV-101"].output, A["P-201"].output,
                         A["FAN-201"].output, load_profile(self.t))
        self.water.step(dt, A["P-301"].output, A["P-302"].output, A["XV-301"].output, A["XV-303"].output)
        self.mixing.step(dt, A["XV-401"].output, A["XV-402"].output, A["XV-403"].output, A["M-401"].output,
                         A["TCV-401"].output)
        self.pipeline.step(dt, A["P-501"].output, A["XV-501"].output, A["XV-502"].output)
        self._refresh_state()

    def _refresh_state(self) -> None:
        st = self.boiler.state()
        st.update(self.water.state())
        st.update(self.mixing.state())
        st.update(self.pipeline.state())
        self.physical = st

    def field_devices_by_controller(self) -> dict[str, list[tuple[str, str]]]:
        out: dict[str, list[tuple[str, str]]] = {}
        for s in self.sensors.values():
            out.setdefault(s.controller, []).append((s.id, "sensor"))
        for a in self.actuators.values():
            out.setdefault(a.controller, []).append((a.id, "actuator"))
        return out
