def test_batch_matches_single(client, good_row):
    rows = [good_row, {**good_row, "MolWt": 250.0, "MaxPartialCharge": None}, {**good_row, "TPSA": 80.0}]
    batch = client.post("/v1/predict/batch", json={"rows": rows})
    assert batch.status_code == 200
    preds = batch.json()["predictions"]
    assert len(preds) == len(rows)
    for row, p in zip(rows, preds, strict=True):
        assert p["logp"] == client.post("/v1/predict", json=row).json()["logp"]


def test_batch_bounds(client, good_row):
    assert client.post("/v1/predict/batch", json={"rows": []}).status_code == 422
    assert client.post("/v1/predict/batch", json={"rows": [good_row] * 1001}).status_code == 422
    assert client.post("/v1/predict/batch", json={"rows": [good_row] * 1000}).status_code == 200


def test_batch_validates_every_row(client, good_row):
    r = client.post("/v1/predict/batch", json={"rows": [good_row, {**good_row, "FractionCSP3": 2}]})
    assert r.status_code == 422
