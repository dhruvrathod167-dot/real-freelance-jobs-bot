"""
Application Configuration Module
Loads configuration from environment variables and .env file using Pydantic.
Ensures strong typing, secure defaults, and easy cloud deployment.
"""

from typing import List, Set, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import os


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False
    )

    # Telegram Bot Settings
    TELEGRAM_BOT_TOKEN: str = Field(default="", description="Telegram Bot token from @BotFather")
    BOT_USERNAME: str = Field(default="RealFreelanceJobsBot", description="Bot handle without @")
    ADMIN_IDS_RAW: str = Field(default="", alias="ADMIN_IDS", description="Comma-separated admin Telegram IDs")
    TELEGRAM_GROUP_ID: str = Field(default="-1004335696952", description="Group or Channel ID for job broadcasts (Legally Freelancing Working)")
    TELEGRAM_GROUP_NAME: str = Field(default="Legally Freelancing Working", description="Name of the official group")

    # Database Settings
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./freelance_jobs.db",
        description="Async database connection string (SQLite or PostgreSQL)"
    )

    # AI Analyzer Settings
    AI_PROVIDER: str = Field(default="openai", description="AI Provider: 'openai' or 'gemini'")
    AI_API_KEY: str = Field(default="", description="API key for AI provider (optional, heuristic fallback available)")
    AI_MODEL: str = Field(default="gpt-4o-mini", description="AI model to query")

    # Web Server / Health Check Settings
    FASTAPI_HOST: str = Field(default="0.0.0.0", description="FastAPI bind host")
    FASTAPI_PORT: int = Field(default=8000, description="FastAPI bind port")
    ENVIRONMENT: str = Field(default="development", description="development or production")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    @property
    def telegram_token(self) -> str:
        """Returns the full bot token, prepending the numeric bot ID if missing."""
        token = self.TELEGRAM_BOT_TOKEN.strip().strip("'\"")
        if not token:
            return ""
        if ":" not in token:
            # Automatically prefix the BotFather bot ID if omitted
            return f"8787634226:{token}"
        return token

    @property
    def effective_ai_provider(self) -> str:
        """Determines provider from API key or configured AI_PROVIDER."""
        key = self.AI_API_KEY.strip().strip("'\"")
        if key.startswith("sk-"):
            return "openai"
        if key.startswith("AIza"):
            return "gemini"
        provider = self.AI_PROVIDER.strip().strip("'\"").lower()
        return provider if provider in ("openai", "gemini") else "openai"

    @property
    def effective_ai_model(self) -> str:
        """Returns clean AI model name with smart defaults based on provider."""
        model = self.AI_MODEL.strip().strip("'\"")
        if model:
            return model
        return "gpt-4o-mini" if self.effective_ai_provider == "openai" else "gemini-1.5-flash"

    @property
    def effective_group_id(self) -> Optional[int]:
        """Parse TELEGRAM_GROUP_ID into an integer chat ID, or None if unconfigured."""
        val = str(self.TELEGRAM_GROUP_ID).strip().strip("'\"")
        if val:
            try:
                return int(val)
            except ValueError:
                return None
        return None

    @property
    def admin_id_list(self) -> Set[int]:
        """Parse raw comma-separated ADMIN_IDS into a set of integer Telegram user IDs."""
        if not self.ADMIN_IDS_RAW:
            return set()
        ids = set()
        for item in str(self.ADMIN_IDS_RAW).split(","):
            cleaned = item.strip().strip("'\"")
            if cleaned.isdigit() or (cleaned.startswith("-") and cleaned[1:].isdigit()):
                ids.add(int(cleaned))
        return ids

    def is_admin(self, user_id: int) -> bool:
        """Check if a given Telegram user ID has admin privileges."""
        return user_id in self.admin_id_list


# Singleton configuration instance
settings = Settings()
