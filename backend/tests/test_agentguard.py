import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.kev_client import KevClient, build_request, parse_response
from app.main import app, audit_log, get_kev_client
from app.safety_rules import evaluate_rules, is_explicitly_authorized
from app.scenarios import SCENARIOS

FAKE_KEY = "test-secret-key-do-not-log"
SCENARIO = {s["id"]: s["action"] for s in SCENARIOS}


def settings(key: str | None = FAKE_KEY) -> Settings:
    return Settings(
        kev_api_key=key,
        kev_base_url="https://kev.test",
        kev_model="kev-9b",
        kev_timeout_seconds=5,
        confidence_threshold=0.8,
    )


def kev_answer(choice: str, probs: dict[str, float]) -> dict:
    return {"answers": {"decision": {"type": "choice", "choice": choice, "probabilities": probs, "confidence": max(probs.values())}}, "latency_ms": 42}


def make_client(handler=None, key: str | None = FAKE_KEY) -> TestClient:
    s = settings(key)
    transport = httpx.MockTransport(handler) if handler else None
    app.dependency_overrides[get_settings] = lambda: s
    app.dependency_overrides[get_kev_client] = lambda: KevClient(s, transport=transport)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset():
    audit_log.clear()
    yield
    app.dependency_overrides.clear()


def responder(choice, probs, captured=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return httpx.Response(200, json=kev_answer(choice, probs))
    return handler


# ---------- Kev request / response ----------

def test_request_shape_and_auth_header():
    captured = []
    client = make_client(responder("allow", {"allow": 0.9, "review": 0.08, "block": 0.02}, captured))
    client.post("/api/evaluate", json={"action": SCENARIO["read-readme"]})
    req = captured[0]
    assert req.url.path == "/v1/systemone"
    assert req.headers["authorization"] == f"Bearer {FAKE_KEY}"
    body = json.loads(req.content)
    assert body["model"] == "kev-9b"
    assert SCENARIO["read-readme"] in body["state"]
    q = body["questions"]["decision"]
    assert q["type"] == "choice"
    assert set(q["criteria"]) == {"allow", "review", "block"}


def test_build_request_has_three_options():
    assert set(build_request("x", "kev-9b")["questions"]["decision"]["criteria"]) == {"allow", "review", "block"}


@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"answers": {}}, {"answers": {"decision": {"choice": "allow"}}},
     {"answers": {"decision": {"choice": "maybe", "probabilities": {"allow": 0.5, "review": 0.3, "block": 0.2}}}},
     {"answers": {"decision": {"choice": "allow", "probabilities": {"allow": 0.9}}}}],
)
def test_malformed_responses_are_errors(payload):
    assert parse_response(payload).status == "error"


def test_confidence_falls_back_to_max_probability():
    r = parse_response({"answers": {"decision": {"choice": "review", "probabilities": {"allow": 0.1, "review": 0.7, "block": 0.2}}}})
    assert r.status == "ok" and r.confidence == pytest.approx(0.7)


# ---------- Decisions ----------

def test_safe_readme_high_confidence_is_allowed():
    client = make_client(responder("allow", {"allow": 0.93, "review": 0.05, "block": 0.02}))
    data = client.post("/api/evaluate", json={"action": SCENARIO["read-readme"]}).json()
    assert data["final_decision"] == "allow"
    assert data["kev"]["probabilities"] == {"allow": 0.93, "review": 0.05, "block": 0.02}
    assert data["deciding_rule"]["rule_id"] == "M1"
    assert data["executed"] is False


def test_low_confidence_requires_review():
    client = make_client(responder("allow", {"allow": 0.6, "review": 0.3, "block": 0.1}))
    data = client.post("/api/evaluate", json={"action": SCENARIO["read-readme"]}).json()
    assert data["final_decision"] == "review"
    assert data["deciding_rule"]["rule_id"] == "C1"


def test_custom_threshold_is_respected():
    client = make_client(responder("allow", {"allow": 0.6, "review": 0.3, "block": 0.1}))
    data = client.post("/api/evaluate", json={"action": SCENARIO["read-readme"], "threshold": 0.5}).json()
    assert data["final_decision"] == "allow"


def test_missing_key_requires_review_and_skips_network():
    def handler(request):
        raise AssertionError("must not call Kev without a key")
    client = make_client(handler, key=None)
    data = client.post("/api/evaluate", json={"action": SCENARIO["read-readme"]}).json()
    assert data["final_decision"] == "review"
    assert data["kev"]["status"] == "unavailable"
    assert data["deciding_rule"]["rule_id"] == "F1"


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(500, json={"detail": "boom"}),
        lambda r: httpx.Response(401, json={"detail": "bad key"}),
        lambda r: httpx.Response(200, text="not json"),
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")),
        lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")),
    ],
)
def test_api_failures_require_review(handler):
    client = make_client(handler)
    data = client.post("/api/evaluate", json={"action": SCENARIO["read-readme"]}).json()
    assert data["final_decision"] == "review"
    assert data["kev"]["status"] == "error"


def test_failures_never_allow_even_safe_actions():
    client = make_client(lambda r: httpx.Response(503), key=FAKE_KEY)
    for action in SCENARIO.values():
        assert client.post("/api/evaluate", json={"action": action}).json()["final_decision"] != "allow"


def test_confident_allow_cannot_bypass_prod_db_deletion_block():
    client = make_client(responder("allow", {"allow": 0.99, "review": 0.005, "block": 0.005}))
    data = client.post("/api/evaluate", json={"action": SCENARIO["delete-prod-db"]}).json()
    assert data["final_decision"] == "block"
    assert data["deciding_rule"]["rule_id"] == "R1"
    assert data["overridden_model"] is True


def test_confident_allow_on_prod_config_is_escalated():
    client = make_client(responder("allow", {"allow": 0.95, "review": 0.03, "block": 0.02}))
    data = client.post("/api/evaluate", json={"action": SCENARIO["modify-prod-config"]}).json()
    assert data["final_decision"] == "review"
    assert data["deciding_rule"]["source"] == "safety_rule"
    assert data["overridden_model"] is True


def test_model_block_is_respected():
    client = make_client(responder("block", {"allow": 0.02, "review": 0.08, "block": 0.9}))
    data = client.post("/api/evaluate", json={"action": SCENARIO["read-readme"]}).json()
    assert data["final_decision"] == "block"


def test_demo_mode_simulates_faulty_allow_without_calling_kev():
    def handler(request):
        raise AssertionError("demo mode must not call Kev")
    client = make_client(handler)
    data = client.post("/api/evaluate", json={"action": SCENARIO["delete-prod-db"], "simulate_faulty_kev": True}).json()
    assert data["kev"]["status"] == "simulated"
    assert data["kev"]["recommendation"] == "allow"
    assert data["final_decision"] == "block"
    assert data["overridden_model"] is True


def test_empty_action_rejected():
    client = make_client(responder("allow", {"allow": 1, "review": 0, "block": 0}))
    assert client.post("/api/evaluate", json={"action": ""}).status_code == 422


# ---------- Safety rules ----------

def test_rules_for_scenarios():
    assert evaluate_rules(SCENARIO["read-readme"]) == []
    assert {h.rule_id for h in evaluate_rules(SCENARIO["delete-prod-db"])} >= {"R1", "R2"}
    assert {h.rule_id for h in evaluate_rules(SCENARIO["modify-prod-config"])} == {"R3"}


@pytest.mark.parametrize(
    "text",
    [
        "Truncate the orders table in prod. Not authorized.",
        "Delete all rows from the production database without approval.",
        "drop the prod-db users collection",
        "wipe the production mongo database; this is unauthorized",
    ],
)
def test_unauthorized_prod_db_deletion_blocked(text):
    assert any(h.rule_id == "R1" and h.decision == "block" for h in evaluate_rules(text))


def test_authorized_prod_db_deletion_still_needs_review():
    hits = evaluate_rules("Delete the stale_sessions table in the production database. Approved via change ticket CHG-123.")
    assert {h.rule_id for h in hits} >= {"R2"}
    assert "R1" not in {h.rule_id for h in hits}


def test_negated_authorization_is_not_authorization():
    assert not is_explicitly_authorized("This is not authorized by anyone.")
    assert not is_explicitly_authorized("Unauthorized request")
    assert is_explicitly_authorized("Authorized by the on-call SRE")


def test_non_production_actions_have_no_rule_hits():
    assert evaluate_rules("Delete a temporary file in the local sandbox") == []


# ---------- Audit & misc ----------

def test_audit_history_records_and_clears():
    client = make_client(responder("allow", {"allow": 0.9, "review": 0.05, "block": 0.05}))
    client.post("/api/evaluate", json={"action": SCENARIO["read-readme"]})
    client.post("/api/evaluate", json={"action": SCENARIO["delete-prod-db"], "simulate_faulty_kev": True})
    history = client.get("/api/audit").json()
    assert len(history) == 2
    assert history[0]["simulated_faulty_kev"] is True  # newest first
    assert client.delete("/api/audit").status_code == 200
    assert client.get("/api/audit").json() == []


def test_health_does_not_expose_key():
    client = make_client(key=FAKE_KEY)
    resp = client.get("/api/health")
    assert resp.json()["kev_configured"] is True
    assert FAKE_KEY not in resp.text


def test_secret_never_logged_or_returned(caplog):
    caplog.set_level(logging.DEBUG)
    client = make_client(lambda r: httpx.Response(500))
    resp = client.post("/api/evaluate", json={"action": SCENARIO["read-readme"]})
    assert FAKE_KEY not in resp.text
    assert FAKE_KEY not in caplog.text
    assert FAKE_KEY not in json.dumps(client.get("/api/audit").json())
