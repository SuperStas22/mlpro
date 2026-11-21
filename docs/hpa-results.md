# HPA load-test results

Замеры выполнены через `http://logp.localhost`, Locust 2.47.0, длительность каждого
прогона 90 секунд. Метрики pod снимались командой `kubectl top pods` каждые пять секунд.

| Users | Replicas (max) | POST `/v1/predict` p95 | CPU/pod (max) | Memory/pod (max) | Errors |
|---:|---:|---:|---:|---:|---:|
| 5 | 4 | 14 ms | 176m | 210Mi | 0% |
| 10 | 6 | 14 ms | 206m | 207Mi | 0% |
| 20 | 6 | 800 ms | 477m | 218Mi | 1.09% POST (40 responses 502) |

События HPA после первого прогона:

```text
SuccessfulRescale  New size: 4; cpu resource utilization above target
SuccessfulRescale  New size: 6; cpu resource utilization above target
```

После остановки нагрузки utilization упал до 2%, но HPA уменьшил число реплик с 6 до 2
примерно через 5 минут 50 секунд из-за стандартного окна стабилизации scale-down.

Память достигала 218Mi. Исходный request 256Mi заменён на 320Mi: это наблюдаемый пик плюс
примерно треть запаса. CPU request оставлен 100m, потому что HPA использует его как базу для
целевых 60%, а limit 1 CPU защищает узел от одной зависшей реплики.
