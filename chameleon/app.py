"""HTTP API for the CHAMELEON design reflow engine."""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from jsonschema import Draft202012Validator

from engine.main import self_check, validate_task
from engine.resize import resize

logger = logging.getLogger(__name__)

MAX_REQUEST_BYTES = 4_000_000
MAX_ELEMENTS = 5_000

with Path(__file__).with_name("chameleon_design_schema_v0.9.json").open(
    encoding="utf-8"
) as schema_file:
    DESIGN_SCHEMA = json.load(schema_file)

DESIGN_VALIDATOR = Draft202012Validator(DESIGN_SCHEMA)
CANVAS_VALIDATOR = Draft202012Validator(DESIGN_SCHEMA["$defs"]["canvas"])

app = FastAPI(
    debug=False,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _parse_finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON numbers must be finite")
    return number


def _reject_nonstandard_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


async def _read_request_body(request: Request) -> bytes:
    length_header = request.headers.get("content-length")
    if length_header is not None:
        try:
            declared_length = int(length_header)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Content-Length must be a non-negative integer.",
            ) from exc
        if declared_length < 0:
            raise HTTPException(
                status_code=400,
                detail="Content-Length must be a non-negative integer.",
            )
        if declared_length > MAX_REQUEST_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Request body exceeds the 4 MB limit.",
            )

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_REQUEST_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Request body exceeds the 4 MB limit.",
            )
        body.extend(chunk)
    return bytes(body)


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    """Return a minimal liveness response."""
    return {"status": "ok"}


@app.post("/api/resize")
async def resize_design(request: Request) -> dict[str, Any]:
    """Validate and reflow one design using the real CHAMELEON engine."""
    raw_body = await _read_request_body(request)
    if not raw_body:
        raise HTTPException(status_code=400, detail="Request body is required.")

    media_type = (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    if media_type != "application/json" and not media_type.endswith("+json"):
        raise HTTPException(
            status_code=415,
            detail="Content-Type must be application/json.",
        )

    try:
        task = json.loads(
            raw_body,
            parse_float=_parse_finite_float,
            parse_constant=_reject_nonstandard_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise HTTPException(
            status_code=400,
            detail="Request body must contain valid JSON.",
        ) from None

    if not isinstance(task, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object.")
    if not isinstance(task.get("source"), dict):
        raise HTTPException(
            status_code=422,
            detail="A 'source' design object is required.",
        )
    if not isinstance(task.get("target_canvas"), dict):
        raise HTTPException(
            status_code=422,
            detail="A 'target_canvas' object is required.",
        )

    elements = task["source"].get("elements")
    if isinstance(elements, list) and len(elements) > MAX_ELEMENTS:
        raise HTTPException(
            status_code=413,
            detail=f"Designs may contain at most {MAX_ELEMENTS} elements.",
        )

    try:
        source = task["source"]
        target_canvas = task["target_canvas"]
        if not DESIGN_VALIDATOR.is_valid(source) or not CANVAS_VALIDATOR.is_valid(
            target_canvas
        ):
            raise ValueError("Design does not match the CHAMELEON schema")
        source, target_canvas = validate_task(task)
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise HTTPException(
            status_code=422,
            detail="The design or target canvas contains invalid fields.",
        ) from None

    try:
        output = resize(source, target_canvas)
        problems = self_check(source, output)
        expected_canvas = {
            "width": target_canvas["width"],
            "height": target_canvas["height"],
        }
        if (
            output.get("canvas") != expected_canvas
            or problems
            or not DESIGN_VALIDATOR.is_valid(output)
        ):
            logger.error("CHAMELEON API output validation failed")
            raise HTTPException(
                status_code=500,
                detail="The resized design failed validation.",
            )
        json.dumps(output, allow_nan=False)
    except HTTPException:
        raise
    except Exception:
        logger.exception("CHAMELEON API resize failed")
        raise HTTPException(
            status_code=500,
            detail="The design could not be resized.",
        ) from None

    return output
