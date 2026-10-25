"""Hilfsfunktionen für die serverseitig gerenderte Oberfläche (Jinja2 + HTMX)."""

from datetime import date, datetime
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import TZ
from app.security import csrf_token

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
WEEKDAYS_LONG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]
SPORT_LABELS = {"tennis": "Tennis", "padel": "Padel"}


def fmt_day(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]} {d.day:02d}.{d.month:02d}."


def fmt_dt(dt: datetime) -> str:
    local = dt.astimezone(TZ)
    return f"{WEEKDAYS[local.weekday()]} {local:%d.%m.%Y, %H:%M} Uhr"


def fmt_time(dt: datetime) -> str:
    return f"{dt.astimezone(TZ):%H:%M}"


def initials(name: str) -> str:
    parts = name.split()
    if not parts:
        return "?"
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


templates.env.filters["day"] = fmt_day
templates.env.filters["initials"] = initials
templates.env.filters["weekday"] = lambda d: WEEKDAYS[d.weekday()]
templates.env.filters["weekday_long"] = lambda d: WEEKDAYS_LONG[d.weekday()]
templates.env.filters["month"] = lambda d: MONTHS[d.month - 1]
templates.env.filters["local"] = lambda dt: dt.astimezone(TZ)
templates.env.filters["dt"] = fmt_dt
templates.env.filters["time"] = fmt_time
templates.env.globals["sport_label"] = lambda s: SPORT_LABELS.get(str(s), str(s))


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session.setdefault("flash", []).append({"text": message, "kind": kind})


def pop_flashes(request: Request) -> list[dict]:
    return request.session.pop("flash", [])


def render(request: Request, template: str, status_code: int = 200, **context) -> HTMLResponse:
    context.setdefault("user", None)
    context["request"] = request
    context["csrf"] = csrf_token(request)
    context["flashes"] = pop_flashes(request)
    return templates.TemplateResponse(request, template, context, status_code=status_code)


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"
