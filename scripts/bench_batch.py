"""Звёздочка 2: одна строка через /v1/predict/batch против 500 строк в одном запросе.

  uv run python scripts/bench_batch.py --url http://127.0.0.1:8000 --repeats 15

latency_ms из ответа: время сервиса на сборку DataFrame и predict. wall_ms: полный путь запроса с клиента,
включая JSON и валидацию pydantic каждой строки.
"""

import argparse
import json
import random
import statistics
import time
from pathlib import Path

import httpx

GOOD = json.loads((Path(__file__).resolve().parents[1] / "good.json").read_text())

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8000")
parser.add_argument("--repeats", type=int, default=15)
args = parser.parse_args()


def rows(n: int) -> list[dict]:
    return [
        {**GOOD, "MolWt": round(GOOD["MolWt"] * random.uniform(0.8, 1.5), 3), "TPSA": round(random.uniform(0, 120), 2)} for _ in range(n)
    ]


def call(client: httpx.Client, n: int) -> tuple[float, float]:
    payload = {"rows": rows(n)}
    t0 = time.perf_counter()
    r = client.post("/v1/predict/batch", json=payload)
    wall_ms = (time.perf_counter() - t0) * 1000
    r.raise_for_status()
    assert len(r.json()["predictions"]) == n
    return r.json()["latency_ms"], wall_ms


# trust_env=False: мимо системного прокси, меряем сервис, а не прокси.
# urllib не годится: заголовки и тело уходят разными пакетами, и Nagle + delayed ACK добавляют ~40 мс к каждому запросу
result = {}
with httpx.Client(base_url=args.url, trust_env=False, timeout=30) as client:
    for n in (1, 500):
        call(client, n)  # прогрев
        runs = [call(client, n) for _ in range(args.repeats)]
        result[n] = (statistics.median(r[0] for r in runs), statistics.median(r[1] for r in runs))
        print(f"{n:>4} строк: latency_ms медиана {result[n][0]:.2f}, wall_ms медиана {result[n][1]:.2f}")

single, batch = result[1], result[500]
print(f"500 строк дороже одной: по latency_ms в {batch[0] / single[0]:.1f} раза, по wall_ms в {batch[1] / single[1]:.1f} раза")
print(f"на одну строку в батче: {batch[0] / 500 * 1000:.0f} мкс модели против {single[0] * 1000:.0f} мкс в одиночном запросе")
