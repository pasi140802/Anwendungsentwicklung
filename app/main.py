"""Einstiegspunkt der CourtSlot-Webanwendung."""

from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.config import SECRET_KEY, SECURE_COOKIES
from app.db import engine
from app.routes import account, admin, auth, calendar, legal
from app.security import ClubRequired, LoginRequired
from app.services.booking import ForbiddenError, NotFoundError
from app.web import redirect, render

# Das Datenbankschema verwalten Migrationen (alembic upgrade head), nicht die App.
app = FastAPI(title="CourtSlot", docs_url=None, redoc_url=None, openapi_url=None)

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if SECURE_COOKIES:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


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
for module in (auth, account, calendar, admin, legal):
    app.include_router(module.router)


@app.get("/health")
def health():
    """Bereitschaftsprüfung für Reverse Proxy und Monitoring: App und Datenbank."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 – jeder Datenbankfehler bedeutet „nicht bereit“
        return JSONResponse({"status": "error", "database": "nicht erreichbar"}, status_code=503)
    return {"status": "ok"}


@app.exception_handler(LoginRequired)
async def login_required(request: Request, _: LoginRequired):
    target = request.url.path
    if request.method == "GET" and target not in ("/", "/kalender"):
        return redirect(f"/login?next={quote(target)}")
    return redirect("/login")


@app.exception_handler(ClubRequired)
async def club_required(request: Request, _: ClubRequired):
    return redirect("/start")


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
