from types import SimpleNamespace

import logp.model_store as model_store


def test_load_model_uses_joblib_without_model_name(monkeypatch):
    # CI не должен зависеть от MLflow: отсутствие MODEL_NAME включает fallback.
    bundle = {
        "pipeline": object(),
        "metadata": {"model_version": "file-v1", "features": [], "threshold": 5.0},
    }
    monkeypatch.setattr(model_store.settings, "model_name", None)
    monkeypatch.setattr(model_store.joblib, "load", lambda path: bundle)

    pipeline, metadata, version = model_store.load_model()

    assert pipeline is bundle["pipeline"]
    assert metadata is bundle["metadata"]
    assert version == "file-v1"


def test_load_model_resolves_registry_alias(monkeypatch):
    # Подменяем только сетевые вызовы, проверяя построенные URI и версию /health.
    import mlflow
    import mlflow.sklearn

    calls = {}
    registered_version = SimpleNamespace(version="3", run_id="run-3")
    pipeline = object()
    metadata = {"features": ["MolWt"], "threshold": 5.0}

    class FakeClient:
        def get_model_version_by_alias(self, model_name, alias):
            calls["alias"] = (model_name, alias)
            return registered_version

    monkeypatch.setattr(model_store.settings, "model_name", "logp-model")
    monkeypatch.setattr(model_store.settings, "model_alias", "champion")
    monkeypatch.setattr(model_store.settings, "mlflow_tracking_uri", "http://mlflow.mlops:5000")
    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: calls.setdefault("tracking_uri", uri))
    monkeypatch.setattr(mlflow, "MlflowClient", FakeClient)
    monkeypatch.setattr(mlflow.sklearn, "load_model", lambda uri: calls.setdefault("model_uri", uri) and pipeline)
    monkeypatch.setattr(mlflow.artifacts, "load_dict", lambda uri: calls.setdefault("metadata_uri", uri) and metadata)

    loaded_pipeline, loaded_metadata, version = model_store.load_model()

    assert calls == {
        "tracking_uri": "http://mlflow.mlops:5000",
        "alias": ("logp-model", "champion"),
        "model_uri": "models:/logp-model/3",
        "metadata_uri": "runs:/run-3/metadata.json",
    }
    assert loaded_pipeline is pipeline
    assert loaded_metadata is metadata
    assert version == "logp-model-v3"
