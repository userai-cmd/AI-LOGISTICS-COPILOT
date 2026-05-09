from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = Field(..., validation_alias="ANTHROPIC_API_KEY")
    model_name: str = Field(default="claude-3-5-sonnet-latest", validation_alias="MODEL_NAME")

    telegram_bot_token: str = Field(..., validation_alias="TELEGRAM_BOT_TOKEN")
    operator_chat_id: int = Field(..., validation_alias="OPERATOR_CHAT_ID")
    manager_chat_id: int | None = Field(default=None, validation_alias="MANAGER_CHAT_ID")

    database_url: str = Field(..., validation_alias="DATABASE_URL")
    database_ssl: bool = Field(
        default=False,
        validation_alias="DATABASE_SSL",
    )

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

    @property
    def effective_manager_chat_id(self) -> int:
        return self.manager_chat_id if self.manager_chat_id is not None else self.operator_chat_id


def get_settings() -> Settings:
    return Settings()
