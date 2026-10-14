"""Exception handlers: every error is returned as an ``ErrorResponse``."""

from __future__ import annotations

import logging

from cineforge.configuration import ThemeNotFoundError
from cineforge.contracts.agents import AgentSchemaError
from cineforge.contracts.api import ErrorResponse
from cineforge.contracts.cost import BudgetExceededError, UnknownPriceError
from cineforge.contracts.repositories import NotFoundError, ThemeVersionConflictError
from cineforge.contracts.workflow import InvalidStateTransitionError
from cineforge.orchestration import external
from cineforge.orchestration.workflow import ApprovalBlockedError, InvalidClaimReviewError
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

_HTTP_ERROR_NAMES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
}


def error_response(status_code: int, error: str, detail: object = None) -> JSONResponse:
    body = ErrorResponse(error=error, detail=jsonable_encoder(detail))
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return error_response(status.HTTP_404_NOT_FOUND, "not_found", str(exc))

    @app.exception_handler(ThemeNotFoundError)
    async def _theme_not_found(_: Request, exc: ThemeNotFoundError) -> JSONResponse:
        return error_response(status.HTTP_404_NOT_FOUND, "not_found", str(exc))

    @app.exception_handler(InvalidStateTransitionError)
    async def _conflict(_: Request, exc: InvalidStateTransitionError) -> JSONResponse:
        return error_response(
            status.HTTP_409_CONFLICT,
            "invalid_state_transition",
            {
                "message": str(exc),
                "from_state": exc.from_state.value,
                "to_state": exc.to_state.value,
            },
        )

    @app.exception_handler(ApprovalBlockedError)
    async def _approval_blocked(_: Request, exc: ApprovalBlockedError) -> JSONResponse:
        return error_response(status.HTTP_409_CONFLICT, "approval_blocked", str(exc))

    @app.exception_handler(ThemeVersionConflictError)
    async def _theme_conflict(_: Request, exc: ThemeVersionConflictError) -> JSONResponse:
        return error_response(status.HTTP_409_CONFLICT, "theme_version_conflict", str(exc))

    @app.exception_handler(InvalidClaimReviewError)
    async def _bad_claims(_: Request, exc: InvalidClaimReviewError) -> JSONResponse:
        return error_response(status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", str(exc))

    @app.exception_handler(external.PaidProvidersDisabledError)
    async def _paid_disabled(_: Request, exc: external.PaidProvidersDisabledError) -> JSONResponse:
        return error_response(status.HTTP_403_FORBIDDEN, "paid_providers_disabled", str(exc))

    @app.exception_handler(UnknownPriceError)
    async def _unknown_price(_: Request, exc: UnknownPriceError) -> JSONResponse:
        return error_response(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_price", str(exc))

    @app.exception_handler(BudgetExceededError)
    async def _budget(_: Request, exc: BudgetExceededError) -> JSONResponse:
        return error_response(
            status.HTTP_409_CONFLICT,
            "budget_exceeded",
            {
                "message": str(exc),
                "requested": str(exc.requested),
                "available": str(exc.available),
            },
        )

    @app.exception_handler(external.CreditCapExceededError)
    async def _credit_cap(_: Request, exc: external.CreditCapExceededError) -> JSONResponse:
        return error_response(
            status.HTTP_409_CONFLICT,
            "budget_exceeded",
            {
                "message": str(exc),
                "used": str(exc.used),
                "quoted": str(exc.quoted),
                "cap": str(exc.cap),
            },
        )

    @app.exception_handler(external.ExternalStateError)
    async def _external_state(_: Request, exc: external.ExternalStateError) -> JSONResponse:
        return error_response(status.HTTP_409_CONFLICT, "invalid_state", str(exc))

    @app.exception_handler(external.SourceRightsError)
    async def _source_rights(_: Request, exc: external.SourceRightsError) -> JSONResponse:
        return error_response(status.HTTP_409_CONFLICT, "rights_blocked", str(exc))

    @app.exception_handler(external.ExternalGenerationError)
    async def _external_bad(_: Request, exc: external.ExternalGenerationError) -> JSONResponse:
        return error_response(status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", str(exc))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", exc.errors()
        )

    @app.exception_handler(AgentSchemaError)
    async def _agent_schema(_: Request, exc: AgentSchemaError) -> JSONResponse:
        return error_response(status.HTTP_422_UNPROCESSABLE_CONTENT, "agent_schema_error", str(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        name = _HTTP_ERROR_NAMES.get(exc.status_code, "error")
        return error_response(exc.status_code, name, exc.detail)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", type(exc).__name__
        )
