"""Что сервис пишет в таблицу логов. База не нужна: запись подменена фикстурой saved."""

from logp.service import app as service


def test_success_is_logged_with_200(client, good_row, saved):
    body = client.post("/v1/predict", json=good_row).json()
    assert len(saved) == 1
    row = saved[0]
    assert row["status_code"] == 200
    assert row["request_id"] == body["request_id"]
    assert row["prediction"] == body["logp"]
    assert row["features"]["MolWt"] == good_row["MolWt"]


def test_validation_error_is_logged_with_422(client, good_row, saved):
    r = client.post("/v1/predict", json={**good_row, "NumHDonors": -1})
    assert r.status_code == 422
    assert saved[0]["status_code"] == 422
    assert saved[0]["prediction"] is None
    assert saved[0]["features"]["NumHDonors"] == -1  # пишем то, что прислали, чтобы было видно, что сломалось
    assert saved[0]["request_id"] == r.json()["request_id"]


def test_model_failure_is_logged_with_500(client, good_row, saved, monkeypatch):
    def broken(rows):
        raise RuntimeError("boom")

    # app.state через monkeypatch не подменять: при откате pytest удаляет атрибут из State, а не возвращает его
    monkeypatch.setattr(service, "predict_frame", broken)
    r = client.post("/v1/predict", json=good_row)
    assert r.status_code == 500
    assert saved[0]["status_code"] == 500


def test_other_endpoints_are_not_logged(client, saved):
    client.get("/health")
    client.post("/v1/predict/batch", json={"rows": []})
    assert saved == []
