from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "智档"
    environment: str = Field(default="dev", alias="ENVIRONMENT")
    debug: bool = False
    database_url: str = Field(default="sqlite:///./zhidang.db", alias="DATABASE_URL")
    jwt_secret: str = Field(default="change-me", alias="JWT_SECRET")
    jwt_exp_hours: int = 24
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    static_dir: str = "frontend/dist"
    agent_a_max_rounds: int = 5
    agent_b_max_rounds: int = 5
    data_retention_days: int = 90
    encryption_key: str | None = Field(default=None, alias="ENCRYPTION_KEY")


settings = Settings()
