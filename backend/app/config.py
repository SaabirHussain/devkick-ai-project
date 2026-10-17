import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DEFAULT_KEV_BASE_URL = "https://yohann-60613--kev-demo.modal.run"


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    kev_api_key: str | None
    kev_base_url: str
    kev_model: str
    kev_timeout_seconds: float
    confidence_threshold: float

    @property
    def kev_configured(self) -> bool:
        return bool(self.kev_api_key)


def get_settings() -> Settings:
    threshold = _float_env("CONFIDENCE_THRESHOLD", 0.8)
    return Settings(
        kev_api_key=(os.getenv("KEV_DEMO_KEY") or "").strip() or None,
        kev_base_url=os.getenv("KEV_BASE_URL", DEFAULT_KEV_BASE_URL).rstrip("/"),
        kev_model=os.getenv("KEV_MODEL", "kev-9b"),
        kev_timeout_seconds=_float_env("KEV_TIMEOUT_SECONDS", 300.0),
        confidence_threshold=min(max(threshold, 0.0), 1.0),
    )
