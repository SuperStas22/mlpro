import os

import psycopg
import pytest

import logp.service.app as service_app

DATABASE_URL = os.getenv("DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="нужен Postgres: задайте DATABASE_URL"),
]


def logged(request_id):
    # Читаем именно строку текущего запроса, не полагаясь на порядок записей.
    with psycopg.connect(DATABASE_URL) as conn:
        return conn.execute(
            "SELECT model_version, prediction, status_code, features->>'MolWt' FROM predictions WHERE request_id = %s",
            (request_id,),
        ).fetchone()


def test_prediction_is_logged(client, good_row):
    # Успешный ответ должен сохранять версию модели, прогноз, код и признаки.
    body = client.post("/v1/predict", json=good_row).json()
    row = logged(body["request_id"])

    assert row is not None
    assert row[0] == body["model_version"]
    assert row[1] == pytest.approx(body["logp"])
    assert row[2] == 200
    assert float(row[3]) == good_row["MolWt"]


def test_garbage_is_logged_with_422(client, good_row):
    # Ошибка схемы тоже является запросом: сохраняем её с prediction = NULL.
    r = client.post("/v1/predict", json={**good_row, "NumHDonors": "много"})
    assert r.status_code == 422
    row = logged(r.json()["request_id"])

    assert row is not None
    assert row[1] is None
    assert row[2] == 422


def test_prediction_failure_is_logged_with_500(client, good_row, monkeypatch):
    # Имитируем сбой модели, чтобы проверить обработчик и его побочный эффект в БД.
    def fail_prediction(_rows):
        raise RuntimeError("искусственный сбой предсказания")

    monkeypatch.setattr(service_app, "predict_frame", fail_prediction)

    r = client.post("/v1/predict", json=good_row)
    assert r.status_code == 500
    row = logged(r.json()["request_id"])

    # При ошибке нельзя записывать выдуманный прогноз, но код ответа обязателен.
    assert row is not None
    assert row[1] is None
    assert row[2] == 500
