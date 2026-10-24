import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.features.interviews.service import InterviewService
from backend.features.live_interviews.models import EngineError
from backend.features.live_interviews.reasoning import ModelReasoner
from backend.features.live_interviews.service import LiveInterviewService
from backend.features.live_interviews.source import LocalPlanSource
from backend.features.live_interviews.speech import SpeechClient
from backend.features.live_interviews.storage import SQLiteRepository
from backend.features.preparation.service import PreparationService
from backend.features.preparation.storage import LocalStore
from backend.features.profiles.service import ProfileService
from backend.shared.config import Settings
from backend.shared.llm import ChatCompletionsClient
from backend.web.live_routes import router as live_router
from backend.web.routes import router
from backend.web.upload_limits import ResumeUploadLimits


def create_app(
    settings: Settings | None = None,
    service: PreparationService | None = None,
    live_service: LiveInterviewService | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        config = settings or Settings()
        store = service.store if service else LocalStore(config.data_dir)
        store.recover()
        model = ChatCompletionsClient(config.llm_base_url, config.llm_model, config.llm_api_key)
        app.state.service = service or PreparationService(
            store,
            ProfileService(model),
            InterviewService(model),
        )
        app.state.tasks = set()
        app.state.speech_client = (
            SpeechClient(
                config.stt_base_url,
                config.tts_base_url,
                stt_api_key=config.stt_api_key,
                tts_api_key=config.tts_api_key,
                timeout=config.speech_timeout_sec,
            )
            if config.speech_enabled
            else None
        )
        app.state.live_service = live_service or LiveInterviewService(
            SQLiteRepository(config.data_dir / "live_interviews.sqlite3"),
            LocalPlanSource(store.root, app.state.service.active),
            ModelReasoner(
                model,
                timeout=config.live_reasoning_timeout_sec,
            )
            if config.live_reasoning_enabled
            else None,
            timeout=config.live_reasoning_timeout_sec,
        )
        await app.state.live_service.initialize()

        async def watch_deadlines():
            while True:
                await asyncio.sleep(1)
                try:
                    await app.state.live_service.expire()
                except EngineError:
                    # A busy store must not permanently stop deadline enforcement.
                    continue

        watcher = asyncio.create_task(watch_deadlines())
        app.state.tasks.add(watcher)
        try:
            yield
        finally:
            tasks = list(app.state.tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(
        title="Interview preparation",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        message = (
            "Check the session ID, event ID, prompt ID, and answer fields."
            if request.url.path.startswith("/api/live-sessions")
            else "Check the required fields, job description, and interview settings."
        )
        return JSONResponse(
            status_code=422,
            content={"detail": message},
        )

    app.add_middleware(ResumeUploadLimits)
    app.include_router(router)
    app.include_router(live_router)

    @app.exception_handler(EngineError)
    async def engine_error(request, exc):
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "web/static"),
        name="static",
    )
    return app


app = create_app()
