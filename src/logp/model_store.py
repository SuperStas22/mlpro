"""Загрузка модели из локального файла или из MLflow Model Registry."""

import joblib

from logp.config import settings


def load_model() -> tuple[object, dict, str]:
    """Вернуть Pipeline, паспорт и отображаемую версию модели."""
    if not settings.model_name:
        # Fallback сохраняет быстрые тесты и автономный запуск без MLflow.
        bundle = joblib.load(settings.model_path)
        metadata = bundle["metadata"]
        return bundle["pipeline"], metadata, metadata["model_version"]

    # Тяжёлый импорт нужен только в production-режиме с Model Registry.
    import mlflow
    import mlflow.sklearn
    from mlflow import MlflowClient

    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = MlflowClient()
    version = client.get_model_version_by_alias(settings.model_name, settings.model_alias)

    # Сначала фиксируем номер, на который указывал алиас: его перемещение в UI
    # во время загрузки не должно смешать модель одной версии с паспортом другой.
    model_uri = f"models:/{settings.model_name}/{version.version}"
    pipeline = mlflow.sklearn.load_model(model_uri)
    metadata = mlflow.artifacts.load_dict(f"runs:/{version.run_id}/metadata.json")
    display_version = f"{settings.model_name}-v{version.version}"
    return pipeline, metadata, display_version
