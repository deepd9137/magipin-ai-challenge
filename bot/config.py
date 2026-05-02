from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List


def _members() -> list[str]:
    raw = os.getenv("TEAM_MEMBERS", "Deepanshu")
    return [m.strip() for m in raw.split(",") if m.strip()]


@dataclass
class Settings:
    team_name: str = field(default_factory=lambda: os.getenv("TEAM_NAME", "Team Vera"))
    team_members: List[str] = field(default_factory=_members)
    model: str = field(default_factory=lambda: os.getenv("MODEL", "claude-sonnet-4-6"))
    approach: str = field(
        default_factory=lambda: os.getenv(
            "APPROACH",
            "4-layer context composition (category + merchant + trigger + customer) "
            "with per-trigger prompt framing, voice-pack enforcement, and anti-fabrication validation",
        )
    )
    contact_email: str = field(
        default_factory=lambda: os.getenv("CONTACT_EMAIL", "deepd9137@gmail.com")
    )
    version: str = field(default_factory=lambda: os.getenv("VERSION", "1.0.0"))
    submitted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )

    def metadata_dict(self) -> Dict[str, Any]:
        return {
            "team_name": self.team_name,
            "team_members": self.team_members,
            "model": self.model,
            "approach": self.approach,
            "contact_email": self.contact_email,
            "version": self.version,
            "submitted_at": self.submitted_at,
        }


settings = Settings()
