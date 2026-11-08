**logp-service**  
   
   
   Сервис предсказывает липофильность молекулы, logP (октанол/вода), по 14 RDKit-дескрипторам.  
    задания со звездачками смотреть не нужно, я сам не понял, как они работают, тяжко без их наличия на семинаре  

    Модель: градиентный бустинг `HistGradientBoostingRegressor` из scikit-learn, обучен на \~14 тыс. молекул из моего проекта logP-Prediction.  

    Ноутбук обучения:   
    `notebooks/train.ipynb`,  

    отчёт по ДЗ: `README.md`, report - не нужно, картинки в docs/screen  

   Нужны `uv`, Docker с compose v2, `kind` и `kubectl`. Порты 8000 и 8080 должны быть свободны.  
   Проверка: три команды  
```  
# 1. Тесты        
    uv sync && uv run pytest        
```  
```  
# 2. Compose: сервис + Postgres, запрос к модели и SELECT из таблицы логов        
    docker compose up -d --build --wait \
  && curl -s -X POST http://127.0.0.1:8000/v1/predict -H 'Content-Type: application/json' -d @good.json && echo \
  && sleep 1 && docker compose exec db psql -U postgres -d logp -c "SELECT request_id, ts, model_version, prediction, latency_ms, status_code FROM predictions ORDER BY ts DESC LIMIT 5"     
```  
```  
# 3. kind: кластер, образ, манифесты, rollout, ответ модели через port-forward        
     kind create cluster --name logp && kubectl config use-context kind-logp \
  && docker build -t logp-service:1.0 . && kind load docker-image logp-service:1.0 --name logp \
  && kubectl apply -f k8s/ && kubectl rollout status deploy/logp-service --timeout=180s \
  && kubectl get deploy,pods -l app=logp \
  && { kubectl port-forward svc/logp-service 8080:80 >/dev/null & PF=$!; sleep 3; \
       curl -s -X POST http://127.0.0.1:8080/v1/predict -H 'Content-Type: application/json' -d @good.json; echo; kill $PF; }     
```  
    3 команду помог доофрмить чатгпт, потому что я мудрил с отступами  и получалось запустить только отдельными командами (в целом работает и без sleep, но я оставил)  
   
   Уборка после проверки: `docker compose down -v && kind delete cluster --name logp`.  
   
   Пример запроса лежит в `good.json`: ибупрофен, экспериментальный logP 3.97.  
```  
{"logp":4.059582599082669,"lipinski_ok":true,"model_version":"hgb-1.0","request_id":"96ad27d2-58cf-4242-8abb-233c7660bd20","latency_ms":7.26}  
```  
**Схема запроса**  
   
   `extra="forbid"`: лишнее поле даёт 422. Границы взяты с запасом относительно обучающих данных.  
  
|  |  |  |  |  
| - | - | - | - |  
|   |    |    |    |  
|   |    |    |    |  
|   |    |    |    |  
| **Поле** |  **Тип** |  **Границы** |  **Смысл** |  
| `MolWt` |  float |  0 < x ≤ 2000 |  молекулярная масса, г/моль |  
| `HeavyAtomCount` |  int |  1..200 |  тяжёлые атомы |  
| `NumHeteroatoms` |  int |  0..200 |  атомы кроме C и H |  
| `fr_halogen` |  int |  0..100 |  атомы галогенов |  
| `NumHDonors`, `NumHAcceptors` |  int |  0..50, 0..100 |  доноры и акцепторы H-связи |  
| `TPSA` |  float |  0..1000 |  топологическая полярная площадь поверхности, Å² |  
| `MolMR` |  float |  0..1000 |  молярная рефракция |  
| `NumRotatableBonds` |  int |  0..200 |  вращающиеся связи |  
| `RingCount`, `NumAromaticRings` |  int |  0..50 |  все циклы и ароматические |  
| `FractionCSP3` |  float |  0..1 |  доля sp3-углерода |  
| `MaxPartialCharge`, `MinPartialCharge` |  float, **опционально** |  −1..1 |  заряды Гастайгера |  

   Кроме границ, схема проверяет согласованность  
    счётчиков: `NumAromaticRings ≤ RingCount`, `fr_halogen ≤ NumHeteroatoms ≤ HeavyAtomCount`, `MinPartialCharge ≤ MaxPartialCharge`  
