"""Same-origin local demo UI without external assets or services."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

WEB_ROOT = Path(__file__).resolve().parents[3] / "web"

router = APIRouter(include_in_schema=False)


@router.get("/")
def web_index() -> FileResponse:
    """Serve the local-only CreditPilot demonstration page."""

    return FileResponse(
        WEB_ROOT / "index.html",
        headers={
            "Content-Security-Policy": (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self'; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'"
            ),
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )
