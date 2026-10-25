from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.config import TZ
from app.db import get_db
from app.models import Club, User
from app.security import get_current_user, verify_csrf
from app.services import booking as svc
from app.web import flash, is_htmx, redirect, render

router = APIRouter()


def _monday(start: str | None) -> date:
    today = svc.now_local().date()
    if start:
        try:
            return svc.week_start_for(date.fromisoformat(start))
        except ValueError:
            pass
    return svc.week_start_for(today)


def _selected_day(monday: date, wanted: date | None, today: date) -> date:
    """Angezeigter Tag der Woche: gewünschter Tag, sonst heute, sonst Montag."""
    sunday = monday + timedelta(days=6)
    for candidate in (wanted, today):
        if candidate and monday <= candidate <= sunday:
            return candidate
    return monday


def _parse_day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _calendar(request: Request, db: Session, user: User, monday: date, partial: bool,
              selected: date | None = None):
    now = svc.now_local()
    courts, days = svc.build_week(db, user, monday, now)
    club = db.get(Club, user.club_id)
    upcoming, _ = svc.my_bookings(db, user, now)
    context = dict(
        user=user, club=club, courts=courts, days=days, monday=monday,
        prev_week=monday - timedelta(days=7), next_week=monday + timedelta(days=7),
        today=now.date(), active_count=len(upcoming),
        next_booking=upcoming[0] if upcoming else None,
        selected=_selected_day(monday, selected, now.date()),
        oob=partial,
    )
    template = "_week.html" if partial else "calendar.html"
    return render(request, template, **context)


@router.get("/")
def home():
    return redirect("/kalender")


@router.get("/kalender")
def calendar(request: Request, start: str | None = None, tag: str | None = None,
             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    wanted = _parse_day(tag) or _parse_day(start)
    return _calendar(request, db, user, _monday(start or tag), partial=False, selected=wanted)


@router.post("/buchungen", dependencies=[Depends(verify_csrf)])
def create_booking(request: Request, court_id: int = Form(...), start: str = Form(...),
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        slot = datetime.fromisoformat(start)
    except ValueError:
        flash(request, "Ungültige Startzeit.", "error")
        return redirect("/kalender")
    if slot.tzinfo is None:
        slot = slot.replace(tzinfo=TZ)
    try:
        booking = svc.book_slot(db, user, court_id, slot)
        when = booking.start_at.astimezone(TZ)
        flash(request, f"Gebucht: {booking.court.name}, {when:%d.%m. %H:%M} Uhr.")
    except svc.BookingError as exc:
        flash(request, str(exc), "error")
    day = slot.astimezone(TZ).date()
    if is_htmx(request):
        return _calendar(request, db, user, svc.week_start_for(day), partial=True, selected=day)
    return redirect(f"/kalender?tag={day.isoformat()}")


@router.post("/buchungen/{booking_id}/storno", dependencies=[Depends(verify_csrf)])
def cancel(request: Request, booking_id: int, back: str = Form("/kalender"),
           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        booking = svc.cancel_booking(db, user, booking_id)
        when = booking.start_at.astimezone(TZ)
        flash(request, f"Storniert: {booking.court.name}, {when:%d.%m. %H:%M} Uhr.")
        day = booking.start_at.astimezone(TZ).date()
    except svc.BookingError as exc:
        flash(request, str(exc), "error")
        day = svc.now_local().date()
    if is_htmx(request) and back.startswith("/kalender"):
        return _calendar(request, db, user, svc.week_start_for(day), partial=True, selected=day)
    target = back if back.startswith("/") and not back.startswith("//") else "/kalender"
    return redirect(target)


@router.get("/meine-buchungen")
def my_bookings(request: Request, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    upcoming, past = svc.my_bookings(db, user)
    return render(request, "my_bookings.html", user=user, upcoming=upcoming, past=past)
