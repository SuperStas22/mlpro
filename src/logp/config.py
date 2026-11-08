from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_path: str = "artifact/model.joblib"
    database_url: str | None = None
    app_version: str = "1.0"
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "protected_namespaces": ()}


settings = Settings()
