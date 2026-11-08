def test_predict_smoke(client, good_row):
    r = client.post("/v1/predict", json=good_row)
    assert r.status_code == 200
    body = r.json()
    assert -10 <= body["logp"] <= 15
    assert isinstance(body["lipinski_ok"], bool)
    assert body["latency_ms"] >= 0
    assert body["model_version"]


def test_predict_handles_missing_charges(client, good_row):
    r = client.post("/v1/predict", json={**good_row, "MaxPartialCharge": None, "MinPartialCharge": None})
    assert r.status_code == 200


def test_same_input_same_answer(client, good_row):
    s1 = client.post("/v1/predict", json=good_row).json()["logp"]
    s2 = client.post("/v1/predict", json=good_row).json()["logp"]
    assert abs(s1 - s2) < 1e-12
