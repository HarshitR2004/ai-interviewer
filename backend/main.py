from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.errors import install_error_handlers
from backend.api.routes.live_interviews import router as live_router
from backend.api.routes.preparation import router as preparation_router
from backend.bootstrap import Services, build_services
from backend.settings import Settings


def create_app(
    settings: Settings | None = None,
    *,
    service_factory: Callable[[Settings], Services] = build_services,
) -> FastAPI:
    @asynccontextmanager
    # Build the API with injectable services and shared error handling.
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Own provider resources for the lifetime of this application instance.
        services = service_factory(settings or Settings.model_validate({}))
        app.state.services = services
        try:
            yield
        finally:
            await services.aclose()

    app = FastAPI(
        title="AI Interviewer Demo API",
        version="3.0.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    install_error_handlers(app)
    app.include_router(preparation_router)
    app.include_router(live_router)
    return app


app = create_app()
