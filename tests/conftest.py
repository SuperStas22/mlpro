import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from logp import db
from logp.service.app import app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def good_row():
    # ибупрофен, экспериментальный logP 3.97
    return json.loads((ROOT / "good.json").read_text())


@pytest.fixture()
def saved(monkeypatch):
    """Подменяет запись в Postgres и собирает строки, которые сервис пытался залогировать."""
    rows = []

    def fake_save(request_id, features, prediction, model_version, latency_ms, status_code):
        rows.append(
            {
                "request_id": request_id,
                "features": features,
                "prediction": prediction,
                "model_version": model_version,
                "latency_ms": latency_ms,
                "status_code": status_code,
            }
        )

    monkeypatch.setattr(db, "save_prediction", fake_save)
    return rows
