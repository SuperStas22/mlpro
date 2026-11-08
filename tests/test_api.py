import pytest


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["model_version"].startswith("hgb-")


def test_ready(client):
    assert client.get("/ready").status_code == 200


def test_docs_example_is_valid(client):
    spec = client.get("/openapi.json").json()
    assert "/v1/predict" in spec["paths"]
    example = spec["components"]["schemas"]["Features"]["examples"][0]
    assert client.post("/v1/predict", json=example).status_code == 200


# контракт: мусор, выход за границы, лишние и пропущенные поля дают 422
@pytest.mark.parametrize(
    "field, value",
    [
        ("MolWt", "heavy"),  # мусор вместо числа
        ("MolWt", 0),  # gt=0
        ("NumHDonors", -1),  # ge=0
        ("NumHDonors", 1.5),  # счётчик должен быть целым
        ("FractionCSP3", 1.2),  # доля, le=1
        ("MaxPartialCharge", 3.0),  # заряд Гастайгера в [-1, 1]
    ],
)
def test_bad_value_is_422(client, good_row, field, value):
    assert client.post("/v1/predict", json={**good_row, field: value}).status_code == 422


def test_missing_required_field_is_422(client, good_row):
    row = dict(good_row)
    del row["TPSA"]
    assert client.post("/v1/predict", json=row).status_code == 422


def test_extra_field_is_422(client, good_row):
    assert client.post("/v1/predict", json={**good_row, "SMILES": "CCO"}).status_code == 422


def test_inconsistent_counts_are_422(client, good_row):
    assert client.post("/v1/predict", json={**good_row, "NumAromaticRings": 2, "RingCount": 1}).status_code == 422
    assert client.post("/v1/predict", json={**good_row, "fr_halogen": 3}).status_code == 422  # галогенов больше, чем гетероатомов


def test_invalid_json_is_422(client):
    r = client.post("/v1/predict", content=b"{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
