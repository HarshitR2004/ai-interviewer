from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.errors import install_error_handlers
from backend.api.routes.live_interviews import router as live_router
from backend.api.routes.preparation import router as preparation_router
from backend.bootstrap import Services, build_services
from backend.settings import Settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Create demo services once at startup and close provider clients on shutdown.
    services = app.state.services
    if services is None:
        services = build_services(Settings.model_validate({}))
    app.state.services = services
    try:
        yield
    finally:
        await services.aclose()


def create_app(services: Services | None = None) -> FastAPI:
    # Tests can supply ready-made services without changing the startup procedure.
    app = FastAPI(
        title="AI Interviewer Demo API",
        version="3.0.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.services = services
    install_error_handlers(app)
    app.include_router(preparation_router)
    app.include_router(live_router)
    return app


app = create_app()
