"""Обучить регрессию logP, зарегистрировать её в MLflow и применить MAE-гейт.

Пример первого запуска:
    MLFLOW_TRACKING_URI=http://mlflow.localhost uv run python -m logp.train

Каждая новая версия получает алиас ``challenger``. Алиас ``champion`` переносится
на неё только при улучшении MAE не меньше чем на ``GATE_MIN_GAIN``.
"""

import hashlib
import json
import os
import platform
from datetime import UTC, datetime
from pathlib import Path

import matplotlib.pyplot as plt
import mlflow
import mlflow.sklearn
import pandas as pd
import sklearn
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

DATA_PATH = Path(os.getenv("DATA_PATH", "data/logP-14000.csv"))
MODEL_NAME = os.getenv("MODEL_NAME", "logp-model")
EXPERIMENT = os.getenv("MLFLOW_EXPERIMENT", "logp-training")
MAX_ITER = int(os.getenv("MAX_ITER", "300"))
MIN_GAIN = float(os.getenv("GATE_MIN_GAIN", "0.01"))

SEED = 42
THRESHOLD = 5.0
SKOPS_TRUSTED = [
    "numpy.dtype",
    "sklearn.compose._column_transformer._RemainderColsList",
    # Модель обучена этим процессом, поэтому доверяем её внутреннему представлению деревьев.
    "sklearn.ensemble._hist_gradient_boosting.predictor.TreePredictor",
]

FEATURES = [
    "MolWt",
    "HeavyAtomCount",
    "NumHeteroatoms",
    "fr_halogen",
    "NumHDonors",
    "NumHAcceptors",
    "TPSA",
    "MolMR",
    "NumRotatableBonds",
    "RingCount",
    "NumAromaticRings",
    "FractionCSP3",
    "MaxPartialCharge",
    "MinPartialCharge",
]


def file_md5(path: Path) -> str:
    """Вернуть MD5 содержимого — тот же идентификатор версии, который хранит DVC."""
    return hashlib.md5(path.read_bytes()).hexdigest()


def load_and_validate(path: Path) -> pd.DataFrame:
    """Загрузить датасет и проверить минимальный контракт обучения."""
    frame = pd.read_csv(path).rename(columns={"Kow": "logP"})
    required = set(FEATURES + ["SMILES", "logP"])
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"в данных нет колонок: {sorted(missing)}")
    if len(frame) < 1000:
        raise ValueError(f"слишком мало строк: {len(frame)}")
    if frame["logP"].isna().any():
        raise ValueError("target logP содержит пропуски")

    # Одна молекула не должна одновременно оказаться и в train, и в holdout.
    return frame.drop_duplicates("SMILES").reset_index(drop=True)


def build_pipeline(max_iter: int) -> Pipeline:
    """Построить тот же sklearn Pipeline, контракт которого использует API."""
    preprocessing = ColumnTransformer(
        [("numeric", SimpleImputer(strategy="median"), FEATURES)],
    )
    model = HistGradientBoostingRegressor(
        max_iter=max_iter,
        learning_rate=0.1,
        max_leaf_nodes=31,
        l2_regularization=1.0,
        early_stopping=False,
        random_state=SEED,
    )
    return Pipeline([("preprocessing", preprocessing), ("model", model)])


def champion_mae(client: MlflowClient) -> tuple[str | None, float | None]:
    """Получить версию и holdout MAE текущего champion либо пару None."""
    try:
        version = client.get_model_version_by_alias(MODEL_NAME, "champion")
    except MlflowException:
        return None, None
    metric = client.get_run(version.run_id).data.metrics.get("mae")
    return version.version, metric


def prediction_figure(actual: pd.Series, predicted: object):
    """Построить диагностический график: точки должны лежать около диагонали."""
    figure, axis = plt.subplots(figsize=(7, 6))
    axis.scatter(actual, predicted, alpha=0.35, s=14)
    lower = float(min(actual.min(), predicted.min()))
    upper = float(max(actual.max(), predicted.max()))
    axis.plot([lower, upper], [lower, upper], "r--", label="идеальный прогноз")
    axis.set(xlabel="истинный logP", ylabel="предсказанный logP", title="Прогноз на holdout")
    axis.legend()
    figure.tight_layout()
    return figure


def main() -> dict:
    """Обучить, залогировать, зарегистрировать модель и вернуть решение гейта."""
    frame = load_and_validate(DATA_PATH)
    x_train, x_test, y_train, y_test = train_test_split(
        frame[FEATURES],
        frame["logP"],
        test_size=0.2,
        random_state=SEED,
    )

    pipeline = build_pipeline(MAX_ITER).fit(x_train, y_train)
    prediction = pipeline.predict(x_test)
    metrics = {
        "mae": float(mean_absolute_error(y_test, prediction)),
        "rmse": float(root_mean_squared_error(y_test, prediction)),
        "r2": float(r2_score(y_test, prediction)),
    }
    data_md5 = file_md5(DATA_PATH)

    mlflow.set_experiment(EXPERIMENT)
    client = MlflowClient()
    old_version, old_mae = champion_mae(client)

    with mlflow.start_run() as run:
        metadata = {
            "features": FEATURES,
            "threshold": THRESHOLD,
            "target": "logP",
            "data_rows": len(frame),
            "n_train": len(x_train),
            "trained_at": datetime.now(UTC).isoformat(),
            "sklearn": sklearn.__version__,
            "python": platform.python_version(),
        }
        mlflow.log_params(
            {
                "model": "HistGradientBoostingRegressor",
                "max_iter": MAX_ITER,
                "learning_rate": 0.1,
                "max_leaf_nodes": 31,
                "l2_regularization": 1.0,
                "seed": SEED,
                "data": str(DATA_PATH),
                "data_md5": data_md5,
                "gate_min_gain": MIN_GAIN,
            }
        )
        mlflow.log_metrics(metrics)
        mlflow.log_dict(metadata, "metadata.json")

        figure = prediction_figure(y_test, prediction)
        mlflow.log_figure(figure, "prediction_vs_actual.png")
        plt.close(figure)

        model_info = mlflow.sklearn.log_model(
            pipeline,
            name="model",
            registered_model_name=MODEL_NAME,
            skops_trusted_types=SKOPS_TRUSTED,
        )
        version = model_info.registered_model_version

    promoted = old_mae is None or metrics["mae"] < old_mae - MIN_GAIN
    client.set_registered_model_alias(MODEL_NAME, "challenger", version)
    if promoted:
        client.set_registered_model_alias(MODEL_NAME, "champion", version)

    # Решение гейта остаётся видимым в MLflow рядом с параметрами и метриками запуска.
    client.set_tag(run.info.run_id, "gate.promoted", str(promoted).lower())
    client.set_tag(run.info.run_id, "gate.champion_before", old_version or "none")

    result = {
        "run_id": run.info.run_id,
        "version": version,
        "mae": round(metrics["mae"], 4),
        "data_md5": data_md5,
        "champion_before": old_version,
        "champion_mae_before": old_mae,
        "min_gain": MIN_GAIN,
        "promoted": promoted,
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    main()
