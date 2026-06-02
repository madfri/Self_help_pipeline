#!/usr/bin/env python3
"""
Downstream Worker: enrichment.geoip
====================================
A lightweight FastAPI HTTP server that acts as the business logic container
for the GeoIP enrichment stage of the pipeline.

Endpoints:
  POST /process  - Receives the JSON envelope, enriches with mock GeoIP data,
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
    format="%(asctime)s | %(levelname)-8s | enrichment-geoip | %(message)s",
)
logger = logging.getLogger("enrichment-geoip")

app = FastAPI(title="GeoIP Enrichment Worker")


def enrich_geoip(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mock GeoIP enrichment: add geographic metadata based on a mock IP lookup.
    In production, this would call MaxMind GeoIP2 or a similar database.
    """
    result = dict(envelope)

    # Mock enrichment logic
    geoip_data = {
        "source_country": "US",
        "source_city": "Ashburn",
        "source_asn": "AS14618 Amazon Web Services",
        "destination_country": "DE",
        "destination_city": "Frankfurt",
        "destination_asn": "AS16509 Amazon.com, Inc.",
        "enriched_at": int(time.time() * 1000),
        "enrichment_stage": "geoip",
    }

    # Append to an enrichments array (create if absent)
    if "enrichments" not in result:
        result["enrichments"] = []
    result["enrichments"].append(geoip_data)

    logger.info("GeoIP enrichment applied for fingerprint=%s", result.get("fingerprint"))
    return result


@app.post("/process")
async def process(request: Request) -> JSONResponse:
    """Receive envelope, enrich, and return."""
    try:
        body = await request.body()
        envelope: Dict[str, Any] = json.loads(body.decode("utf-8"))
        logger.info("Received envelope for processing")

        updated = enrich_geoip(envelope)

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
