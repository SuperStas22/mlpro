import uuid


def test_predict_smoke(client, good_row):
    r = client.post("/v1/predict", json=good_row)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["logp"], float)
    assert -10 <= body["logp"] <= 15  # весь диапазон logP в данных от -5 до 11
    assert abs(body["logp"] - 3.97) < 1.0  # ибупрофен, эксперимент 3.97
    assert body["lipinski_ok"] is (body["logp"] <= 5)
    assert body["latency_ms"] >= 0
    assert body["model_version"]
    uuid.UUID(body["request_id"])


def test_optional_charges(client, good_row):
    # заряды Гастайгера бывают NaN: поле можно передать как null или не передать вовсе
    assert client.post("/v1/predict", json={**good_row, "MaxPartialCharge": None, "MinPartialCharge": None}).status_code == 200
    row = {k: v for k, v in good_row.items() if not k.endswith("PartialCharge")}
    assert client.post("/v1/predict", json=row).status_code == 200


def test_deterministic(client, good_row):
    first = client.post("/v1/predict", json=good_row).json()
    second = client.post("/v1/predict", json=good_row).json()
    assert first["logp"] == second["logp"]
    assert first["request_id"] != second["request_id"]


def test_lipophilic_molecule_fails_lipinski(client, good_row):
    # крупная галогенированная ароматика без полярных групп: logP заведомо выше 5
    row = {
        **good_row,
        "MolWt": 430.0,
        "HeavyAtomCount": 22,
        "NumHeteroatoms": 6,
        "fr_halogen": 6,
        "NumHDonors": 0,
        "NumHAcceptors": 0,
        "TPSA": 0.0,
        "MolMR": 95.0,
        "RingCount": 2,
        "NumAromaticRings": 2,
        "FractionCSP3": 0.0,
    }
    body = client.post("/v1/predict", json=row).json()
    assert body["logp"] > 5 and body["lipinski_ok"] is False
