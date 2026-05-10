from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def infer_postgres_ssl_from_url(database_url: str) -> bool:
    """Евристика Railway: публічний TCP-проксі → TLS; приватний *.railway.internal → без TLS."""
    u = database_url.strip()
    if u.startswith("postgres://"):
        u = "postgresql://" + u[len("postgres://") :]
    try:
        parsed = urlparse(u)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if "proxy.rlwy.net" in host:
        return True
    if "railway.internal" in host or host.endswith(".internal"):
        return False
    if host in ("localhost", "127.0.0.1", "::1"):
        return False
    return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = Field(..., validation_alias="ANTHROPIC_API_KEY")
    model_name: str = Field(
        default="claude-sonnet-4-6",
        validation_alias="MODEL_NAME",
    )

    telegram_bot_token: str = Field(..., validation_alias="TELEGRAM_BOT_TOKEN")
    operator_chat_id: int = Field(..., validation_alias="OPERATOR_CHAT_ID")
    manager_chat_id: int | None = Field(default=None, validation_alias="MANAGER_CHAT_ID")

    # Bearer for /api/operator/* and the browser workspace at /operator/
    operator_workspace_token: str | None = Field(
        default=None,
        validation_alias="OPERATOR_WORKSPACE_TOKEN",
    )

    database_url: str = Field(..., validation_alias="DATABASE_URL")
    # Якщо не задавати DATABASE_SSL у Railway — автоматично: proxy.rlwy.net=true, railway.internal=false
    database_ssl: bool | None = Field(
        default=None,
        validation_alias="DATABASE_SSL",
    )

    @field_validator("database_ssl", mode="before")
    @classmethod
    def _empty_database_ssl_as_unset(cls, v: object) -> object:
        if v == "":
            return None
        return v

    webhook_base_url: str = Field(
        default="http://127.0.0.1:8000",
        validation_alias="WEBHOOK_BASE_URL",
    )
    telegram_webhook_secret: str | None = Field(
        default=None,
        validation_alias="TELEGRAM_WEBHOOK_SECRET",
    )
    set_webhook_on_start: bool = Field(
        default=False,
        validation_alias="SET_WEBHOOK_ON_START",
    )

    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    host: str = Field(default="0.0.0.0", validation_alias="HOST")
    port: int = Field(default=8000, validation_alias="PORT")

    @property
    def telegram_webhook_url(self) -> str:
        base = self.webhook_base_url.rstrip("/")
        return f"{base}/api/webhooks/telegram"

    def postgres_should_use_ssl(self) -> bool:
        if self.database_ssl is not None:
            return self.database_ssl
        return infer_postgres_ssl_from_url(self.database_url)

    @property
    def effective_manager_chat_id(self) -> int:
        return self.manager_chat_id if self.manager_chat_id is not None else self.operator_chat_id


def get_settings() -> Settings:
    return Settings()
