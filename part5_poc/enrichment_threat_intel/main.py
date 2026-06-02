#!/usr/bin/env python3
"""
Downstream Worker: enrichment.threat_intel
===========================================
A lightweight FastAPI HTTP server that acts as the business logic container
for the Threat Intelligence enrichment stage of the pipeline.

Endpoints:
  POST /process  - Receives the JSON envelope, enriches with mock threat intel,
                   and returns the updated envelope.
  GET  /health   - Liveness probe.
  GET  /ready    - Readiness probe.
"""

import json
import logging
import time
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | enrichment-threat-intel | %(message)s",
)
logger = logging.getLogger("enrichment-threat-intel")

app = FastAPI(title="Threat Intel Enrichment Worker")


def enrich_threat_intel(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mock Threat Intelligence enrichment: add IoC and reputation metadata.
    In production, this would query MISP, ThreatConnect, or VirusTotal.
    """
    result = dict(envelope)

    threat_data = {
        "iocs": [
            {"type": "ip", "value": "192.0.2.100", "reputation": "malicious"},
            {"type": "domain", "value": "evil.example.com", "reputation": "suspicious"},
        ],
        "risk_score": 87,
        "category": "c2_communication",
        "enriched_at": int(time.time() * 1000),
        "enrichment_stage": "threat_intel",
    }

    if "enrichments" not in result:
        result["enrichments"] = []
    result["enrichments"].append(threat_data)

    logger.info(
        "Threat intel enrichment applied for fingerprint=%s",
        result.get("fingerprint"),
    )
    return result


@app.post("/process")
async def process(request: Request) -> JSONResponse:
    """Receive envelope, enrich, and return."""
    try:
        body = await request.body()
        envelope: Dict[str, Any] = json.loads(body.decode("utf-8"))
        logger.info("Received envelope for processing")

        updated = enrich_threat_intel(envelope)

        return JSONResponse(content=updated, status_code=200)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON: %s", exc)
        return JSONResponse(content={"error": "Invalid JSON"}, status_code=400)
    except Exception as exc:
        logger.exception("Processing error: %s", exc)
        return JSONResponse(content={"error": str(exc)}, status_code=500)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(content={"status": "alive"})


@app.get("/ready")
async def ready() -> JSONResponse:
    return JSONResponse(content={"status": "ready"})


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="info")
