const BASE = "";

async function j<T>(url: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(BASE + url, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch { /* ignore */ }
    throw new Error(`${r.status}: ${detail}`);
  }
  return r.json() as Promise<T>;
}

const post = (url: string, body?: unknown) =>
  j(url, { method: "POST", body: JSON.stringify(body ?? {}) });

export const api = {
  health: () => j<any>("/api/health"),
  meta: () => j<any>("/api/meta"),
  plantState: () => j<any>("/api/plant/state"),
  devices: () => j<any>("/api/devices"),
  device: (id: string) => j<any>(`/api/devices/${id}`),
  charts: (keys: string[], points = 600) =>
    j<any>(`/api/charts?keys=${keys.join(",")}&points=${points}`),
  topology: () => j<any>("/api/network/topology"),
  traffic: (limit = 120) => j<any>(`/api/network/traffic?limit=${limit}`),
  twin: () => j<any>("/api/twin/state"),
  alerts: (activeOnly = false, limit = 200) =>
    j<any>(`/api/ids/alerts?active_only=${activeOnly}&limit=${limit}`),
  incidents: () => j<any>("/api/ids/incidents"),
  toggleLayers: (layers: Record<string, boolean>) => post("/api/ids/layers", layers),
  ackIncident: (incident_id: string) => post("/api/ids/ack", { incident_id }),
  watermark: () => j<any>("/api/watermarking/state"),
  wmEnable: () => post("/api/watermarking/enable"),
  wmDisable: () => post("/api/watermarking/disable"),
  wmConfig: (cfg: Record<string, unknown>) => post("/api/watermarking/config", cfg),
  simStart: () => post("/api/simulation/start"),
  simPause: () => post("/api/simulation/pause"),
  simSpeed: (speed: number) => post("/api/simulation/speed", { speed }),
  simReset: (seed?: number) => post("/api/simulation/reset", { seed }),
  esd: () => post("/api/simulation/esd"),
  esdReset: () => post("/api/simulation/esd/reset"),
  maintenance: (enabled: boolean) => post("/api/simulation/maintenance", { enabled }),
  setpoint: (plc: string, register: string, value: number, user = "operator1") =>
    post("/api/control/setpoint", { plc, register, value, user }),
  attacks: () => j<any>("/api/attacks"),
  attackStart: (scenario: string, params: Record<string, unknown> = {}) =>
    post("/api/attacks/start", { scenario, params }),
  attackStop: (scenario: string) => post("/api/attacks/stop", { scenario }),
  attackStopAll: () => post("/api/attacks/stop_all"),
  response: () => j<any>("/api/response"),
  responseMode: (mode: string) => post("/api/response/mode", { mode }),
  approve: (response_id: string, approve = true, operator = "operator1") =>
    post("/api/response/approve", { response_id, approve, operator }),
  experiments: () => j<any>("/api/experiments"),
  experiment: (id: string) => j<any>(`/api/experiments/${id}`),
  runExperiment: (cfg: Record<string, unknown>) => post("/api/experiments/run", cfg),
  events: (limit = 200) => j<any>(`/api/events?limit=${limit}`),
  exportUrl: (kind: string) => `${BASE}/api/export/${kind}`,
};
