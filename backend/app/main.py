"""AgentGuard API. All actions are simulated: nothing evaluated here is ever executed."""

import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .audit import AuditLog
from .config import Settings, get_settings
from .decision import decide
from .kev_client import KevClient, KevResult, simulated_faulty_result
from .scenarios import SCENARIOS

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="AgentGuard", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

audit_log = AuditLog()


def get_kev_client(settings: Settings = Depends(get_settings)) -> KevClient:
    return KevClient(settings)


class EvaluateRequest(BaseModel):
    action: str = Field(min_length=1, max_length=5000)
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    simulate_faulty_kev: bool = False


def _kev_view(kev: KevResult) -> dict:
    return {
        "status": kev.status,
        "recommendation": kev.recommendation,
        "probabilities": kev.probabilities,
        "confidence": kev.confidence,
        "latency_ms": kev.latency_ms,
        "error": kev.error,
    }


@app.get("/api/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "status": "ok",
        "kev_configured": settings.kev_configured,
        "kev_model": settings.kev_model,
        "default_threshold": settings.confidence_threshold,
    }


@app.get("/api/scenarios")
def scenarios() -> list[dict]:
    return SCENARIOS


@app.post("/api/evaluate")
async def evaluate(
    req: EvaluateRequest,
    settings: Settings = Depends(get_settings),
    kev_client: KevClient = Depends(get_kev_client),
) -> dict:
    action = req.action.strip()
    threshold = req.threshold if req.threshold is not None else settings.confidence_threshold

    kev = simulated_faulty_result() if req.simulate_faulty_kev else await kev_client.evaluate(action)
    decision = decide(action, kev, threshold)

    record = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "threshold": threshold,
        "simulated_faulty_kev": req.simulate_faulty_kev,
        "kev": _kev_view(kev),
        "final_decision": decision.final_decision,
        "deciding_rule": asdict(decision.deciding_rule),
        "applied_rules": [asdict(r) for r in decision.applied_rules],
        "model_gate_decision": decision.model_gate_decision,
        "overridden_model": decision.overridden_model,
        "executed": False,
    }
    audit_log.add(record)
    return record


@app.get("/api/audit")
def get_audit() -> list[dict]:
    return audit_log.list()


@app.delete("/api/audit")
def clear_audit() -> dict:
    audit_log.clear()
    return {"cleared": True}
