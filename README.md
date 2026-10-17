# AgentGuard — AI Agent Safety Gate

AI decision-making application built at DevKick 004 using Kev and Devin.

AgentGuard evaluates a **proposed AI-agent action** before it is allowed to proceed. It asks
[Kev](https://yohann-60613--kev-demo.modal.run) (`kev-9b`) to choose between `allow`, `review`
and `block`, then runs that prediction through a confidence gate and an independent set of
deterministic safety rules. The most restrictive outcome wins.

> **All actions are simulated.** AgentGuard never executes shell commands, database operations,
> deployments or any other action. It only returns a decision.

## How a decision is made

| Step | Rule | Outcome |
| --- | --- | --- |
| 1 | `F1` Fail-safe | Missing `KEV_DEMO_KEY`, network errors, timeouts, non-200 responses or malformed responses → **review** (never allow) |
| 2 | `C1` Confidence gate | Kev's confidence below the threshold (default 80%) → **review** |
| 3 | `M1` Model | Otherwise Kev's recommendation is used as the model gate decision |
| 4 | `R1` Unauthorized production DB deletion | Production + database + delete/drop/truncate/wipe without explicit, non-negated authorization → **block** |
| 4 | `R2` Destructive production operation | Production + destructive verb (delete, drop, rm -rf, force push, terminate, …) → **review** |
| 4 | `R3` Privileged production operation | Production + privileged/config change (config, deploy, IAM, secrets, sudo, restart, …) → **review** |

Safety rules (`R*`) can only make a decision stricter; Kev can never relax them. If Kev says
`block`, that is respected too. A model probability is treated as a signal, not proof of safety.

**Demo mode** skips the real Kev call and simulates Kev confidently (96%) recommending `allow`.
Run it on the "Delete the production database" scenario to see `R1` block the action anyway.

## Project layout

```
backend/
  app/main.py          FastAPI app: /api/health, /api/scenarios, /api/evaluate, /api/audit
  app/kev_client.py    Kev System One request/response handling (choice question, parsing)
  app/safety_rules.py  Deterministic, keyword-based safety rules (R1–R3)
  app/decision.py      Combines fail-safe, confidence gate, Kev and safety rules
  app/audit.py         Thread-safe in-memory audit history (resets on restart)
  app/scenarios.py     The three demo scenarios
  app/config.py        Environment-based settings
  tests/               Pytest suite (Kev is mocked; no network or key needed)
frontend/
  src/App.jsx          Dashboard: scenarios, action input, threshold, demo mode, results, audit
  src/api.js           Tiny fetch wrapper for the backend
  vite.config.js       Dev server on :5173, proxies /api to the backend on :8000
```

## Run locally

Prerequisites: Python 3.10+, Node.js 18+.

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example .env        # then put your real key in backend/.env
uvicorn app.main:app --reload --port 8000
```

Without `KEV_DEMO_KEY` the app still runs, but every action falls back to human review.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

### 3. Tests

```bash
cd backend
pytest -q
```

## API

`POST /api/evaluate`

```json
{ "action": "Action: ...\nEnvironment: ...\nAuthorization: ...\nPotential consequences: ...",
  "threshold": 0.8, "simulate_faulty_kev": false }
```

Returns Kev's status, recommendation, probabilities for all three options and confidence, plus the
`final_decision`, the `deciding_rule`, every `applied_rules` entry, and `executed: false`.

`GET /api/audit` returns the in-memory history (newest first); `DELETE /api/audit` clears it.

## Kev integration

The backend sends:

```json
{
  "model": "kev-9b",
  "state": "Proposed AI-agent action submitted for a safety decision: ...",
  "questions": {
    "decision": { "type": "choice", "instructions": "...",
                  "criteria": { "allow": "...", "review": "...", "block": "..." } }
  }
}
```

to `POST {KEV_BASE_URL}/v1/systemone` with `Authorization: Bearer $KEV_DEMO_KEY`, and reads
`answers.decision.choice`, `answers.decision.probabilities` and `answers.decision.confidence`
(the format used by the Kev playground). Any deviation from that format is treated as an error → review.
The key is read only from the environment and is never logged or returned by the API.

## Limitations

- Safety rules are keyword based: easy to audit, but they can over-escalate and can be evaded by
  creative wording. They are a backstop, not a complete policy engine.
- Audit history is in memory only.
- The first Kev call after an idle period can take 3–4 minutes while the GPU wakes up.
