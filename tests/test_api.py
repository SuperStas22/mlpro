def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert "model_version" in r.json()
    assert r.json()["log_level"] == "INFO"


def test_ready(client):
    assert client.get("/ready").status_code == 200


def test_bad_donors_is_422(client, good_row):
    # Отрицательное число доноров нарушает ограничение отдельного поля.
    r = client.post("/v1/predict", json={**good_row, "NumHDonors": -1})
    assert r.status_code == 422


def test_missing_field_is_422(client, good_row):
    # TPSA обязательна: модель не должна получать неполный набор признаков.
    row = dict(good_row)
    del row["TPSA"]
    assert client.post("/v1/predict", json=row).status_code == 422


def test_extra_field_is_422(client, good_row):
    # Запрещаем неизвестные поля, чтобы опечатки клиента не игнорировались.
    r = client.post("/v1/predict", json={**good_row, "SMILES": "CCO"})
    assert r.status_code == 422


def test_aromatic_rings_cannot_exceed_all_rings(client, good_row):
    # Ароматические циклы являются подмножеством всех циклов молекулы.
    r = client.post(
        "/v1/predict",
        json={**good_row, "RingCount": 1, "NumAromaticRings": 2},
    )
    assert r.status_code == 422


def test_halogens_cannot_exceed_heteroatoms(client, good_row):
    # Галогены входят в число гетероатомов, поэтому их не может быть больше.
    r = client.post(
        "/v1/predict",
        json={**good_row, "NumHeteroatoms": 1, "fr_halogen": 2},
    )
    assert r.status_code == 422


def test_min_partial_charge_cannot_exceed_max(client, good_row):
    # Пара зарядов должна сохранять естественный порядок min <= max.
    r = client.post(
        "/v1/predict",
        json={**good_row, "MinPartialCharge": 0.4, "MaxPartialCharge": -0.2},
    )
    assert r.status_code == 422
