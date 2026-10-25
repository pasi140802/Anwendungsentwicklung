"""Kalender, Buchen, Stornieren und Meine Buchungen."""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import mail
from app.config import BASE_URL, TZ
from app.db import get_db
from app.models import Booking, Membership, MembershipStatus, User
from app.security import get_current_member, get_current_user, verify_csrf
from app.services import booking as svc
from app.web import flash, fmt_dt, is_htmx, redirect, render

router = APIRouter()


def _parse_day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _selected_day(monday: date, wanted: date | None, today: date) -> date:
    """Angezeigter Tag der Woche: gewünschter Tag, sonst heute, sonst Montag."""
    sunday = monday + timedelta(days=6)
    for candidate in (wanted, today):
        if candidate and monday <= candidate <= sunday:
            return candidate
    return monday


def _calendar(request: Request, db: Session, member: Membership, monday: date, partial: bool,
              selected: date | None = None):
    now = svc.now_local()
    club, courts, days = svc.build_week(db, member, monday, now)
    upcoming = [b for b in svc.my_bookings(db, member.user, now)[0] if b.club_id == club.id]
    context = dict(
        club=club, courts=courts, days=days, monday=monday,
        prev_week=monday - timedelta(days=7), next_week=monday + timedelta(days=7),
        today=now.date(), active_count=len(upcoming),
        next_booking=upcoming[0] if upcoming else None,
        selected=_selected_day(monday, selected, now.date()), oob=partial,
    )
    return render(request, "_week.html" if partial else "calendar.html", **context)


@router.get("/")
def home():
    return redirect("/kalender")


@router.get("/kalender")
def calendar(request: Request, start: str | None = None, tag: str | None = None,
             db: Session = Depends(get_db), member: Membership = Depends(get_current_member)):
    wanted = _parse_day(tag) or _parse_day(start)
    monday = svc.week_start_for(wanted or svc.now_local().date())
    return _calendar(request, db, member, monday, partial=False, selected=wanted)


@router.post("/buchungen", dependencies=[Depends(verify_csrf)])
def create_booking(request: Request, background: BackgroundTasks, court_id: int = Form(...),
                   start: str = Form(...), db: Session = Depends(get_db),
                   member: Membership = Depends(get_current_member)):
    try:
        slot = datetime.fromisoformat(start)
    except ValueError:
        flash(request, "Ungültige Startzeit.", "error")
        return redirect("/kalender")
    if slot.tzinfo is None:
        slot = slot.replace(tzinfo=TZ)
    try:
        booking = svc.book_slot(db, member, court_id, slot)
        when = booking.start_at.astimezone(TZ)
        flash(request, f"Gebucht: {booking.court.name}, {when:%d.%m. %H:%M} Uhr.")
        mail.send(background, member.user.email,
                  f"Gebucht: {booking.court.name}, {when:%d.%m. %H:%M} Uhr", "booking_confirmed",
                  name=member.user.name, club=member.club.name, court=booking.court.name,
                  when=fmt_dt(booking.start_at), until=f"{booking.end_at.astimezone(TZ):%H:%M}",
                  price=booking.price_cents, link=f"{BASE_URL}/meine-buchungen")
    except svc.BookingError as exc:
        flash(request, str(exc), "error")
    day = slot.astimezone(TZ).date()
    if is_htmx(request):
        return _calendar(request, db, member, svc.week_start_for(day), partial=True, selected=day)
    return redirect(f"/kalender?tag={day.isoformat()}")


@router.post("/buchungen/{booking_id}/storno", dependencies=[Depends(verify_csrf)])
def cancel(request: Request, background: BackgroundTasks, booking_id: int,
           back: str = Form("/kalender"), db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    booking = db.get(Booking, booking_id)
    member = None
    if booking is not None:
        member = db.scalars(select(Membership).where(
            Membership.user_id == user.id, Membership.club_id == booking.club_id,
            Membership.status == MembershipStatus.ACTIVE)).first()
    if member is None:
        raise svc.NotFoundError("Buchung nicht gefunden")
    request.state.member = member
    day = svc.now_local().date()
    try:
        svc.cancel_booking(db, member, booking_id)
        when = booking.start_at.astimezone(TZ)
        flash(request, f"Storniert: {booking.court.name}, {when:%d.%m. %H:%M} Uhr.")
        day = when.date()
        if booking.user_id != user.id:  # Verwaltung storniert: Mitglied informieren
            mail.send(background, booking.user.email, "Deine Buchung wurde storniert",
                      "booking_cancelled_by_club", name=booking.user.name,
                      club=member.club.name, court=booking.court.name,
                      when=fmt_dt(booking.start_at), reason="")
    except svc.BookingError as exc:
        flash(request, str(exc), "error")
    if is_htmx(request) and back.startswith("/kalender"):
        request.session["club_id"] = member.club_id
        return _calendar(request, db, member, svc.week_start_for(day), partial=True, selected=day)
    target = back if back.startswith("/") and not back.startswith("//") else "/kalender"
    return redirect(target)


@router.get("/meine-buchungen")
def my_bookings(request: Request, db: Session = Depends(get_db),
                member: Membership = Depends(get_current_member)):
    now = svc.now_local()
    upcoming, past = svc.my_bookings(db, member.user, now)
    clubs = {m.club_id: m.club for m in request.state.memberships}
    deadlines = {}  # Buchung -> Stornofrist, falls der Verein eine hat
    for b in upcoming:
        club = clubs.get(b.club_id)
        if club is not None and club.cancel_hours:
            deadlines[b.id] = svc.cancel_deadline(club, b)
    return render(request, "my_bookings.html", upcoming=upcoming, past=past, clubs=clubs,
                  multi_club=len(clubs) > 1, deadlines=deadlines, now=now)
