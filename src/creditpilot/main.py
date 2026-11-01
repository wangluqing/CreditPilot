"""FastAPI application entry point for CreditPilot."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from creditpilot import __version__
from creditpilot.api import analyze_validation_error, router

app = FastAPI(
    title="CreditPilot",
    version=__version__,
    description="AI credit risk explanation and decision-support demo.",
)
app.include_router(router)


@app.exception_handler(RequestValidationError)
def request_validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    if request.url.path == "/analyze":
        return analyze_validation_error(request, exc)
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.get("/health")
def health() -> dict[str, str]:
    """Return basic application health information."""
    return {
        "status": "ok",
        "app": "CreditPilot",
        "version": __version__,
        "mode": "demo",
    }
