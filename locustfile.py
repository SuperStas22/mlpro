"""Нагрузка на сервис: много предсказаний и изредка /health.

uv run locust -f locustfile.py --headless -u 50 -r 10 -t 60s --csv run50 -H http://127.0.0.1:8000
"""

import json
import random
from pathlib import Path

from locust import HttpUser, between, task

GOOD = json.loads((Path(__file__).parent / "good.json").read_text())


def molecule() -> dict:
    row = dict(GOOD)
    row["MolWt"] = round(GOOD["MolWt"] * random.uniform(0.8, 1.5), 3)
    row["TPSA"] = round(random.uniform(0, 120), 2)
    row["FractionCSP3"] = round(random.random(), 3)
    row["NumRotatableBonds"] = random.randint(0, 10)
    return row


class Chemist(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(10)
    def predict(self):
        with self.client.post("/v1/predict", json=molecule(), catch_response=True) as r:
            if r.status_code == 200 and not -10 <= r.json()["logp"] <= 15:
                r.failure(f"logp вне диапазона: {r.json()['logp']}")

    @task(1)
    def health(self):
        self.client.get("/health")
