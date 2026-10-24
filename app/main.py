"""Einstiegspunkt der CourtSlot-Webanwendung."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.config import SECRET_KEY, SECURE_COOKIES
from app.db import Base, engine
from app.routes import admin, auth, calendar
from app.security import LoginRequired
from app.services.booking import ForbiddenError, NotFoundError
from app.web import redirect, render


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Prototyp: Tabellen beim Start anlegen. Im Zielbetrieb übernehmen das Migrationen.
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="CourtSlot", lifespan=lifespan, docs_url=None, redoc_url=None)
# Session-Cookie: signiert, HttpOnly, SameSite=Lax; im Zielbetrieb nur über HTTPS (NFA-04).
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="courtslot_session",
    same_site="lax",
    https_only=SECURE_COOKIES,
    max_age=14 * 24 * 3600,
)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(auth.router)
app.include_router(calendar.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.exception_handler(LoginRequired)
async def login_required(request: Request, _: LoginRequired):
    return redirect("/login")


@app.exception_handler(NotFoundError)
async def not_found(request: Request, exc: NotFoundError):
    return render(request, "error.html", status_code=404, title="Nicht gefunden", message=str(exc))


@app.exception_handler(ForbiddenError)
async def forbidden(request: Request, exc: ForbiddenError):
    return render(request, "error.html", status_code=403, title="Nicht erlaubt", message=str(exc))


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    titles = {403: "Nicht erlaubt", 404: "Nicht gefunden"}
    return render(request, "error.html", status_code=exc.status_code,
                  title=titles.get(exc.status_code, "Fehler"), message=str(exc.detail))
