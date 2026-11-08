import pytest
from fastapi.testclient import TestClient

from logp.service.app import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def good_row():
    # ибупрофен, экспериментальный logP 3.97
    return {
        "MolWt": 206.285,
        "HeavyAtomCount": 15,
        "NumHeteroatoms": 2,
        "fr_halogen": 0,
        "NumHDonors": 1,
        "NumHAcceptors": 1,
        "TPSA": 37.3,
        "MolMR": 61.0348,
        "NumRotatableBonds": 4,
        "RingCount": 1,
        "NumAromaticRings": 1,
        "FractionCSP3": 0.4615,
        "MaxPartialCharge": 0.3102,
        "MinPartialCharge": -0.4808,
    }
