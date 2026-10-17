async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    throw new Error(`${res.status}: ${detail}`);
  }
  return data;
}

export const api = {
  health: () => request("/api/health"),
  scenarios: () => request("/api/scenarios"),
  evaluate: (body) => request("/api/evaluate", { method: "POST", body: JSON.stringify(body) }),
  audit: () => request("/api/audit"),
  clearAudit: () => request("/api/audit", { method: "DELETE" }),
};
