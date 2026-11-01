"""FastAPI route and safe validation responses for offline analysis."""

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from creditpilot.agent.orchestrator import AnalysisOrchestrator
from creditpilot.models.analysis import AnalyzeRequest, AnalyzeResponse
from creditpilot.models.decision import AnalysisStatus

router = APIRouter()
orchestrator = AnalysisOrchestrator.from_default_dataset()


def _http_status(status: AnalysisStatus) -> int:
    if status is AnalysisStatus.NOT_FOUND:
        return 404
    if status is AnalysisStatus.INVALID_INPUT:
        return 422
    if status is AnalysisStatus.FAILED:
        return 503
    return 200


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest) -> JSONResponse:
    result = orchestrator.analyze(payload)
    return JSONResponse(
        status_code=_http_status(result.analysis_status),
        content=result.model_dump(mode="json"),
    )


def analyze_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return stable business statuses without reflecting unsafe input."""

    error_code = "INVALID_INPUT"
    fields = {str(item) for error in exc.errors() for item in error.get("loc", ())}
    if "customer_id" in fields:
        error_code = "INVALID_CUSTOMER_ID"
    elif "question" in fields:
        error_code = "INVALID_QUESTION"
    elif "mode" in fields:
        error_code = "INVALID_MODE"
    content = AnalysisOrchestrator._terminal_response(
        uuid4(),
        None,
        AnalysisStatus.INVALID_INPUT,
        error_code,
        "request does not satisfy the analysis contract",
    )
    return JSONResponse(status_code=422, content=content.model_dump(mode="json"))
