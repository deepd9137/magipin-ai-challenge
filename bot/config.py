from __future__ import annotations

import os
from datetime import datetime
from typing import List

from dotenv import load_dotenv

load_dotenv()


def _list(val: str) -> List[str]:
    return [v.strip() for v in val.split(",") if v.strip()]


class _Settings:
    team_name: str
    team_members: List[str]
    version: str
    llm_provider: str
    llm_api_key: str
    llm_model: str
    nvidia_key: str
    nvidia_model: str
    model: str

    def __init__(self) -> None:
        self.team_name = os.environ.get("TEAM_NAME", "Vera AI")
        self.team_members = _list(os.environ.get("TEAM_MEMBERS", "Deepanshu Pofare"))
        self.version = os.environ.get("VERSION", "2.0.0")

        self.llm_provider = os.environ.get("LLM_PROVIDER", "")
        self.llm_api_key = os.environ.get("LLM_API_KEY", "")
        self.llm_model = os.environ.get("LLM_MODEL", "")

        # NVIDIA NIM fallback
        self.nvidia_key = os.environ.get("NVIDIA_API_KEY", "")
        self.nvidia_model = os.environ.get("NVIDIA_MODEL", "openai/gpt-oss-20b")

        # Auto-detect primary provider from known key env vars
        if not self.llm_provider:
            if os.environ.get("ANTHROPIC_API_KEY"):
                self.llm_provider = "anthropic"
            elif os.environ.get("GEMINI_API_KEY"):
                self.llm_provider = "gemini"
            elif os.environ.get("OPENAI_API_KEY"):
                self.llm_provider = "openai"
            elif self.nvidia_key:
                self.llm_provider = "nvidia"
            else:
                self.llm_provider = "anthropic"

        # Resolve API key from provider-specific env vars if not set directly
        if not self.llm_api_key:
            key_map = {
                "anthropic": "ANTHROPIC_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "openai": "OPENAI_API_KEY",
                "nvidia": "NVIDIA_API_KEY",
            }
            env_var = key_map.get(self.llm_provider, "")
            self.llm_api_key = os.environ.get(env_var, "")

        # Default model per provider
        if not self.llm_model:
            defaults = {
                "anthropic": "claude-sonnet-4-6",
                "gemini": "gemini-2.0-flash",
                "openai": "gpt-4o-mini",
                "nvidia": self.nvidia_model,
            }
            self.llm_model = defaults.get(self.llm_provider, "unknown")

        self.model = f"{self.llm_provider}:{self.llm_model}"

    def metadata_dict(self) -> dict:
        return {
            "team_name": self.team_name,
            "team_members": self.team_members,
            "model": self.model,
            "approach": (
                "4-layer context composition (category+merchant+trigger+customer) "
                "via LLM with anti-fabrication validation and suppression dedup"
            ),
            "contact_email": "deepd9137@gmail.com",
            "version": self.version,
            "submitted_at": datetime.utcnow().isoformat() + "Z",
        }


settings = _Settings()
