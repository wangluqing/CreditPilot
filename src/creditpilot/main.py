"""FastAPI application entry point for CreditPilot."""

from fastapi import FastAPI

from creditpilot import __version__

app = FastAPI(
    title="CreditPilot",
    version=__version__,
    description="AI credit risk explanation and decision-support demo.",
)


@app.get("/health")
def health() -> dict[str, str]:
    """Return basic application health information."""
    return {
        "status": "ok",
        "app": "CreditPilot",
        "version": __version__,
        "mode": "demo",
    }
