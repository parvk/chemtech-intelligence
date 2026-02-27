from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Application
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8001
    secret_key: str = "change-me-in-production"

    # Database
    database_url: str = "postgresql+asyncpg://chemflow:chemflow@localhost:5432/chemflow_intelligence"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-6"

    # PubChem
    pubchem_base_url: str = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"

    # ECHA
    echa_api_base_url: str = "https://iuclid6.echa.europa.eu/api"

    # AiZynthFinder
    aizynthfinder_config_path: str = "/app/config/aizynthfinder.yml"
    aizynthfinder_stock_file: str = "/app/data/zinc_stock.hdf5"

    # Job Settings
    job_timeout_seconds: int = 180
    job_retention_days: int = 30

    # Logging
    log_level: str = "INFO"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


settings = Settings()
