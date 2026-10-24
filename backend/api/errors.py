from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from backend.common.errors import ApplicationError, Conflict, InvalidInput, NotFound, Unavailable


class ErrorResponse(BaseModel):
    detail: str


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def application_error(request: Request, exc: ApplicationError) -> JSONResponse:
        status = (
            422
            if isinstance(exc, InvalidInput)
            else 404
            if isinstance(exc, NotFound)
            else 409
            if isinstance(exc, Conflict)
            else 503
            if isinstance(exc, Unavailable)
            else 500
        )
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def invalid_request(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=422, content={"detail": "Check the required fields and supplied settings."}
        )
