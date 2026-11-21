## Отчёт по ДЗ 3: DVC, MLflow и Model Registry

### Чекпоинты

| Пункт | Доказательство |
|---|---|
| Платформа kind + MLflow + Traefik | [`platform/up.sh`](platform/up.sh), [`platform/mlflow.yaml`](platform/mlflow.yaml), [`platform/ingress.yaml`](platform/ingress.yaml) |
| Две версии обучающих данных в DVC | [коммит v1 `c6a94af`](https://github.com/SuperStas22/mlpro/commit/c6a94af), [коммит v2 `8723668`](https://github.com/SuperStas22/mlpro/commit/8723668), [`data/logP-14000.csv.dvc`](data/logP-14000.csv.dvc) |
| Обучение, эксперименты и MAE-гейт | [`src/logp/train.py`](src/logp/train.py), [коммит `3e5c815`](https://github.com/SuperStas22/mlpro/commit/3e5c815) |
| Загрузка `champion` из Registry | [`src/logp/model_store.py`](src/logp/model_store.py), [`tests/test_model_store.py`](tests/test_model_store.py), [коммит `083dab1`](https://github.com/SuperStas22/mlpro/commit/083dab1) |
| CI/CD в локальный kind | [финальный зелёный run `44927196447`](https://github.com/SuperStas22/mlpro/actions/runs/44927196447), [скриншот](docs/screens/hw3-ci-success.png), [workflow](.github/workflows/ci.yml) |

### 1. Локальная MLOps-платформа

`platform/up.sh` идемпотентно создаёт кластер kind `logp`, устанавливает Traefik и применяет MLflow. Хранилище MLflow вынесено в PVC размером 2 GiB, поэтому эксперименты, Registry и артефакты переживают перезапуск pod. Ingress публикует UI как `http://mlflow.localhost`, а сервис модели как `http://logp.localhost`.

MLflow запущен с отдельным backend store и artifact store на PVC. Доступ из приложения внутри Kubernetes идёт напрямую через Service `http://mlflow.mlops:5000`, без внешнего Ingress.

### 2. Версионирование данных в DVC

Файл `data/logP-14000.csv` не хранится в Git: Git содержит маленький `.dvc`-указатель, а сами данные находятся в локальном DVC remote `../../dvc-storage`.

| Версия | Строк | MD5 | Изменение |
|---|---:|---|---|
| v1 | 14 176 | `cdd3248b2288aad9344a518523dc316a` | исходный датасет |
| v2 | 14 163 | `281ffae6e4e238e181d19c49b8410db1` | удалены 13 неполных строк скриптом `scripts/clean_dataset.py` |

Воспроизводимость проверена в отдельном чистом клоне `HW1-dvc-check`: после checkout Git-версии команда `dvc pull` восстановила соответствующий файл из remote. Тот же MD5 вычисляется при обучении и сохраняется в параметре MLflow `data_md5`, поэтому запуск однозначно связан с версией данных.

### 3. Эксперименты и регистрация моделей

`python -m logp.train` проверяет контракт данных, делает детерминированный split с `random_state=42`, обучает sklearn Pipeline и записывает в эксперимент `logp-training`:

- параметры модели, seed, путь и MD5 данных;
- метрики MAE, RMSE и R²;
- паспорт `metadata.json`;
- график `prediction_vs_actual.png`;
- сериализованную модель в `logp-model` Model Registry.

Проведены четыре запуска:

| Версия Registry | Данные | `max_iter` | MAE | Результат гейта |
|---|---|---:|---:|---|
| v1 | DVC v2 | 300 | 0,4601 | первый `champion` |
| v2 | DVC v2 | 20 | 0,7369 | не продвинута |
| v3 | DVC v2 | 500 | 0,4337 | новый `champion` |
| v4 | DVC v1 | 20 | 0,7286 | не продвинута, `challenger` |

Каждая новая версия получает алиас `challenger`. Алиас `champion` переносится только если новая MAE меньше прежней хотя бы на `GATE_MIN_GAIN=0.01`. Запас 0,01 выбран, чтобы не выкатывать модель из-за шума разбиения и улучшения в тысячных: для logP это малая, но уже различимая доля ошибки относительно MAE около 0,45. Решение сохраняется в тегах запуска `gate.promoted` и `gate.champion_before`. В финальном состоянии `champion` указывает на v3, `challenger` — на v4.

### 4. Использование Registry в сервисе

В Kubernetes заданы `MODEL_NAME=logp-model`, `MODEL_ALIAS=champion` и адрес MLflow. При старте `model_store.py` сначала разрешает алиас в конкретную Model Version, а затем загружает модель и паспорт по зафиксированным номеру версии и `run_id`. Поэтому перемещение алиаса во время загрузки не может смешать модель одной версии с метаданными другой.

Endpoint `/health` показывает фактически загруженную версию, например `logp-model-v3`. Перемещение алиаса само по себе не меняет уже работающий процесс: для применения новой версии выполняется rollout deployment. При автономном запуске без `MODEL_NAME` сохранён fallback на локальный joblib из ДЗ 1.

Тесты `tests/test_model_store.py` проверяют разрешение алиаса, загрузку конкретной версии и локальный fallback.

### 5. Проверка отката

Для контролируемого отката алиас `champion` был перемещён с v3 на v1, после чего выполнен restart deployment. Новые pod загрузили v1, а `/health` вернул `logp-model-v1`. Измеренное время от переключения до готового rollout составило 13,445 секунды. Затем алиас возвращён на v3 и повторный rollout подтвердил `logp-model-v3`.

Это разделяет выпуск модели и образа приложения: для отката модели не требуется собирать новый Docker-образ, достаточно вернуть алиас и перезапустить реплики.

### 6. CI/CD

После tests job build публикует неизменяемый образ. Job deploy выполняется на self-hosted runner с меткой kind, потому что только он имеет доступ к локальному Docker daemon и кластеру kind.

Deploy:

1. экспортирует kubeconfig существующего кластера
2. скачивает SHA-образ из GHCR и загружает его в kind
3. создаёт Kubernetes Secret из GitHub Secret DB_PASSWORD
4. применяет PostgreSQL и манифесты сервиса
5. ждёт rollout двух реплик
6. проверяет `/health`, контракт `/v1/predict` и появление строки именно этого запроса в PostgreSQL.

Запись лога выполняется через BackgroundTask, поэтому smoke использует ограниченный polling до 20 секунд, а не фиксированный `sleep`. Финальный run [`44927196447`](https://github.com/SuperStas22/mlpro/actions/runs/44927196447) завершил `tests`, `build`, `deploy` и smoke test успешно.

![Зелёный CI/CD ДЗ 3](docs/screens/hw3-ci-success.png)

### 7. HPA и нагрузка

Metrics Server установлен chart `metrics-server` 3.14.0 с `--kubelet-insecure-tls`, необходимым для самоподписанного kubelet-сертификата kind. HPA держит от 2 до 6 реплик и целится в 60% CPU от request 100m.

| Пользователи | Максимум реплик | p95 `/v1/predict` | Максимум CPU/pod | Ошибки |
|---:|---:|---:|---:|---:|
| 5 | 4 | 14 мс | 176m | 0% |
| 10 | 6 | 14 мс | 206m | 0% |
| 20 | 6 | 800 мс | 477m | 1,09% POST |

События `SuccessfulRescale` зафиксировали рост сначала до 4, затем до 6 реплик. После остановки нагрузки CPU упал до 2%, но возврат с 6 до 2 произошёл примерно через 5 минут 50 секунд из-за окна стабилизации scale-down. Пиковая память составила 218Mi; request увеличен с 256Mi до 320Mi, то есть до пика плюс примерно треть запаса. Полный протокол: [`docs/hpa-results.md`](docs/hpa-results.md).

### 8. Ответы на восемь вопросов

1. `tests` и `build` не требуют доступа к домашней сети, поэтому выполняются на изолированных GitHub-hosted runner. Локальный kind находится за NAT и недоступен входящему соединению из GitHub; альтернативы — публичный API Kubernetes, VPN/tunnel или GitOps-агент внутри сети. Self-hosted runner выбран потому, что сам устанавливает исходящее соединение с GitHub и уже находится рядом с кластером.

2. `--network kind` даёт runner DNS и сетевой путь до `logp-control-plane`; без него smoke и внутренний kubeconfig не достигнут узел. Docker socket нужен для `docker pull`, `kind load` и управления контейнером kind. `--group-add 0` добавляет процесс runner в группу сокета с GID 0; без этого Docker CLI получает `permission denied`.

3. Обычный `kubectl create secret` работает только один раз и на втором deploy завершается с `AlreadyExists`. `--dry-run=client -o yaml | kubectl apply -f -` формирует декларативный Secret и идемпотентно создаёт или обновляет его.

4. `challenger` — последняя проверяемая версия, а `champion` — версия, прошедшая гейт и используемая production-сервисом. Алиас позволяет переключить модель без изменения конфигурации и образа; номер версии пришлось бы менять при каждом выпуске. Откат алиаса меняет модель после restart pod, а `rollout undo` возвращает весь предыдущий шаблон Deployment и образ кода.

5. Если `champion` ещё не существует, приложение упадёт при startup на запросе к Registry. В k9s будет `CrashLoopBackOff`, readiness останется false; CI остановится на `kubectl rollout status`, а `--previous`-лог покажет `Registered Model` или alias not found.

6. Браузер идёт на host port 80, проброшенный kind в node port 30080, затем в Traefik, по Ingress — в Service MLflow:5000 и pod MLflow:5000. `allowed-hosts` разрешает нужный Host header, а `cors-allowed-origins` разрешает браузерные запросы UI с `http://mlflow.localhost`. Проброс порта задаётся при создании node-контейнера kind; существующему контейнеру Docker нельзя добавить port mapping.

7. При 10 пользователях перед последним масштабированием было 5 реплик и 111% CPU при цели 60%: `ceil(5 × 111 / 60) = 10`, но `maxReplicas=6`, поэтому HPA выставил 6 — как и наблюдалось. Вверх контроллер реагировал за интервалы сбора метрик, вниз ждал около 5 минут 50 секунд из-за окна стабилизации, чтобы не дёргать реплики на коротких провалах.

8. Git хранит код, `.dvc`-указатель с MD5 и конфигурацию remote; DVC storage хранит байты CSV. Для версии модели N нужно открыть её run в MLflow, взять `data_md5`, найти Git-коммит с таким MD5 в `.csv.dvc`, checkout этого указателя и выполнить `dvc pull`/`dvc checkout`. Полученный файл проверяется тем же MD5, поэтому восстанавливаются именно обучающие данные версии N.

### 9. Журнал проблем ДЗ 3

1. Новая реплика попала в CrashLoopBackOff после первого CI deploy. В kubectl logs --previous приложение завершалось на db.init() с `password authentication failed for user postgres`. Workflow обновил logp-secrets, но существующий PostgreSQL был ранее инициализирован с другим паролем: смена Secret не меняет пароль внутри уже созданной БД. Сравнение SHA-256 без вывода значений подтвердило несовпадение. GitHub Secret DB_PASSWORD синхронизирован с паролем работающего PostgreSQL, после чего повторный main-run успешно заменил обе реплики. Старые pod оставались Ready, поэтому сервис во время диагностики отвечал.


---

## Отчёт по ДЗ 2: CI/CD

### Чекпоинты

| Пункт | Ссылка |
|---|---|
| Зелёный pipeline `tests -> build -> deploy` | [Actions run 43630510183](https://github.com/SuperStas22/mlpro/actions/runs/43630510183) |
| GHCR-образ с SHA-тегами | [package `mlpro`](https://github.com/SuperStas22/mlpro/pkgs/container/mlpro), финальный тег `sha-2a8297925ad713cb97431a4c159d6d0f6d92ba28` |
| Pull request: красный тест, затем зелёный | [PR #1](https://github.com/SuperStas22/mlpro/pull/1), [красный](https://github.com/SuperStas22/mlpro/actions/runs/43616073692), [зелёный](https://github.com/SuperStas22/mlpro/actions/runs/43616318074) |
| Конфиг: неверный `MODEL_PATH` | [красный](https://github.com/SuperStas22/mlpro/actions/runs/43618595619), [зелёный](https://github.com/SuperStas22/mlpro/actions/runs/43626012742) |
| Secret: неверный `secretRef` | [красный](https://github.com/SuperStas22/mlpro/actions/runs/43626437640), [зелёный](https://github.com/SuperStas22/mlpro/actions/runs/43627794053) |
| Ресурсы: невозможный memory request | [красный](https://github.com/SuperStas22/mlpro/actions/runs/43628261838), [зелёный](https://github.com/SuperStas22/mlpro/actions/runs/43630510183) |

### Три красных прогона

1. **Конфиг.** Красным стал job `deploy`, шаг `Deploy service`: rollout не завершился за 180 секунд. В диагностике поды перезапускались, а в логах был FileNotFoundError для artifact/missing-model.joblib: приложение падало в lifespan при загрузке модели. Статус подов CrashLoopBackOff

2. **Secret.** Красным стал job `deploy`, шаг `Deploy service`. Под был назначен на узел, но остался в CreateContainerConfigError с Restart Count: 0: контейнер не запускался. kubectl describe показал обязательный secretRef на отсутствующий logp-secret-missing

3. **Ресурсы.** Красным стал job `deploy`, шаг `Deploy service`. Поды остались в Pending, Node был пустой, а PodScheduled=False. В Events scheduler напечатал 0/1 nodes are available: 1 Insufficient memory, то есть ни один узел не мог удовлетворить memory request

### Ответы на семь вопросов

1. В [первом build](https://github.com/SuperStas22/mlpro/actions/runs/43617157255) шёл 94 секунды, а в [следующем](https://github.com/SuperStas22/mlpro/actions/runs/43618005357) 58 секунд. Из кэша взят слой RUN uv sync --frozen --no-dev --no-install-project, потому что перед ним Dockerfile копирует только неизменившиеся pyproject.toml и uv.lock; код копируется позже и не сбрасывает кэш зависимостей

2. Поды в ImagePullBackOff появляются между kubectl apply и kubectl set image: первый ReplicaSet ещё пытается запустить placeholder-образ logp-service:1.0, которого нет в registry узла. Затем set image создаёт актуальный ReplicaSet с загруженным SHA-образом, и rollout успешно завершается, поэтому старые поды не делают job красным

3. Пароль задаётся в Settings -> Secrets and variables -> Actions как DB_PASSWORD. GitHub подставляет его в env шага Create application secret, kubectl create secret создаёт logp-secrets, а secretRef передаёт DATABASE_URL в env контейнера. В ConfigMap пароль класть нельзя: его значение будет обычным открытым текстом в манифесте и Git-истории

4. Если убрать needs: tests, build сможет начаться параллельно с тестами. При сломанной валидации или ошибке логирования образ успеет попасть в GHCR до падения pytest, следующий deploy может выкатить заведомо непроверенный код

5. На pull request выполняется только tests, потому что у build стоит if: github.ref == 'refs/heads/main'. deploy зависит от пропущенного build. Так PR быстро проверяется без публикации лишних образов и без выката неслитого кода

6. pg_advisory_xact_lock(7001) сериализует инициализацию схемы на время транзакции. Без него две Kubernetes-реплики API, одновременно запущенные на пустой базе, могут одновременно выполнять DDL и создать гонку, сейчас вторая реплика ждёт коммита первой

7. Порядок по жизни пода: Pending -> CreateContainerConfigError -> CrashLoopBackOff. В Pending scheduler ещё не нашёл узел, при CreateContainerConfigError узел уже назначен, но kubelet не может собрать env из Secret; в CrashLoopBackOff контейнер уже запускался, но падает, а Kubernetes увеличивает паузу между перезапусками

### Звёздочки

**Быстрее.** В [первом build](https://github.com/SuperStas22/mlpro/actions/runs/43617157255) job занял 94 секунды, а Docker build  77 секунд при 0% кэша. В [финальном прогоне](https://github.com/SuperStas22/mlpro/actions/runs/43630510183) job build занял 23 секунды, сама сборка  6 секунд при 44% кэша. Выигрыш дали GHA-кэш BuildKit и порядок Dockerfile: lock-файлы копируются и зависимости ставятся до копирования часто меняющегося src/

**Диагностика богаче.** Шаг Diagnostics печатает поды, describe, отсортированные Events, текущие и previous-логи контейнера. Его вывода хватило, чтобы различить [падение приложения](https://github.com/SuperStas22/mlpro/actions/runs/43618595619), [отсутствующий Secret](https://github.com/SuperStas22/mlpro/actions/runs/43626437640) и [отказ scheduler](https://github.com/SuperStas22/mlpro/actions/runs/43628261838)

### Журнал проблем

1. После обновления зависимостей TestClient зависал на lifespan. В lock-файле оказались FastAPI 0.162.2 и Starlette 1.10.0, а Starlette предупреждала о deprecated fallback на httpx. Добавил httpx2 в dev-зависимости и обновил uv.lock, в CI все 10 тестов проходят

2. Локальный integration-запуск первоначально пытался подключиться к localhost:5432, но compose-база не публиковала этот порт на host. Для локальной проверки использовал адрес контейнера, в Actions-сервисе порт явно опубликован как 5432:5432

---

**Отчёт по ДЗ 1**  
**Чекпоинты базовой части**  
**pytest**: 8 тестов, все зелёные.  
![pytest](docs/screens/tests.png)

**SELECT из таблицы логов** после `docker compose up`: в таблице видно и успешные запросы, и 422.  
![select](docs/screens/bad_request.png)

**kind**: kubectl get deploy,pods с 2/2 Running и ответ `/v1/predict` через port-forward.  
![kind](docs/screens/req_for_k8s.png)

**k9s** с подами сервиса.  
![k9s](docs/screens/k9s.png)

**Журнал проблем – тут тольок звездочки, можно не смотреть**  
**1. Нагрузка упёрлась в 46 RPS, а время самой модели выросло в 18 раз.**  
   
 Первый прогон locust: при 50 пользователях медиана 840 мс, при 100 пользователях 2 с, RPS не растёт.  
   
 Медиана `latency_ms` из таблицы логов (а это только сборка DataFrame и `predict`, без сети и очереди) была \~47 мс  
   
 в прогоне на 10 пользователей и \~850 мс в прогонах на 50 и 100. Значит, тормозит сама модель, а не очередь перед ней.  
   
 `threadpoolctl.threadpool_info()` в контейнере показал `libgomp` с `num_threads: 32`: `HistGradientBoostingRegressor`  
   
 на каждый `predict` поднимает OpenMP на все ядра машины, а uvicorn выполняет до 40 запросов параллельно в пуле потоков.  
   
 Получается 40 × 32 потоков на 32 ядра, и они мешают друг другу.  
   
 Починил: `ENV OMP_NUM_THREADS=1` в Dockerfile, параллелим запросами, а не внутри одного предсказания.  
   
 Заодно уменьшил модель: 300 деревьев с `learning_rate=0.1` вместо 600 с 0.05 дают тот же R² (0.879 против 0.880),  
   
 а одна строка предсказывается за 3 мс вместо 5,4. Итог: 146 RPS вместо 46, медиана при 10 пользователях 7 мс вместо 46.  
   
 Сырые CSV до исправления лежат в `docs/loadtest/before_omp/`.  
**2. Скрипт замера батча получал `HTTP Error 502: Bad Gateway`.**  
   
 На машине в окружении `http_proxy=http://127.0.0.1:2080`, а в `no_proxy` записано `127.0.0.1/8`.  
   
 `requests` (на нём locust) понимает CIDR и идёт напрямую, `urllib` нет: он отправил запрос в прокси, а тот ответил 502.  
   
 После обхода прокси всплыло второе: одна строка с клиента занимала 64 мс при 5,7 мс на сервере.  
   
 `http.client` отправляет заголовки и тело двумя пакетами, и связка Nagle + delayed ACK добавляет \~40 мс.  
   
 Перешёл на `httpx.Client(trust_env=False)` с keep-alive: 6,4 мс.  
**3. Предупреждение в выводе pytest.** Starlette пишет `Using httpx with starlette.testclient is deprecated`.  
   
 Фильтр `ignore::DeprecationWarning` не сработал: это `StarletteDeprecationWarning`, наследник `UserWarning`.  
   
 Отфильтровал по тексту сообщения в `pyproject.toml`; на работу `TestClient` это не влияет.  
**4. Не ошибки, но выглядят как ошибки.**  
   
 `docker build` пишет `DEPRECATED: The legacy builder is deprecated`: на этой машине нет плагина buildx, сборка  
   
 идёт классическим сборщиком и работает. `kubectl rollout undo` предупреждает про `last-applied-configuration`:  
   
 откат меняет деплоймент в обход `kubectl apply`, после отката образ снова 1.0, как в манифесте, так что  
   
 следующий `kubectl apply -f k8s/` ничего не сломает.  
**Звёздочка 1: нагрузочное тестирование**  
`locustfile.py`: пользователь с паузой 0,1–0,5 с, POST `/v1/predict` с весом 10 (ибупрофен с немного изменёнными  
   
 дескрипторами, чтобы запросы различались) и GET `/health` с весом 1. Нагрузка на compose-версию, команды как в задании,  
   
 CSV в `docs/loadtest/`. Латентность в таблице для `/v1/predict`, RPS суммарный.  
  
|  |  |  |  |  |  |  
| - | - | - | - | - | - |  
| **Пользователи** |  **RPS** |  **median, мс** |  **p95, мс** |  **max, мс** |  **Ошибки** |  
| 10 |  32,2 |  7 |  17 |  108 |  0 % |  
| 50 |  138,0 |  46 |  120 |  230 |  0 % |  
| 100 |  145,8 |  380 |  540 |  835 |  0 % |  
  
   
До исправления OpenMP (проблема 1), для сравнения:  
  
|  |  |  |  |  |  |  
| - | - | - | - | - | - |  
| **Пользователи** |  **RPS** |  **median, мс** |  **p95, мс** |  **max, мс** |  **Ошибки** |  
| 10 |  28,1 |  46 |  98 |  240 |  0 % |  
| 50 |  45,9 |  840 |  940 |  1184 |  0 % |  
| 100 |  45,5 |  2000 |  2200 |  2508 |  0 % |  
  
   
Выводы. При 10 пользователях сервис почти простаивает: они просят \~32 RPS, и все получают. При 50 пользователях спрос  
   
 (\~140 RPS) сравнялся с пропускной способностью, появилась очередь: медиана выросла с 7 до 46 мс, p95 оторвался до 120 мс.  
   
 От 50 к 100 пользователям RPS почти не вырос (138 → 146): сервис это один процесс uvicorn, и почти весь путь запроса  
   
 (pydantic, pandas, обход 300 деревьев) держит GIL. По `docker stats` под нагрузкой контейнер занимает 1,2–1,4 ядра  
   
 из 32, на запрос выходит \~7 мс, отсюда потолок \~145 RPS. Всё, что сверху, становится  
   
 ожиданием в очереди: по закону Литтла 100 / 146 − 0,3 с паузы ≈ 0,38 с, ровно медиана. Ошибок нет ни в одном прогоне:  
   
 запросы ждут, но не отваливаются. Дальше масштабироваться надо процессами (`uvicorn --workers N`) или репликами.  
**Звёздочка 2: батч-эндпоинт**  
`POST /v1/predict/batch`: `rows: list[Features]` от 1 до 1000, все строки собираются в один DataFrame,  
   
 модель вызывается один раз. Замер: `uv run python scripts/bench_batch.py`, медиана из 15 повторов на compose-версии  
   
 (результат в `docs/loadtest/batch.txt`).  
  
|  |  |  |  
| - | - | - |  
|   |  **latency_ms (сервис)** |  **wall, мс (клиент)** |  
| 1 строка |  4,83 |  6,42 |  
| 500 строк |  21,81 |  29,99 |  
  
   
500 строк дороже одной всего в 4,5 раза: \~44 мкс на строку против 4,8 мс на одиночный запрос. Почти всё время  
   
 одиночного запроса это фиксированная плата за вызов: сборка DataFrame, проверки sklearn в пайплайне и проход Python-кода  
   
 по 300 деревьям, а сам спуск строки по дереву в Cython занимает наносекунды, поэтому каждая следующая строка добавляет  
   
 лишь \~34 мкс.  
**Звёздочка 3: выкат новой версии и откат**  
Видимое отличие 1.1: поле `app_version` в `/health`. Версия задаётся при сборке (`ARG APP_VERSION` в Dockerfile),  
   
 код тот же.  
```  
docker build --build-arg APP_VERSION=1.1 -t logp-service:1.1 .  
 kind load docker-image logp-service:1.1 --name logp  
 kubectl set image deploy/logp-service api=logp-service:1.1  
 kubectl annotate deploy/logp-service kubernetes.io/change-cause="1.1: app_version в /health" --overwrite  
 kubectl rollout status deploy/logp-service  
 kubectl rollout undo deploy/logp-service  
 kubectl rollout history deploy/logp-service  
   
```  
```  
REVISION  CHANGE-CAUSE  
 2         1.1: app_version в /health  
 3         1.0: базовая версия  
   
```  
Чтобы проверить, что сервис не замолкал, внутри кластера работал под-пробник: 10 раз в секунду GET `/health`  
   
 через Service (через port-forward так не проверить: он привязан к одному поду и рвётся, когда этот под удаляют).  
```  
kubectl run probe --image=logp-service:1.0 --image-pull-policy=Never --restart=Never --command -- python -c "  
 import json, time, urllib.request  
 while True:  
     try:  
         with urllib.request.urlopen('http://logp-service/health', timeout=2) as r:  
             print(time.strftime('%H:%M:%S'), r.status, json.load(r)['app_version'], flush=True)  
     except Exception as e:  
         print(time.strftime('%H:%M:%S'), 'ERR', type(e).__name__, e, flush=True)  
     time.sleep(0.1)  
 "  
   
```  
За время выката и отката пробник получил около тысячи ответов, ни одной ошибки (`docs/rollout/probe.log`).  
   
 Во время выката поды менялись по одному (`docs/rollout/pods_watch.txt`): рядом с двумя старыми поднимался новый,  
   
 проходил readiness на `/ready`, и только после этого один старый уходил в Terminating; так дважды. Около пяти секунд  
   
 пробник получал вперемешку 1.0 и 1.1, потом только 1.1. Откат вернул прежний ReplicaSet с образом 1.0:  
   
 в истории он стал ревизией 3, а ревизия 1 исчезла, потому что это тот же шаблон пода.  
   
 Сервис не молчал, потому что `maxUnavailable: 0` не даёт убрать старый под, пока новый не готов, readiness-проба  
   
 не пускает трафик в под до загрузки модели, а `preStop: sleep 5` держит уходящий под живым, пока Service убирает его  
   
 из эндпоинтов.  
