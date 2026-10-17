"""Deterministic safety rules that run independently of Kev.

Rules only ever make a decision *more* restrictive. They are keyword based on
purpose: predictable and auditable, and biased towards false positives (extra
human review) rather than false negatives.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    name: str
    decision: str  # "review" | "block"
    reason: str


def _rx(*patterns: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)


PRODUCTION = _rx(r"\bprod(uction)?\b", r"\bprod[-_]\w+", r"\w+[-_]prod\b", r"\blive (environment|system|database|db)\b")
DATABASE = _rx(
    r"\bdata ?base\b", r"\bdb\b", r"\w+[-_]db\b", r"\bdb[-_]\w+", r"\btables?\b", r"\bschema\b",
    r"\bpostgres(ql)?\b", r"\bmysql\b", r"\bmongo(db)?\b", r"\bredis\b", r"\bdynamo(db)?\b",
    r"\bsql\b", r"\brds\b", r"\bcollections?\b",
)
DELETION = _rx(
    r"\bdelet(e|es|ed|ing|ion)\b", r"\bdrop(s|ped|ping)?\b", r"\btruncat(e|es|ed|ing)\b",
    r"\bwip(e|es|ed|ing)\b", r"\bpurg(e|es|ed|ing)\b", r"\bdestroy(s|ed|ing)?\b", r"\berase[sd]?\b",
    r"\bflushall\b", r"\bflushdb\b",
)
DESTRUCTIVE = _rx(
    DELETION.pattern, r"\brm\s+-\w*[rf]", r"\boverwrit(e|es|ing|ten)\b", r"\bforce[- ]push\b",
    r"\bpush\s+(--force|-f)\b", r"\bterminat(e|es|ed|ing)\b", r"\bshut ?down\b", r"\bkill\b",
    r"\breset\s+--hard\b", r"\bdecommission\b", r"\brevok(e|es|ed|ing)\b", r"\bformat\b",
)
PRIVILEGED = _rx(
    r"\bsudo\b", r"\broot\b", r"\badmin(istrator)?\b", r"\bprivileg(e|ed|es)\b", r"\biam\b",
    r"\bpermissions?\b", r"\bcredentials?\b", r"\bsecrets?\b", r"\bapi keys?\b", r"\bfirewall\b",
    r"\bconfig(uration)?s?\b", r"\bmodif(y|ies|ied|ying)\b", r"\bchang(e|es|ed|ing)\b",
    r"\bupdat(e|es|ed|ing)\b", r"\bdeploy(s|ed|ing|ment)?\b", r"\bmigrat(e|es|ed|ion|ions)\b",
    r"\brestart(s|ed|ing)?\b", r"\benvironment variables?\b", r"\bfeature flags?\b",
    r"\bscal(e|es|ed|ing)\b", r"\bwrite access\b", r"\bgrant(s|ed|ing)?\b", r"\bdns\b",
)
NEGATED_AUTH = _rx(
    r"\bun(authori[sz]ed|approved)\b",
    r"\b(no|not|without|lacks?|lacking|missing|never|nobody|no one|none)\b[^.\n]{0,60}"
    r"\b(authori[sz]\w*|approv\w*|tickets?|sign[- ]?off|permission)\b",
    r"\bauthori[sz]ation:\s*(none|no|n/a)\b",
)
POSITIVE_AUTH = _rx(
    r"\bauthori[sz]ed\b", r"\bapproved\b", r"\bchange (ticket|request)\b", r"\bsigned[- ]off\b",
)


def is_explicitly_authorized(text: str) -> bool:
    """True only when the text claims authorization and never negates it."""
    return bool(POSITIVE_AUTH.search(text)) and not NEGATED_AUTH.search(text)


def evaluate_rules(text: str) -> list[RuleHit]:
    hits: list[RuleHit] = []
    in_prod = bool(PRODUCTION.search(text))
    if not in_prod:
        return hits

    destructive = bool(DESTRUCTIVE.search(text))
    if DATABASE.search(text) and DELETION.search(text) and not is_explicitly_authorized(text):
        hits.append(
            RuleHit(
                rule_id="R1",
                name="Unauthorized production database deletion",
                decision="block",
                reason="Deletes production data without explicit, un-negated authorization.",
            )
        )
    if destructive:
        hits.append(
            RuleHit(
                rule_id="R2",
                name="Destructive production operation",
                decision="review",
                reason="Destructive operations in production always require human review.",
            )
        )
    if PRIVILEGED.search(text):
        hits.append(
            RuleHit(
                rule_id="R3",
                name="Privileged production operation",
                decision="review",
                reason="Privileged or configuration-changing production operations require human review.",
            )
        )
    return hits
