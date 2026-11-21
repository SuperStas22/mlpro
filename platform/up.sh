#!/usr/bin/env bash
# Поднимает минимальную платформу ДЗ 3: kind, MLflow, Traefik и два Ingress.
# Повторный запуск безопасен: существующий кластер и Helm-релиз обновляются на месте.
set -euo pipefail

CLUSTER=${CLUSTER:-logp}
cd "$(dirname "$0")/.."

# Лучше остановиться с понятной ошибкой до частично созданного кластера.
for tool in docker kind kubectl helm; do
  command -v "$tool" >/dev/null || {
    echo "Ошибка: не найдена обязательная команда '$tool'" >&2
    exit 1
  }
done

echo "== kind cluster: $CLUSTER"
if ! kind get clusters | grep -qx "$CLUSTER"; then
  kind create cluster --name "$CLUSTER" --config platform/kind-config.yaml
fi
kubectl config use-context "kind-$CLUSTER" >/dev/null

echo "== MLflow"
kubectl apply -f platform/mlflow.yaml

echo "== Traefik"
helm repo add traefik https://traefik.github.io/charts >/dev/null 2>&1 || true
helm upgrade --install traefik traefik/traefik --version 41.6.0 \
  --namespace traefik --create-namespace \
  --values platform/traefik-values.yaml --wait

echo "== Ingress routes"
kubectl apply -f platform/ingress.yaml

echo "== Waiting for MLflow"
kubectl -n mlops rollout status deployment/mlflow --timeout=5m

echo
echo "MLflow: http://mlflow.localhost"
echo "Service (после деплоя): http://logp.localhost"
