from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET = "dev-only-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", protected_namespaces=())

    app_name: str = "FieldOps AI API"
    database_url: str = "sqlite:///./fieldops.db"
    secret_key: str = DEFAULT_SECRET
    demo_mode: bool = True
    demo_auth_enabled: bool = True
    model_mode: str = "fixture"
    token_ttl_minutes: int = 480
    investigations_per_minute: int = 5
    run_step_delay_ms: int = 0
    cors_origins: str = "http://localhost:5173"
    approval_expiry_minutes: int = 30
    retrieval_top_k: int = 4
    max_retries: int = 2
    eval_max_concurrency: int = 1
    log_level: str = "INFO"

    def validate_safety(self) -> None:
        """Refuse unsafe combinations at startup (fail closed)."""
        if self.demo_auth_enabled and not self.demo_mode:
            raise RuntimeError("DEMO_AUTH_ENABLED requires DEMO_MODE=true. Demo auth is never a production mechanism.")
        if not self.demo_mode and self.secret_key == DEFAULT_SECRET:
            raise RuntimeError("SECRET_KEY must be set outside demo mode.")
        if len(self.secret_key) < 16:
            raise RuntimeError("SECRET_KEY is too short.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
