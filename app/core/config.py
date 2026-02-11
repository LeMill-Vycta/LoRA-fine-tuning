from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="LoRA Studio", alias="APP_NAME")
    app_version: str = Field(default="1.1.0", alias="APP_VERSION")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")

    database_url: str = Field(default="sqlite:///data/lora_studio.db", alias="DATABASE_URL")
    artifacts_path: Path = Field(default=Path("data/artifacts"), alias="ARTIFACTS_PATH")

    session_secret: str = Field(default="change-this-secret", alias="SESSION_SECRET")
    access_token_expire_minutes: int = Field(default=1440, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    password_pbkdf2_iterations: int = Field(default=390000, alias="PASSWORD_PBKDF2_ITERATIONS")
    api_key: str | None = Field(default=None, alias="API_KEY")
    operator_token: str | None = Field(default=None, alias="OPERATOR_TOKEN")
    operator_header_name: str = Field(default="X-Operator-Token", alias="OPERATOR_HEADER_NAME")

    max_gpu_vram_gb: float = Field(default=8.0, alias="MAX_GPU_VRAM_GB")
    vram_safety_factor: float = Field(default=0.85, alias="VRAM_SAFETY_FACTOR")

    doc_quality_threshold: int = Field(default=65, alias="DOC_QUALITY_THRESHOLD")
    near_duplicate_threshold: float = Field(default=0.9, alias="NEAR_DUPLICATE_THRESHOLD")
    require_grounding: bool = Field(default=True, alias="REQUIRE_GROUNDING")
    max_upload_mb: int = Field(default=50, alias="MAX_UPLOAD_MB")

    worker_poll_seconds: float = Field(default=2.0, alias="WORKER_POLL_SECONDS")
    enable_background_worker: bool = Field(default=True, alias="ENABLE_BACKGROUND_WORKER")
    enable_metrics: bool = Field(default=True, alias="ENABLE_METRICS")

    inference_backend: str = Field(default="mock", alias="INFERENCE_BACKEND")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_chat_model: str = Field(default="llama3.1:8b", alias="OLLAMA_CHAT_MODEL")

    trainer_backend: str = Field(default="mock", alias="TRAINER_BACKEND")
    trainer_command_template: str | None = Field(default=None, alias="TRAINER_COMMAND_TEMPLATE")

    supported_models: dict[str, dict[str, Any]] = {
        "mistralai/Mistral-7B-Instruct-v0.3": {
            "license": "Apache-2.0",
            "vram_tier": "8GB-friendly with QLoRA",
            "intended_use": "instruction",
            "approved": True,
        },
        "meta-llama/Llama-3.1-8B-Instruct": {
            "license": "Llama 3.1 Community License",
            "vram_tier": "8GB with strict QLoRA settings",
            "intended_use": "chat",
            "approved": True,
        },
        "Qwen/Qwen2.5-7B-Instruct": {
            "license": "Apache-2.0",
            "vram_tier": "8GB-friendly with QLoRA",
            "intended_use": "chat",
            "approved": True,
        },
    }

    @field_validator("access_token_expire_minutes", "max_upload_mb", "password_pbkdf2_iterations")
    @classmethod
    def validate_positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("value must be positive")
        return value

    @field_validator("vram_safety_factor", "near_duplicate_threshold")
    @classmethod
    def validate_ratio(cls, value: float) -> float:
        if value <= 0 or value > 1:
            raise ValueError("ratio must be between 0 and 1")
        return value

    @field_validator("doc_quality_threshold")
    @classmethod
    def validate_quality_threshold(cls, value: int) -> int:
        if value < 0 or value > 100:
            raise ValueError("doc_quality_threshold must be between 0 and 100")
        return value

    @field_validator("inference_backend")
    @classmethod
    def validate_inference_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"mock", "ollama"}:
            raise ValueError("inference_backend must be one of: mock, ollama")
        return normalized

    @field_validator("trainer_backend")
    @classmethod
    def validate_trainer_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"mock", "command"}:
            raise ValueError("trainer_backend must be one of: mock, command")
        return normalized

    def ensure_directories(self) -> None:
        self.artifacts_path.mkdir(parents=True, exist_ok=True)
        self._ensure_sqlite_parent(self.database_url)

    @staticmethod
    def _ensure_sqlite_parent(database_url: str) -> None:
        if not database_url.startswith("sqlite"):
            return
        parsed = urlparse(database_url)
        db_path = parsed.path.lstrip("/")
        if not db_path:
            return
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
