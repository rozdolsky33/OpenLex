from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str
    anthropic_model: str = "claude-sonnet-4-5"

    database_url: str

    ny_open_leg_api_key: str = ""
    ny_open_leg_base_url: str = "https://legislation.nysenate.gov/api/3"

    embedding_model_name: str = "BAAI/bge-small-en-v1.5"

    cors_allow_origins: list[str] = ["http://localhost:5173"]


settings = Settings()  # type: ignore[call-arg]  # pydantic-settings fills these from .env at runtime
