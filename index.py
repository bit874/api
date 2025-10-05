from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Any
from pathlib import Path
import json, math

app = FastAPI(title="eShopCo Telemetry Metrics")

# CORS: allow POST from any origin (preflight covered)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)

# ---------- File discovery ----------

def find_data_file() -> Path:
    """
    Look for either telemetry.jsonl (JSON Lines) or telemetry.json (array JSON)
    in typical locations for Vercel packaging.
    """
    here = Path(__file__).resolve().parent
    candidates = [
        Path("data/telemetry.jsonl"),
        Path("data/telemetry.json"),
        here / "data" / "telemetry.jsonl",
        here / "data" / "telemetry.json",
        here.parent / "data" / "telemetry.jsonl",
        here.parent / "data" / "telemetry.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Expected data/telemetry.json or data/telemetry.jsonl next to the project root. "
        "Make sure the file exists and vercel.json has includeFiles: \"data/**\"."
    )

# ---------- Parsing & metrics ----------

def coerce_uptime(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    try:
        f = float(v)
    except Exception:
        return None
    if f > 1.0:  # treat 0..100 as percent
        return max(0.0, min(1.0, f / 100.0))
    return max(0.0, min(1.0, f))

def load_records():
    path = find_data_file()
    records = []

    if path.suffix == ".jsonl":
        # JSON Lines
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                _ingest_row(row, records)
    else:
        # Array JSON
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and "records" in data:
                data = data["records"]
            if not isinstance(data, list):
                raise RuntimeError("telemetry.json must contain a JSON array of rows.")
            for row in data:
                _ingest_row(row, records)

    if not records:
        raise RuntimeError("No usable telemetry rows found in telemetry file.")
    return records

def _ingest_row(row, records):
    region = (row.get("region") or "").strip().lower()
    lat = row.get("latency_ms") if "latency_ms" in row else row.get("latency")
    up  = row.get("uptime")
    if up is None:
        up = row.get("up", row.get("is_up"))
    uptime = coerce_uptime(up)
    try:
        lat = float(lat)
    except Exception:
        return
    if region:
        records.append({"region": region, "latency_ms": lat, "uptime": uptime})

RECORDS = load_records()

def mean(values):
    return float(sum(values) / len(values)) if values else 0.0

def percentile(values, q):
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, math.ceil((q / 100.0) * len(s)) - 1))
    return float(s[k])

def compute_for_region(region: str, threshold_ms: float) -> Dict[str, float]:
    r = region.lower().strip()
    latencies = [x["latency_ms"] for x in RECORDS if x["region"] == r]
    uptimes = [x["uptime"] for x in RECORDS if x["region"] == r and x["uptime"] is not None]
    return {
        "avg_latency": round(mean(latencies), 4),
        "p95_latency": round(percentile(latencies, 95), 4),
        "avg_uptime": round(mean(uptimes) if uptimes else 0.0, 6),
        "breaches": int(sum(1 for v in latencies if v > threshold_ms)),
    }

# ---------- Request/Response ----------

class MetricsRequest(BaseModel):
    regions: List[str] = Field(..., min_items=1)
    threshold_ms: float = Field(..., gt=0)

@app.post("/")
def post_metrics(body: MetricsRequest) -> Dict[str, Any]:
    out = {}
    for r in body.regions:
        out[r] = compute_for_region(r, body.threshold_ms)
    return {"regions": out}
