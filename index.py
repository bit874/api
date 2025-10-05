from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Any
import json, os, math

# --- FastAPI app (ASGI) ---
app = FastAPI(title="eShopCo Telemetry Metrics")

# CORS: allow POST from any origin (preflight handled by middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["*"],
)

# ---- Data loading (at cold start) ----
DATA_PATHS = [
    os.path.join("data", "telemetry.json"),
    os.path.join(os.path.dirname(__file__), "..", "data", "telemetry.json"),
]

def coerce_uptime(v):
    """Return uptime as float in [0,1]. Accepts bool, 0/1, %, or 0..1."""
    if v is None:
        return None
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    try:
        f = float(v)
    except Exception:
        return None
    # If it's a percentage, scale down
    if f > 1.0:
        # treat like percent if in [0,100]
        return max(0.0, min(1.0, f / 100.0))
    return max(0.0, min(1.0, f))

def load_records():
    path = next((p for p in DATA_PATHS if os.path.exists(p)), None)
    if not path:
        raise FileNotFoundError(
            "Expected data/telemetry.json next to the project root. "
            "Please add the sample bundle there."
        )
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            region = (row.get("region") or "").strip().lower()
            lat = row.get("latency_ms") or row.get("latency")
            up = row.get("uptime") if "uptime" in row else row.get("up") or row.get("is_up")
            uptime = coerce_uptime(up)
            try:
                lat = float(lat)
            except Exception:
                continue
            if region:
                records.append({"region": region, "latency_ms": lat, "uptime": uptime})
    if not records:
        raise RuntimeError("No usable telemetry rows found in telemetry.json.")
    return records

RECORDS = load_records()

# ---- Models ----
class MetricsRequest(BaseModel):
    regions: List[str] = Field(..., description="region slugs, e.g., ['apac','emea']")
    threshold_ms: float = Field(..., gt=0)

# ---- Helpers ----
def mean(values):
    return float(sum(values) / len(values)) if values else 0.0

def percentile(values, q):
    """Nearest-rank percentile (no numpy). q in [0,100]."""
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, math.ceil((q / 100.0) * len(s)) - 1))
    return float(s[k])

def compute_for_region(region: str, threshold_ms: float) -> Dict[str, float]:
    region = region.lower().strip()
    latencies = [r["latency_ms"] for r in RECORDS if r["region"] == region]
    uptimes = [r["uptime"] for r in RECORDS if r["region"] == region and r["uptime"] is not None]

    return {
        "avg_latency": round(mean(latencies), 4),
        "p95_latency": round(percentile(latencies, 95), 4),
        "avg_uptime": round(mean(uptimes) if uptimes else 0.0, 6),
        "breaches": int(sum(1 for v in latencies if v > threshold_ms)),
    }

# ---- Route ----
# IMPORTANT: keep the path "/" so Vercel exposes it at /api/metrics
@app.post("/")
def post_metrics(body: MetricsRequest) -> Dict[str, Any]:
    if not body.regions:
        raise HTTPException(400, "regions must be a non-empty list")
    out = {}
    for r in body.regions:
        out[r] = compute_for_region(r, body.threshold_ms)
    return {"regions": out}
