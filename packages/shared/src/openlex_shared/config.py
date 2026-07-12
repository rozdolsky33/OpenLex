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

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # Demo users (seeded via `apps/api/src/openlex_api/seed_demo_users.py`) -- defaulted to ""
    # rather than required, so existing .env/CI configs that don't set them don't break
    # Settings() construction. The seed script itself validates these are non-empty before
    # running.
    demo_silver_email: str = ""
    demo_silver_password: str = ""
    demo_gold_email: str = ""
    demo_gold_password: str = ""
    demo_platinum_email: str = ""
    demo_platinum_password: str = ""


settings = Settings()  # type: ignore[call-arg]  # pydantic-settings fills these from .env at runtime
