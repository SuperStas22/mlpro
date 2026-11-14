import time
import uuid
from contextlib import asynccontextmanager

import joblib
import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from starlette.background import BackgroundTask

from logp import db
from logp.config import settings

PREDICT_PATH = "/v1/predict"

## ибупрофен 
EXAMPLE = {
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


# пока делал, сам забыл что есть что - наверное по хорошему,
# на вход в дальнейшем надо подавть молекулу, а не её дескрипторы, там логичнее
class Features(BaseModel):

    model_config = {"extra": "forbid", "json_schema_extra": {"examples": [EXAMPLE]}}

    MolWt: float = Field(gt=0, le=2000, description="молекулярная масса, г/моль")
    HeavyAtomCount: int = Field(ge=1, le=200, description="число тяжёлых атомов")
    NumHeteroatoms: int = Field(ge=0, le=200, description="число атомов кроме C и H")
    fr_halogen: int = Field(ge=0, le=100, description="число атомов галогенов")
    NumHDonors: int = Field(ge=0, le=50, description="доноры водородной связи")
    NumHAcceptors: int = Field(ge=0, le=100, description="акцепторы водородной связи")
    TPSA: float = Field(ge=0, le=1000, description="топологическая полярная площадь поверхности, Å²")
    MolMR: float = Field(ge=0, le=1000, description="молярная рефракция (Crippen)") ## я даже не знаю, что это....
    NumRotatableBonds: int = Field(ge=0, le=200)
    RingCount: int = Field(ge=0, le=50)
    NumAromaticRings: int = Field(ge=0, le=50)
    FractionCSP3: float = Field(ge=0, le=1, description="доля sp3-атомов углерода")
    MaxPartialCharge: float | None = Field(default=None, ge=-1, le=1, description="макс. заряд Гастайгера")
    MinPartialCharge: float | None = Field(default=None, ge=-1, le=1, description="мин. заряд Гастайгера")

    @model_validator(mode="after") ## это пока передаем фичи, а не молеклу 
    def consistent(self): 
        if self.NumAromaticRings > self.RingCount:
            raise ValueError("NumAromaticRings больше RingCount")
        if not self.fr_halogen <= self.NumHeteroatoms <= self.HeavyAtomCount:
            raise ValueError("должно быть fr_halogen <= NumHeteroatoms <= HeavyAtomCount")
        if None not in (self.MinPartialCharge, self.MaxPartialCharge) and self.MinPartialCharge > self.MaxPartialCharge:
            raise ValueError("MinPartialCharge больше MaxPartialCharge")
        return self


class Prediction(BaseModel):
    logp: float = Field(description="предсказанный logP (октанол/вода)")
    lipinski_ok: bool = Field(description="logP <= порога из паспорта модели (правило пяти Липински)")
    model_version: str
    request_id: str
    latency_ms: float


class Batch(BaseModel):
    model_config = {"extra": "forbid"}

    rows: list[Features] = Field(min_length=1, max_length=1000)


class BatchItem(BaseModel):
    logp: float
    lipinski_ok: bool


class BatchPrediction(BaseModel):
    predictions: list[BatchItem]
    model_version: str
    request_id: str
    latency_ms: float


@asynccontextmanager
async def lifespan(app: FastAPI):
    bundle = joblib.load(settings.model_path)
    app.state.pipeline = bundle["pipeline"]
    app.state.meta = bundle["metadata"]
    app.state.version = bundle["metadata"]["model_version"]

    db.init()
    yield
    app.state.pipeline = None


app = FastAPI(
    title="logp-service",
    version=settings.app_version,
    lifespan=lifespan,
    description="Предсказание logP по RDKit-дескрипторам, градиентный бустинг",
)


def predict_frame(rows: list[dict]) -> list[float]:
    frame = pd.DataFrame(rows).reindex(columns=app.state.meta["features"]).astype("float64")
    return [float(v) for v in app.state.pipeline.predict(frame)]


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    request_id = str(uuid.uuid4())
    task = None
    if request.url.path == PREDICT_PATH:
        body = exc.body
        features = body if isinstance(body, (dict, list)) else {"raw": None if body is None else str(body)}
        task = BackgroundTask(db.save_prediction, request_id, features, None, getattr(app.state, "version", "unknown"), None, 422)
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors()), "request_id": request_id}, background=task)


@app.get("/health")
def health():
    return {"status": "ok", "model_version": getattr(app.state, "version", "unknown"), "app_version": settings.app_version}


@app.get("/ready")
def ready():
    if getattr(app.state, "pipeline", None) is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {"status": "ready"}


@app.post(PREDICT_PATH)
def predict(x: Features, bg: BackgroundTasks) -> Prediction:
    t0 = time.perf_counter()
    request_id = str(uuid.uuid4())
    payload = x.model_dump()
    try:
        logp = predict_frame([payload])[0]
    except Exception:
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        task = BackgroundTask(db.save_prediction, request_id, payload, None, app.state.version, latency_ms, 500)
        return JSONResponse(status_code=500, content={"detail": "prediction failed", "request_id": request_id}, background=task)
    latency_ms = round((time.perf_counter() - t0) * 1000, 2)

    bg.add_task(db.save_prediction, request_id, payload, logp, app.state.version, latency_ms, 200)

    return Prediction(
        logp=logp,
        lipinski_ok=logp <= app.state.meta["threshold"],
        model_version=app.state.version,
        request_id=request_id,
        latency_ms=latency_ms,
    )


@app.post(PREDICT_PATH + "/batch")
def predict_batch(batch: Batch) -> BatchPrediction:
    # в таблицу логов батч не пишем: одна строка таблицы = один запрос /v1/predict
    t0 = time.perf_counter()
    values = predict_frame([row.model_dump() for row in batch.rows])
    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    threshold = app.state.meta["threshold"]
    return BatchPrediction(
        predictions=[BatchItem(logp=v, lipinski_ok=v <= threshold) for v in values],
        model_version=app.state.version,
        request_id=str(uuid.uuid4()),
        latency_ms=latency_ms,
    )
