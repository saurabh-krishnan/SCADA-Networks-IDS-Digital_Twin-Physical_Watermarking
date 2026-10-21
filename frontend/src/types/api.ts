export type Severity = "info" | "low" | "medium" | "high" | "critical";

export interface SensorView {
  name: string; subsystem: string; unit: string; value: number | null;
  quality: string; alarm: string; limits: Record<string, number | null>;
  range: [number, number]; suspicious: boolean;
}
export interface ActuatorView {
  name: string; kind: string; subsystem: string; unit: string;
  command: number; output: number; feedback: number; tripped: boolean; suspicious: boolean;
}
export interface PlantState {
  t: number; sim_t: number; running: boolean; speed: number; tick: number; mode: string;
  subsystems: Record<string, string>;
  sensors: Record<string, SensorView>;
  actuators: Record<string, ActuatorView>;
  physical_debug: Record<string, number>;
  safety: SafetyState;
  controllers: Record<string, { phase: Record<string, number>; rejected_writes: number; allowlist: boolean }>;
  batch_phase: number; load_demand_kw: number;
}
export interface SafetyState {
  tripped: boolean; manual_esd: boolean;
  latched: { rule: string; desc: string; value: number; limit: number }[];
  rules: { id: string; desc: string; limit: number; op: string; value: number; latched: boolean }[];
  history: any[]; independent: boolean;
}
export interface Alert {
  id: string; timestamp: number; last_seen: number; wall_time: string; asset: string;
  severity: Severity; category: string; source: string; rule: string; evidence: Record<string, any>;
  score: number | null; peak_score: number | null; confidence: number; recommendation: string;
  status: string; active: boolean; count: number; incident_id: string | null;
}
export interface Incident {
  id: string; created: number; updated: number; wall_time: string; zone: string; status: string;
  severity: Severity; classification: string; confidence: number; assets: string[]; layers: string[];
  rules: string[]; alert_ids: string[]; timeline: any[];
  recommendations: { action: string; target: string; reason: string }[];
  response_ids: string[]; resolved_at: number | null; acknowledged: boolean;
}
export interface TwinState {
  initialized: boolean; state: Record<string, number>; predictions: Record<string, number>;
  residuals: Record<string, ResidualView>; gated: Record<string, boolean>;
  confidence: number; health: string; sync_status: string; anomaly_score: number;
  inputs: Record<string, number>; forecast: any[]; params: Record<string, number>;
  config_log: any[]; resyncs: number; gate_z: number; tau_corr_s: number;
  independent_of_ground_truth: boolean;
}
export interface ResidualView {
  tag: string; observed: number | null; predicted: number | null; residual: number | null;
  z: number | null; sigma: number | null; bias: number | null; cusum: number | null;
  score: number | null; persistent: boolean; sudden: boolean; alarm_since: number | null;
  calibrating: boolean; valid: boolean;
}
export interface WatermarkState {
  enabled: boolean; injecting: boolean; suspended_reason: string | null; config: any;
  t_enabled: number | null; calibrating: boolean; calibrated_at: number | null;
  current_offset: number; decision: string; decision_reason: string; streak: number; alarm: boolean;
  channels: Record<string, any>; baseline: Record<string, any>; decisions: any[]; history: WmHist[];
}
export interface WmHist { t: number; offset: number; e_flow: number; o_flow: number; e_p: number; o_p: number; valid: boolean; }
export interface Snapshot {
  t: number; sim_t: number; running: boolean; speed: number; mode: string;
  sensors: Record<string, number>; actuators: Record<string, number>;
  alarms: { tag: string; level: string; value: number; since: number }[];
  twin: { confidence: number; health: string; sync: string; anomaly_score: number; residuals: Record<string, number | null> };
  watermark: { enabled: boolean; injecting: boolean; decision: string; alarm: boolean; offset: number };
  ids: { active_alerts: number; active_layers: string[]; open_incidents: number };
  incidents: Incident[];
  lab: { running: string[]; ground_truth: boolean };
  safety: { tripped: boolean; latched: string[] };
  response_mode: string; new_alerts: Alert[]; run_id: string;
}
export interface TopoNode { id: string; kind: string; label: string; ip: string; mac: string; zone: string; x: number; y: number; hidden: boolean; known: boolean; }
export interface TopoLink { id: string; a: string; b: string; medium: string; latency_ms: number; loss: number; extra_delay_ms: number; extra_loss: number; up: boolean; rate: Record<string, number>; suspicious: boolean; }
export interface Scenario {
  key: string; name: string; category: string; description: string; preconditions: string;
  target_assets: string[]; expected_evidence: string[]; default_params: Record<string, any>;
}
export interface ExperimentResult {
  run_id?: string; label: string; config: any; created: string; wall_time_s: number;
  sim_duration_s: number; samples: number; overall: Metrics;
  by_detector_config: Record<string, Metrics>; scenario: string | null; watermark: boolean;
  attack_window: [number, number]; final_incidents: Incident[]; responses: any[];
}
export interface Metrics {
  tp: number; fp: number; tn: number; fn: number; precision: number; recall: number; f1: number;
  detection_latency_s: number | null; windows: number; attack_windows: number;
  process_deviation_rms: number; process_deviation_max: number; recovery_time_s: number | null; detected: boolean;
}
