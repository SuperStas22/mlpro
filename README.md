# logp-service

Сервис предсказывает липофильность молекулы, logP (октанол/вода), по 14 RDKit-дескрипторам.
Модель: градиентный бустинг `HistGradientBoostingRegressor` из scikit-learn, обучен на ~14 тыс. молекул
из моего проекта [logP-Prediction](https://github.com/SuperStas22/logP-Prediction). Ноутбук обучения:
[`notebooks/train.ipynb`](notebooks/train.ipynb), отчёт по ДЗ: [`REPORT.md`](REPORT.md).

Нужны `uv`, Docker с compose v2, `kind` и `kubectl`. Порты 8000 и 8080 должны быть свободны.

## Проверка: три команды

```bash
# 1. Тесты
uv sync && uv run pytest
```

```bash
# 2. Compose: сервис + Postgres, запрос к модели и SELECT из таблицы логов
docker compose up -d --build --wait \
  && curl -s -X POST http://127.0.0.1:8000/v1/predict -H 'Content-Type: application/json' -d @good.json && echo \
  && sleep 1 && docker compose exec db psql -U postgres -d logp -c "SELECT request_id, ts, model_version, prediction, latency_ms, status_code FROM predictions ORDER BY ts DESC LIMIT 5"
```

```bash
# 3. kind: кластер, образ, манифесты, rollout, ответ модели через port-forward
(kind get clusters | grep -qx logp || kind create cluster --name logp) && kubectl config use-context kind-logp \
  && docker build -t logp-service:1.0 . && kind load docker-image logp-service:1.0 --name logp \
  && kubectl apply -f k8s/ && kubectl rollout status deploy/logp-service --timeout=180s \
  && kubectl get deploy,pods -l app=logp \
  && { kubectl port-forward svc/logp-service 8080:80 >/dev/null & PF=$!; sleep 3; \
       curl -s -X POST http://127.0.0.1:8080/v1/predict -H 'Content-Type: application/json' -d @good.json; echo; kill $PF; }
```

Уборка после проверки: `docker compose down -v && kind delete cluster --name logp`.

## Доказательства

| | |
|---|---|
| `uv run pytest` | ![pytest](docs/screens/01_pytest.png) |
| SELECT из таблицы логов | ![select](docs/screens/02_select.png) |
| `kubectl get pods`, 2/2 Running, и ответ `/v1/predict` через port-forward | ![kind](docs/screens/03_kind.png) |
| k9s с подами | ![k9s](docs/screens/04_k9s.png) |

## API

| Точка | Что делает |
|---|---|
| `GET /health` | жив ли процесс: `status`, `model_version`, `app_version` (версия образа) |
| `GET /ready` | загружена ли модель, иначе 503 |
| `POST /v1/predict` | одна молекула → `logp`, `lipinski_ok`, `model_version`, `request_id`, `latency_ms` |
| `POST /v1/predict/batch` | `{"rows": [...]}` от 1 до 1000 молекул, модель вызывается один раз |
| `GET /docs`, `GET /redoc` | автодоки, в `/docs` есть рабочий пример запроса |

Пример запроса лежит в [`good.json`](good.json): ибупрофен, экспериментальный logP 3.97.

```json
{"logp":4.059582599082669,"lipinski_ok":true,"model_version":"hgb-1.0","request_id":"96ad27d2-58cf-4242-8abb-233c7660bd20","latency_ms":7.26}
```

### Схема запроса

`extra="forbid"`: лишнее поле даёт 422. Границы взяты с запасом относительно обучающих данных.

| Поле | Тип | Границы | Смысл |
|---|---|---|---|
| `MolWt` | float | 0 < x ≤ 2000 | молекулярная масса, г/моль |
| `HeavyAtomCount` | int | 1..200 | тяжёлые атомы |
| `NumHeteroatoms` | int | 0..200 | атомы кроме C и H |
| `fr_halogen` | int | 0..100 | атомы галогенов |
| `NumHDonors`, `NumHAcceptors` | int | 0..50, 0..100 | доноры и акцепторы H-связи |
| `TPSA` | float | 0..1000 | топологическая полярная площадь поверхности, Å² |
| `MolMR` | float | 0..1000 | молярная рефракция |
| `NumRotatableBonds` | int | 0..200 | вращающиеся связи |
| `RingCount`, `NumAromaticRings` | int | 0..50 | все циклы и ароматические |
| `FractionCSP3` | float | 0..1 | доля sp3-углерода |
| `MaxPartialCharge`, `MinPartialCharge` | float, **опционально** | −1..1 | заряды Гастайгера |

Заряды опциональные, потому что для молекул с As, Se, I(III) и т.п. у метода Гастайгера нет параметров и RDKit отдаёт NaN:
в обучающих данных таких 13 строк, в пайплайне пропуск закрывает медиана. Кроме границ, схема проверяет согласованность
счётчиков: `NumAromaticRings ≤ RingCount`, `fr_halogen ≤ NumHeteroatoms ≤ HeavyAtomCount`, `MinPartialCharge ≤ MaxPartialCharge`
(на всех 14,9 тыс. молекул из данных это выполняется).

Дескрипторы для своей молекулы можно посчитать так: `from rdkit.Chem import Descriptors; Descriptors.CalcMolDescriptors(mol)`.

## Артефакт

`artifact/model.joblib` это словарь из двух частей:

* `pipeline`: `SimpleImputer(median)` → `HistGradientBoostingRegressor(300 деревьев, lr=0.1)`, одним `Pipeline`;
* `metadata`: `model_version`, `features` в правильном порядке, `threshold` = 5.0 (правило пяти Липински,
  отсюда флаг `lipinski_ok = logp ≤ 5`), метрики, версии sklearn и Python, дата обучения.

| | R² | MAE |
|---|---|---|
| holdout 20 %, бустинг | 0.879 | 0.45 |
| holdout 20 %, Crippen `MolLogP` (бейзлайн из RDKit) | 0.775 | 0.61 |
| внешний тест Martel, бустинг | −0.53 | 1.19 |

На Martel R² отрицательный и у бустинга, и у Crippen (−0.09): набор специально собран из сложных молекул
с узким диапазоном logP.

Переобучить: положить `logP-14000.csv` и `logP-707-Martel.csv` из папки `logP-707/` репозитория
[logP-Prediction](https://github.com/SuperStas22/logP-Prediction) в `data/` (она в `.gitignore`) и выполнить ноутбук.

## Логи в Postgres

Каждый запрос к `/v1/predict` пишется строкой в таблицу `predictions`, в фоне, после ответа клиенту:

| Колонка | |
|---|---|
| `request_id` uuid | тот же, что в ответе |
| `ts` timestamptz | время |
| `model_version` text | |
| `features` jsonb | что прислали; при 422 тоже, чтобы было видно, что сломалось |
| `prediction` double | NULL при 422 и 500 |
| `latency_ms` real | время сборки DataFrame и predict; NULL при 422 |
| `status_code` smallint | 200, 422 или 500 |

Без `DATABASE_URL` сервис работает и просто не логирует (так он запущен в kind). Если база нужна и там,
адрес кладётся в секрет `logp-secrets` (`kubectl create secret generic logp-secrets --from-literal=DATABASE_URL=...`),
деплоймент подхватит его после `kubectl rollout restart deploy/logp-service`.

```sql
SELECT status_code, count(*), round(avg(latency_ms)::numeric, 2) AS avg_ms FROM predictions GROUP BY 1;
SELECT features->>'NumHDonors', count(*) FROM predictions WHERE status_code = 422 GROUP BY 1;
```

## Структура

```
src/logp/config.py          настройки из env: MODEL_PATH, DATABASE_URL, APP_VERSION
src/logp/db.py              таблица логов и запись в неё
src/logp/service/app.py     FastAPI: схема, lifespan, ручки
tests/                      24 теста: контракт, smoke, детерминизм, логирование, батч
notebooks/train.ipynb       обучение и сохранение артефакта
k8s/                        deployment (2 реплики, 3 пробы), service, configmap
locustfile.py               нагрузка, звёздочка 1
scripts/bench_batch.py      батч против одной строки, звёздочка 2
docs/                       скрины, CSV нагрузочных прогонов, история выката
```
