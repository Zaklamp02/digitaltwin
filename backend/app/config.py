"""Configuration — env-driven settings + credentials.yaml loader."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. Populated from environment variables and `.env`."""

    # LLM provider
    llm_provider: Literal["anthropic", "openai", "ollama"] = "anthropic"
    model_name: str = "claude-sonnet-4-6"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://host.docker.internal:11434"

    # Embeddings
    embedding_provider: Literal["openai", "local"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    local_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # RAG
    rag_top_k: int = 5
    rag_min_score: float = 0.35
    rag_context_turns: int = 3
    chunk_tokens: int = 300
    chunk_overlap: int = 50

    # Voice
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "alloy"
    stt_model: str = "whisper-1"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://localhost:4173"
    log_file: str = "./logs/requests.ndjson"

    # Paths
    memory_dir: str = "./memory"
    vault_dir: str = ""  # Obsidian vault path; if set, replaces memory_dir as source of truth
    chroma_dir: str = "./chroma_db"
    credentials_file: str = "./credentials.yaml"
    knowledge_db: str = "./data/knowledge.db"
    documents_dir: str = "./data/documents"

    # Rate limiting
    rate_limit_enabled: bool = True

    # Telegram notifications (optional — no-op if unset)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_public_bot_token: str = ""  # second bot for public-facing access

    # Microsoft Teams Outgoing Webhook (optional)
    teams_webhook_secret: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def memory_path(self) -> Path:
        """Source-of-truth content directory (vault if set, otherwise memory_dir)."""
        if self.vault_dir:
            return Path(self.vault_dir).resolve()
        return Path(self.memory_dir).resolve()

    @property
    def vault_path(self) -> Path | None:
        return Path(self.vault_dir).resolve() if self.vault_dir else None

    @property
    def chroma_path(self) -> Path:
        return Path(self.chroma_dir).resolve()

    @property
    def credentials_path(self) -> Path:
        return Path(self.credentials_file).resolve()

    @property
    def log_path(self) -> Path:
        return Path(self.log_file).resolve()

    @property
    def knowledge_db_path(self) -> Path:
        return Path(self.knowledge_db).resolve()

    @property
    def documents_path(self) -> Path:
        return Path(self.documents_dir).resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Memoised settings accessor."""
    return Settings()


# --- credentials.yaml loader -------------------------------------------------

Tier = Literal["public", "work", "friends", "personal"]

# Tier → default roles mapping (also handles legacy 'recruiter' tier).
_TIER_TO_ROLES: dict[str, list[str]] = {
    "public":    ["public"],
    "recruiter": ["public", "work"],          # legacy alias → work
    "work":      ["public", "work"],
    "friends":   ["public", "friends"],
    "personal":  ["public", "work", "friends", "personal"],
}


def load_tokens(path: Path) -> dict[str, dict]:
    """Load `credentials.yaml`. Returns {token: {tier, roles, label}}.

    Supports both formats:
      Old: {tier: "recruiter", label: "..."}
      New: {roles: ["public", "recruiter"], label: "..."}
    """
    if not path.exists():
        return {"": {"tier": "public", "roles": ["public"], "label": "anonymous (no credentials.yaml)"}}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    tokens: dict[str, dict] = {}
    for token, meta in (data.get("tokens") or {}).items():
        meta = meta or {}
        label = meta.get("label", "")
        if "roles" in meta:
            roles: list[str] = [str(r) for r in (meta["roles"] or ["public"])]
            # Derive tier for rate limiting
            if "personal" in roles:
                tier: Tier = "personal"
            elif "friends" in roles:
                tier = "friends"
            elif "work" in roles or "recruiter" in roles:
                tier = "work"
            else:
                tier = "public"
        else:
            # Old format: single tier string
            tier_raw = meta.get("tier", "public")
            # Map legacy 'recruiter' tier to 'work'
            if tier_raw == "recruiter":
                tier_raw = "work"
            tier = tier_raw if tier_raw in ("public", "work", "friends", "personal") else "public"  # type: ignore
            roles = _TIER_TO_ROLES.get(tier, ["public"])
        tokens[token or ""] = {"tier": tier, "roles": roles, "label": label}
    if "" not in tokens:
        tokens[""] = {"tier": "public", "roles": ["public"], "label": "anonymous (default)"}
    return tokens


def load_role_definitions(path: Path) -> list[dict]:
    """Load the top-level `roles:` list from credentials.yaml.
    Falls back to the three built-in roles if not defined."""
    builtin = [
        {"name": "public",   "description": "Anyone — QR code / public landing"},
        {"name": "work",     "description": "Colleagues & professional contacts"},
        {"name": "friends",  "description": "Social circle & close friends"},
        {"name": "personal", "description": "Just me — full access"},
    ]
    if not path.exists():
        return builtin
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    raw = data.get("roles")
    if not raw:
        return builtin
    return [{"name": str(r.get("name", "")), "description": str(r.get("description", ""))} for r in raw if r.get("name")]


def save_credentials(path: Path, data: dict) -> None:
    """Overwrite credentials.yaml atomically."""
    import tempfile
    tmp = path.with_suffix(".yaml.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    tmp.replace(path)


def accessible_tiers(tier: Tier) -> list[Tier]:
    """Tier hierarchy for rate limiting: public ⊂ work/friends ⊂ personal.
    work and friends are parallel levels; personal sees everything."""
    _order: list[Tier] = ["public", "work", "friends", "personal"]
    # personal can access all; work/friends access their own level + public
    if tier == "personal":
        return list(_order)
    if tier in ("work", "friends"):
        return ["public", tier]
    return ["public"]
