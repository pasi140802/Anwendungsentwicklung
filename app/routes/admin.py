"""Admin-Bereich. Jede Route verlangt die Rolle Admin (NFA-05)."""

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.config import TZ
from app.db import get_db
from app.models import Club, Role, User
from app.security import require_admin, verify_csrf
from app.services import admin as svc
from app.services.booking import BookingError, now_local, week_start_for
from app.web import flash, redirect, render

router = APIRouter(prefix="/admin")
WRITE = [Depends(verify_csrf)]


def _parse_local(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


# --- Mitglieder -------------------------------------------------------------------

@router.get("/mitglieder")
def members(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return render(request, "admin/members.html", user=admin,
                  members=svc.list_members(db, admin.club_id))


@router.post("/mitglieder", dependencies=WRITE)
def create_member(request: Request, name: str = Form(...), email: str = Form(...),
                  role: str = Form("member"), db: Session = Depends(get_db),
                  admin: User = Depends(require_admin)):
    try:
        member, password = svc.create_member(
            db, admin.club_id, name, email, Role.ADMIN if role == "admin" else Role.MEMBER
        )
        flash(request, f"{member.name} angelegt. Startpasswort (nur jetzt sichtbar): {password}")
    except BookingError as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/mitglieder")


@router.post("/mitglieder/{user_id}/sperren", dependencies=WRITE)
def lock_member(request: Request, user_id: int, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    try:
        n = svc.set_member_active(db, admin, user_id, active=False)
        flash(request, f"Mitglied gesperrt, {n} künftige Buchungen storniert.")
    except BookingError as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/mitglieder")


@router.post("/mitglieder/{user_id}/entsperren", dependencies=WRITE)
def unlock_member(request: Request, user_id: int, db: Session = Depends(get_db),
                  admin: User = Depends(require_admin)):
    try:
        svc.set_member_active(db, admin, user_id, active=True)
        flash(request, "Mitglied entsperrt.")
    except BookingError as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/mitglieder")


@router.post("/mitglieder/{user_id}/entfernen", dependencies=WRITE)
def remove_member(request: Request, user_id: int, db: Session = Depends(get_db),
                  admin: User = Depends(require_admin)):
    try:
        n = svc.remove_member(db, admin, user_id)
        flash(request, f"Mitglied entfernt, {n} künftige Buchungen storniert.")
    except BookingError as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/mitglieder")


# --- Plätze -----------------------------------------------------------------------

@router.get("/plaetze")
def courts(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return render(request, "admin/courts.html", user=admin,
                  courts=svc.list_courts(db, admin.club_id))


@router.post("/plaetze", dependencies=WRITE)
def save_court(request: Request, name: str = Form(...), sport: str = Form(...),
               surface: str = Form(""), court_id: int | None = Form(None),
               db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        court = svc.save_court(db, admin.club_id, name, sport, surface, court_id)
        flash(request, f"Platz „{court.name}“ gespeichert.")
    except BookingError as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/plaetze")


@router.post("/plaetze/{court_id}/aktiv", dependencies=WRITE)
def toggle_court(request: Request, court_id: int, active: bool = Form(...),
                 db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        court = svc.set_court_active(db, admin.club_id, court_id, active)
        flash(request, f"Platz „{court.name}“ {'aktiviert' if active else 'deaktiviert'}.")
    except BookingError as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/plaetze")


# --- Sperren ----------------------------------------------------------------------

@router.get("/sperren")
def blocks(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return render(request, "admin/blocks.html", user=admin,
                  courts=svc.list_courts(db, admin.club_id),
                  blocks=svc.list_blocks(db, admin.club_id))


@router.post("/sperren", dependencies=WRITE)
def create_block(request: Request, court_id: int = Form(...), start: str = Form(...),
                 end: str = Form(...), reason: str = Form(...), confirm: bool = Form(False),
                 db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        start_dt, end_dt = _parse_local(start), _parse_local(end)
        block, affected = svc.create_block(db, admin, court_id, start_dt, end_dt, reason, confirm)
    except (BookingError, ValueError) as exc:
        flash(request, str(exc) if isinstance(exc, BookingError) else "Ungültiges Datum.", "error")
        return redirect("/admin/sperren")
    if block is None:
        # Bestätigungsschritt: betroffene Buchungen anzeigen (US-10).
        return render(request, "admin/block_confirm.html", user=admin, affected=affected,
                      form=dict(court_id=court_id, start=start, end=end, reason=reason))
    flash(request, f"Sperre angelegt, {len(affected)} Buchungen storniert.")
    return redirect("/admin/sperren")


@router.post("/sperren/{block_id}/loeschen", dependencies=WRITE)
def delete_block(request: Request, block_id: int, db: Session = Depends(get_db),
                 admin: User = Depends(require_admin)):
    svc.delete_block(db, admin.club_id, block_id)
    flash(request, "Sperre aufgehoben.")
    return redirect("/admin/sperren")


# --- Regeln -----------------------------------------------------------------------

@router.get("/regeln")
def rules(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return render(request, "admin/rules.html", user=admin, club=db.get(Club, admin.club_id))


@router.post("/regeln", dependencies=WRITE)
def save_rules(request: Request, max_active: int = Form(...), max_days: int = Form(...),
               db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        svc.update_rules(db, admin.club_id, max_active, max_days)
        flash(request, "Buchungsregeln gespeichert. Sie gelten für neue Buchungen.")
    except BookingError as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/regeln")


# --- Auslastung -------------------------------------------------------------------

@router.get("/auslastung")
def utilization(request: Request, start: str | None = None, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    from datetime import date, timedelta

    try:
        monday = week_start_for(date.fromisoformat(start)) if start else None
    except ValueError:
        monday = None
    monday = monday or week_start_for(now_local().date())
    return render(request, "admin/utilization.html", user=admin, monday=monday,
                  prev_week=monday - timedelta(days=7), next_week=monday + timedelta(days=7),
                  rows=svc.utilization(db, admin.club_id, monday))
