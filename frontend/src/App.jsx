import { useEffect, useState } from "react";
import { api } from "./api.js";

const OPTIONS = ["allow", "review", "block"];
const pct = (p) => (p == null ? "—" : `${(p * 100).toFixed(1)}%`);

function DecisionBadge({ decision, large }) {
  if (!decision) return <span className="badge muted">n/a</span>;
  return <span className={`badge ${decision} ${large ? "large" : ""}`}>{decision.toUpperCase()}</span>;
}

function ProbabilityBars({ probabilities, top }) {
  return (
    <div className="bars">
      {OPTIONS.map((opt) => {
        const p = probabilities?.[opt];
        return (
          <div key={opt} className={`bar ${opt === top ? "top" : ""}`}>
            <span className="bar-name">{opt}</span>
            <span className="track">
              <span className={`fill ${opt}`} style={{ width: `${(p ?? 0) * 100}%` }} />
            </span>
            <span className="bar-pct">{pct(p)}</span>
          </div>
        );
      })}
    </div>
  );
}

function ModelCard({ result }) {
  const { kev, threshold } = result;
  const statusLabel = {
    ok: "Live Kev prediction",
    simulated: "SIMULATED faulty prediction (demo mode)",
    unavailable: "Kev unavailable",
    error: "Kev call failed",
  }[kev.status];
  return (
    <div className="card">
      <div className="card-head">
        <h3>Kev recommendation</h3>
        <span className={`pill ${kev.status}`}>{statusLabel}</span>
      </div>
      {kev.recommendation ? (
        <>
          <div className="row">
            <DecisionBadge decision={kev.recommendation} large />
            <div className="meta">
              <div>
                Confidence <b>{pct(kev.confidence)}</b> vs threshold <b>{pct(threshold)}</b>
              </div>
              <div className={kev.confidence >= threshold ? "ok-text" : "warn-text"}>
                {kev.confidence >= threshold ? "Meets confidence threshold" : "Below threshold → human review"}
              </div>
              {kev.latency_ms != null && <div className="muted">Latency {Math.round(kev.latency_ms)} ms</div>}
            </div>
          </div>
          <ProbabilityBars probabilities={kev.probabilities} top={kev.recommendation} />
        </>
      ) : (
        <p className="warn-text">{kev.error || "No prediction available"}. Falling back to human review.</p>
      )}
      <p className="fine">A model probability is a signal, not proof of safety.</p>
    </div>
  );
}

function FinalCard({ result }) {
  const { final_decision, deciding_rule, applied_rules, overridden_model } = result;
  return (
    <div className={`card final ${final_decision}`}>
      <div className="card-head">
        <h3>Final safety decision</h3>
        <span className="pill">Simulated · not executed</span>
      </div>
      <div className="row">
        <DecisionBadge decision={final_decision} large />
        <div className="meta">
          <div>
            Decided by <b>{deciding_rule.rule_id}</b> — {deciding_rule.name}
          </div>
          <div className="muted">{deciding_rule.reason}</div>
          {overridden_model && <div className="warn-text">Safety layer overrode Kev's recommendation.</div>}
        </div>
      </div>
      <h4>Rules evaluated</h4>
      <ul className="rules">
        {applied_rules.map((r) => (
          <li key={r.rule_id} className={r.rule_id === deciding_rule.rule_id ? "deciding" : ""}>
            <span className="rule-id">{r.rule_id}</span>
            <span className="rule-name">
              {r.name}
              <small>{r.source.replace("_", " ")}</small>
            </span>
            <DecisionBadge decision={r.decision} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function AuditTable({ entries, onClear }) {
  return (
    <section className="card">
      <div className="card-head">
        <h3>Audit history ({entries.length})</h3>
        <button className="ghost" onClick={onClear} disabled={!entries.length}>
          Clear
        </button>
      </div>
      {entries.length === 0 ? (
        <p className="muted">No actions evaluated yet. History is in-memory and resets when the backend restarts.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Action</th>
                <th>Kev</th>
                <th>Confidence</th>
                <th>Final</th>
                <th>Rule</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id}>
                  <td className="nowrap">{new Date(e.timestamp).toLocaleTimeString()}</td>
                  <td className="action-cell" title={e.action}>
                    {e.simulated_faulty_kev && <span className="pill simulated">demo</span>} {e.action.split("\n")[0]}
                  </td>
                  <td>{e.kev.recommendation ? <DecisionBadge decision={e.kev.recommendation} /> : <span className="muted">{e.kev.status}</span>}</td>
                  <td>{pct(e.kev.confidence)}</td>
                  <td>
                    <DecisionBadge decision={e.final_decision} />
                  </td>
                  <td className="nowrap">
                    {e.deciding_rule.rule_id} · {e.deciding_rule.name}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default function App() {
  const [health, setHealth] = useState(null);
  const [scenarios, setScenarios] = useState([]);
  const [selected, setSelected] = useState(null);
  const [action, setAction] = useState("");
  const [threshold, setThreshold] = useState(0.8);
  const [demoMode, setDemoMode] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [audit, setAudit] = useState([]);

  const refreshAudit = () => api.audit().then(setAudit).catch(() => {});

  useEffect(() => {
    api
      .health()
      .then((h) => {
        setHealth(h);
        setThreshold(h.default_threshold);
      })
      .catch(() => setHealth({ status: "down" }));
    api.scenarios().then(setScenarios).catch(() => {});
    refreshAudit();
  }, []);

  const pickScenario = (s) => {
    setSelected(s.id);
    setAction(s.action);
    setResult(null);
  };

  const evaluate = async () => {
    setLoading(true);
    setError("");
    try {
      const r = await api.evaluate({ action, threshold, simulate_faulty_kev: demoMode });
      setResult(r);
      refreshAudit();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const clearAudit = async () => {
    await api.clearAudit();
    refreshAudit();
  };

  return (
    <div className="app">
      <header>
        <div className="brand">
          <span className="logo">AG</span>
          <div>
            <h1>AgentGuard</h1>
            <span className="tag">AI Agent Safety Gate · powered by Kev</span>
          </div>
        </div>
        <div className="status">
          {health == null ? (
            <span className="pill">Connecting…</span>
          ) : health.status !== "ok" ? (
            <span className="pill error">Backend offline</span>
          ) : health.kev_configured ? (
            <span className="pill ok">Kev connected · {health.kev_model}</span>
          ) : (
            <span className="pill unavailable">No KEV_DEMO_KEY · all actions go to review</span>
          )}
        </div>
      </header>

      <main>
        <section className="card">
          <h3>Proposed agent action</h3>
          <p className="muted">
            Describe the action, its environment, authorization, and potential consequences. Nothing is ever executed — all actions are simulated.
          </p>
          <div className="scenarios">
            {scenarios.map((s) => (
              <button key={s.id} className={`scenario ${selected === s.id ? "active" : ""}`} onClick={() => pickScenario(s)}>
                <span className={`risk ${s.risk}`}>{s.risk}</span>
                {s.title}
              </button>
            ))}
          </div>
          <textarea
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setSelected(null);
            }}
            placeholder={"Action: ...\nEnvironment: ...\nAuthorization: ...\nPotential consequences: ..."}
            rows={8}
          />
          <div className="controls">
            <label className="threshold">
              Confidence threshold <b>{Math.round(threshold * 100)}%</b>
              <input type="range" min="0.5" max="0.99" step="0.01" value={threshold} onChange={(e) => setThreshold(Number(e.target.value))} />
            </label>
            <label className="toggle" title="Skip the real Kev call and pretend Kev confidently recommends ALLOW">
              <input type="checkbox" checked={demoMode} onChange={(e) => setDemoMode(e.target.checked)} />
              Demo mode: simulate Kev wrongly recommending <b>allow</b>
            </label>
            <button className="primary" onClick={evaluate} disabled={loading || !action.trim()}>
              {loading ? "Evaluating…" : "Evaluate action"}
            </button>
          </div>
          {loading && !demoMode && <p className="muted">First Kev call after idle can take 3–4 minutes while a GPU wakes up.</p>}
          {error && <p className="error-text">{error}</p>}
        </section>

        {result && (
          <section className="results">
            <ModelCard result={result} />
            <FinalCard result={result} />
          </section>
        )}

        <AuditTable entries={audit} onClear={clearAudit} />
      </main>
    </div>
  );
}
