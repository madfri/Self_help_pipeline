#!/usr/bin/env python3
"""
Downstream Worker: formatter.json
==================================
A lightweight FastAPI HTTP server that acts as the business logic container
for the final JSON formatting stage of the pipeline.

Endpoints:
  POST /process  - Receives the JSON envelope, applies final formatting,
                   and returns the completed envelope.
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
    format="%(asctime)s | %(levelname)-8s | formatter-json | %(message)s",
)
logger = logging.getLogger("formatter-json")

app = FastAPI(title="JSON Formatter Worker")


def format_output(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """
    Final formatting stage: normalize the envelope into a clean output schema.
    In production, this might validate against a JSON Schema, compress, or
    partition the output for the data warehouse.
    """
    result = dict(envelope)

    formatter_meta = {
        "formatted_at": int(time.time() * 1000),
        "formatter_version": "1.0.0",
        "output_schema": "pcap-decoded-v2",
        "stage": "formatter.json",
    }

    result["formatter_metadata"] = formatter_meta
    result["pipeline_status"] = "formatted"

    # Clean up any transient routing fields if desired
    # result.pop("itinerary", None)  # optionally remove after completion

    logger.info(
        "Formatting complete for fingerprint=%s | next_queue=pipeline.completed",
        result.get("fingerprint"),
    )
    return result


@app.post("/process")
async def process(request: Request) -> JSONResponse:
    """Receive envelope, format, and return."""
    try:
        body = await request.body()
        envelope: Dict[str, Any] = json.loads(body.decode("utf-8"))
        logger.info("Received envelope for final formatting")

        updated = format_output(envelope)

        return JSONResponse(content=updated, status_code=200)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON: %s", exc)
        return JSONResponse(content={"error": "Invalid JSON"}, status_code=400)
    except Exception as exc:
        logger.exception("Formatting error: %s", exc)
        return JSONResponse(content={"error": str(exc)}, status_code=500)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(content={"status": "alive"})


@app.get("/ready")
async def ready() -> JSONResponse:
    return JSONResponse(content={"status": "ready"})


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="info")
