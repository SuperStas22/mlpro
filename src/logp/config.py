from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_path: str = "artifact/model.joblib"
    # Если MODEL_NAME не задан, тесты и локальный запуск используют старый joblib-файл.
    model_name: str | None = None
    model_alias: str = "champion"
    mlflow_tracking_uri: str = "http://127.0.0.1:5000"
    database_url: str | None = None
    app_version: str = "1.0"
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "protected_namespaces": ()}


settings = Settings()
