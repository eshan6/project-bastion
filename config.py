"""
Bastion configuration.

All config is env-driven. .env at repo root, loaded by python-dotenv.
Secrets never land in code or in the catalogue SQL.

Required env vars:
    BASTION_DB_DSN          postgresql://user:pass@host:5432/bastion
    BASTION_BLOB_ROOT       /var/lib/bastion/blobs   (or s3://... later)

Optional:
    BASTION_USER_AGENT      override default UA
    BASTION_DEFAULT_TIMEOUT seconds, default 30
    BASTION_MAX_RETRIES     default 3
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    db_dsn: str
    blob_root: Path
    user_agent: str
    default_timeout: float
    max_retries: int

    @classmethod
    def from_env(cls) -> "Config":
        dsn = os.getenv("BASTION_DB_DSN")
        if not dsn:
            raise RuntimeError(
                "BASTION_DB_DSN is unset. Set it in .env at the repo root."
            )
        blob_root = Path(os.getenv("BASTION_BLOB_ROOT", "/var/lib/bastion/blobs"))
        blob_root.mkdir(parents=True, exist_ok=True)
        return cls(
            db_dsn=dsn,
            blob_root=blob_root,
            user_agent=os.getenv(
                "BASTION_USER_AGENT",
                "BastionResearchBot/0.1 (+contact: ops@silverpot.in)",
            ),
            default_timeout=float(os.getenv("BASTION_DEFAULT_TIMEOUT", "30")),
            max_retries=int(os.getenv("BASTION_MAX_RETRIES", "3")),
        )


CONFIG: Config | None = None


def get_config() -> Config:
    global CONFIG
    if CONFIG is None:
        CONFIG = Config.from_env()
    return CONFIG
