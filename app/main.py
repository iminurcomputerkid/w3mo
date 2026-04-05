from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import router as api_router
from app.config import Settings
from app.logging_config import configure_logging
from app.services.schedule_service import ScheduleService
from app.services.schedule_store import ScheduleStore
from app.services.wemo_service import WemoService

settings = Settings()
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    service = WemoService(settings)
    schedule_service = ScheduleService(
        ScheduleStore(settings.schedules_file), service
    )
    schedule_service.start()
    app.state.settings = settings
    app.state.wemo_service = service
    app.state.schedule_service = schedule_service
    if settings.startup_discovery:
        service.discover_devices(refresh_after=True)
    yield
    schedule_service.stop()


app = FastAPI(title=settings.app_title, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(api_router, prefix="/api")


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_title": settings.app_title,
            "device_poll_seconds": settings.device_poll_seconds,
        },
    )
