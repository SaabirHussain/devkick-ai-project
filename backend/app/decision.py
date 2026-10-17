"""Combines Kev's prediction with the deterministic safety rules.

Order of precedence (most restrictive wins):
1. Deterministic safety rules (can only escalate, never relax).
2. Fail-safe: Kev missing/failed -> human review.
3. Confidence gate: Kev confidence below threshold -> human review.
4. Kev's recommendation.
"""

from dataclasses import dataclass

from .kev_client import KevResult
from .safety_rules import RuleHit, evaluate_rules

SEVERITY = {"allow": 0, "review": 1, "block": 2}


@dataclass
class AppliedRule:
    rule_id: str
    name: str
    decision: str
    reason: str
    source: str  # "safety_rule" | "fail_safe" | "confidence_gate" | "model"


@dataclass
class Decision:
    final_decision: str
    deciding_rule: AppliedRule
    applied_rules: list[AppliedRule]
    model_gate_decision: str
    overridden_model: bool


def _rule(hit: RuleHit) -> AppliedRule:
    return AppliedRule(hit.rule_id, hit.name, hit.decision, hit.reason, "safety_rule")


def decide(action: str, kev: KevResult, threshold: float) -> Decision:
    if not kev.usable:
        gate = AppliedRule(
            "F1",
            "Kev unavailable: fail-safe review",
            "review",
            f"No usable model prediction ({kev.error or kev.status}); never auto-approve.",
            "fail_safe",
        )
    elif kev.confidence is None or kev.confidence < threshold:
        gate = AppliedRule(
            "C1",
            "Low confidence: human review",
            "review",
            f"Kev confidence {kev.confidence or 0:.0%} is below the {threshold:.0%} threshold.",
            "confidence_gate",
        )
    else:
        gate = AppliedRule(
            "M1",
            f"Kev recommendation: {kev.recommendation}",
            kev.recommendation,
            f"Kev confidence {kev.confidence:.0%} meets the {threshold:.0%} threshold.",
            "model",
        )

    safety = [_rule(h) for h in evaluate_rules(action)]
    applied = [gate, *safety]

    # Safety rules are listed first so they win ties against the model.
    deciding = max([*safety, gate], key=lambda r: SEVERITY[r.decision])
    model_said = kev.recommendation if kev.usable else None
    overridden = model_said is not None and SEVERITY[deciding.decision] > SEVERITY[model_said]

    return Decision(
        final_decision=deciding.decision,
        deciding_rule=deciding,
        applied_rules=applied,
        model_gate_decision=gate.decision,
        overridden_model=overridden,
    )
