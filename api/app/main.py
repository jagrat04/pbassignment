import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import SessionLocal
from app.reference import get_reference
from app.routers import admin_artwork, admin_publish, admin_shows, catalog, misc
from app.services.publish import reap_interrupted_runs

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s %(message)s"
)
log = logging.getLogger("peblo")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail loudly at boot rather than on the first upload if the rulebook is
    # missing or malformed.
    ref = get_reference()
    log.info(
        "reference loaded: %d sections, %d categories, %d languages",
        len(ref.sections),
        len(ref.categories),
        len(ref.languages),
    )
    with SessionLocal() as db:
        try:
            reap_interrupted_runs(db)
        except Exception:  # noqa: BLE001 - never block startup on housekeeping
            log.exception("could not reap interrupted publish runs")
    yield


app = FastAPI(
    title="Peblo TV Mini",
    version="1.0.0",
    summary="CMS + publish pipeline + viewer catalogue",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Never leak a stack trace to a content editor."""
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "problem": "Something went wrong on our side.",
            "fix": "Try again. If it keeps happening, send this to engineering: "
            f"{request.method} {request.url.path}",
        },
    )


app.include_router(misc.router)
app.include_router(catalog.router)
app.include_router(admin_shows.router)
app.include_router(admin_artwork.router)
app.include_router(admin_publish.router)

if settings.storage_backend == "local":
    # Local dev only. In production the bucket is served by R2 / a CDN and the
    # API never sits in the path of an image request.
    settings.storage_local_root.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/media",
        StaticFiles(directory=settings.storage_local_root),
        name="media",
    )
