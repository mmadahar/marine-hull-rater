"""HTTP API over the rating engine. Valid inputs come from the rates file."""

import json
import os
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BeforeValidator, ConfigDict, Field, create_model
from pydantic_core import PydanticCustomError

from app.rate_limit import RateLimiter, client_ip
from rater import QuoteResult, load_rates, quote

STATIC_DIR = Path(__file__).parent / "static"


def _json_number(value):
    """Refuse numbers sent as text or true/false, which Decimal would otherwise accept."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PydanticCustomError("number", "Input should be a number")
    return value


def _field_type(definition: dict):
    if definition["type"] == "choice":
        return Literal[*definition["options"]]
    limits = Field(ge=definition["min"], le=definition["max"])
    if definition["type"] == "integer":
        return Annotated[int, Field(strict=True), limits]
    return Annotated[
        Decimal, BeforeValidator(_json_number), Field(allow_inf_nan=False), limits
    ]


def _request_model(rates: dict):
    fields = {
        name: (_field_type(definition), ...)
        for name, definition in rates["inputs"].items()
    }
    return create_model("QuoteRequest", __config__=ConfigDict(extra="forbid"), **fields)


def _invalid(errors: list[dict]) -> JSONResponse:
    return JSONResponse({"errors": errors}, status_code=422)


def _outputs(result: QuoteResult) -> dict:
    """The quote's figures. Decimals become strings so they keep their exact value."""
    return {
        "currency": result.currency,
        "base_premium": str(result.base_premium),
        "factors": [
            {
                "input": factor.input,
                "label": factor.label,
                "value": factor.value,
                "factor": str(factor.factor),
                "effect": str(factor.effect),
                "premium_after": str(factor.premium_after),
            }
            for factor in result.factors
        ],
        "technical_premium": str(result.technical_premium),
        "exposure_unit": result.exposure_unit,
        "rate_per_gross_tonne": str(result.rate_per_exposure_unit),
        "rate_on_hull_value_pct": str(result.rate_on_value_pct),
    }


def create_app(static_dir: Path = STATIC_DIR) -> FastAPI:
    rates = load_rates()
    QuoteRequest = _request_model(rates)
    limiter = RateLimiter()
    git_commit = os.environ.get("GIT_COMMIT") or "local"
    app = FastAPI(title=rates["model"]["name"])

    # Middleware rather than a dependency, so that bad requests count too.
    @app.middleware("http")
    async def limit_quotes(request: Request, call_next):
        is_quote = request.method == "POST" and request.url.path == "/quote"
        if is_quote and not limiter.allow(client_ip(request)):
            return JSONResponse(
                {"errors": [{"field": "request", "message": "Too many quotes, try again in a minute"}]},
                status_code=429,
                headers={"Retry-After": str(limiter.window_seconds)},
            )
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def per_field_errors(request: Request, error: RequestValidationError):
        # Only the name and message go back: the bad value could be NaN, which JSON can't carry.
        return _invalid(
            [
                {
                    "field": next(
                        (part for part in item["loc"] if isinstance(part, str) and part != "body"),
                        "body",
                    ),
                    "message": item["msg"],
                }
                for item in error.errors()
            ]
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/options")
    def options():
        return {
            "model_version": rates["model"]["version"],
            "currency": rates["model"]["currency"],
            "inputs": rates["inputs"],
        }

    @app.post("/quote")
    def post_quote(body: QuoteRequest):
        # A deductible this large means a claim could never pay out.
        if body.deductible >= body.agreed_hull_value:
            return _invalid(
                [{"field": "deductible", "message": "Input should be less than agreed_hull_value"}]
            )

        result = quote(body.model_dump(), rates)
        identity = {
            "quote_id": str(uuid.uuid4()),
            "model_version": result.model_version,
            "git_commit": git_commit,
        }
        outputs = _outputs(result)
        # The audit trail: one JSON line on stdout per successful quote.
        print(
            json.dumps({**identity, "inputs": body.model_dump(mode="json"), "outputs": outputs}),
            flush=True,
        )
        return {**identity, **outputs}

    # Last, so that the routes above win over the catch-all at "/".
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app


app = create_app()
