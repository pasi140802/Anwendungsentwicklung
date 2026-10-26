"""Verwaltung eines Vereins. Jede Route verlangt die Rolle Admin (NFA-05)."""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from sqlalchemy.orm import Session

from app import mail
from app.config import BASE_URL, TZ
from app.db import get_db
from app.models import Club, Membership, MembershipStatus, Role
from app.security import require_admin, verify_csrf
from app.services import accounts
from app.services import admin as svc
from app.services.booking import BookingError, now_local, week_start_for
from app.web import flash, fmt_dt, redirect, render

router = APIRouter(prefix="/admin")
WRITE = [Depends(verify_csrf)]


def _parse_local(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


# --- Mitglieder, Anfragen, Einladungen ------------------------------------------------

@router.get("/mitglieder")
def members(request: Request, db: Session = Depends(get_db),
            admin: Membership = Depends(require_admin)):
    return render(request, "admin/members.html", club=db.get(Club, admin.club_id),
                  members=svc.list_members(db, admin.club_id),
                  pending=svc.list_members(db, admin.club_id, MembershipStatus.PENDING),
                  invitations=svc.open_invitations(db, admin.club_id))


@router.post("/einladungen", dependencies=WRITE)
def create_invitation(request: Request, background: BackgroundTasks, email: str = Form(""),
                      role: str = Form("member"), db: Session = Depends(get_db),
                      admin: Membership = Depends(require_admin)):
    try:
        inv = svc.invite(db, admin, email, Role.ADMIN if role == "admin" else Role.MEMBER)
    except BookingError as exc:
        flash(request, str(exc), "error")
        return redirect("/admin/mitglieder")
    link = f"{BASE_URL}/einladung/{accounts.invitation_token(inv)}"
    mail.send(background, inv.email, f"Einladung zu {admin.club.name}", "invite",
              club=admin.club.name, inviter=admin.user.name, link=link)
    flash(request, f"Einladung an {inv.email} verschickt.")
    return redirect("/admin/mitglieder")


@router.post("/einladungen/{invitation_id}/zurueckziehen", dependencies=WRITE)
def revoke_invitation(request: Request, invitation_id: int, db: Session = Depends(get_db),
                      admin: Membership = Depends(require_admin)):
    svc.revoke_invitation(db, admin.club_id, invitation_id)
    flash(request, "Einladung zurückgezogen.")
    return redirect("/admin/mitglieder")


@router.post("/beitrittscode", dependencies=WRITE)
def new_join_code(request: Request, db: Session = Depends(get_db),
                  admin: Membership = Depends(require_admin)):
    code = svc.regenerate_join_code(db, admin.club_id)
    flash(request, f"Neuer Beitrittscode: {code}. Der alte Code gilt nicht mehr.")
    return redirect("/admin/mitglieder")


@router.post("/mitglieder/{membership_id}/anfrage", dependencies=WRITE)
def decide(request: Request, background: BackgroundTasks, membership_id: int,
           accept: str = Form("true"), db: Session = Depends(get_db),
           admin: Membership = Depends(require_admin)):
    try:
        m = svc.get_membership(db, admin.club_id, membership_id)
        user = m.user
        svc.decide_request(db, admin, membership_id, accept == "true")
    except BookingError as exc:
        flash(request, str(exc), "error")
        return redirect("/admin/mitglieder")
    if accept == "true":
        mail.send(background, user.email, f"Willkommen bei {admin.club.name}", "request_accepted",
                  name=user.name, club=admin.club.name, link=f"{BASE_URL}/kalender")
        flash(request, f"{user.name} ist jetzt Mitglied.")
    else:
        flash(request, f"Anfrage von {user.name} abgelehnt.")
    return redirect("/admin/mitglieder")


@router.post("/mitglieder/{membership_id}/sperren", dependencies=WRITE)
def lock_member(request: Request, membership_id: int, db: Session = Depends(get_db),
                admin: Membership = Depends(require_admin)):
    try:
        n = svc.set_member_locked(db, admin, membership_id, locked=True)
        flash(request, f"Mitglied gesperrt, {n} kommende Buchungen storniert.")
    except BookingError as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/mitglieder")


@router.post("/mitglieder/{membership_id}/entsperren", dependencies=WRITE)
def unlock_member(request: Request, membership_id: int, db: Session = Depends(get_db),
                  admin: Membership = Depends(require_admin)):
    try:
        svc.set_member_locked(db, admin, membership_id, locked=False)
        flash(request, "Mitglied entsperrt.")
    except BookingError as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/mitglieder")


@router.post("/mitglieder/{membership_id}/rolle", dependencies=WRITE)
def change_role(request: Request, membership_id: int, role: str = Form("member"),
                db: Session = Depends(get_db), admin: Membership = Depends(require_admin)):
    try:
        m = svc.set_role(db, admin, membership_id, Role.ADMIN if role == "admin" else Role.MEMBER)
        role = "in der Verwaltung" if m.is_admin else "Mitglied"
        flash(request, f"{m.user.name} ist jetzt {role}.")
    except BookingError as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/mitglieder")


@router.post("/mitglieder/{membership_id}/entfernen", dependencies=WRITE)
def remove_member(request: Request, membership_id: int, db: Session = Depends(get_db),
                  admin: Membership = Depends(require_admin)):
    try:
        n = svc.remove_member(db, admin, membership_id)
        flash(request, f"Mitglied entfernt, {n} kommende Buchungen storniert.")
    except BookingError as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/mitglieder")


# --- Plätze -----------------------------------------------------------------------

@router.get("/plaetze")
def courts(request: Request, db: Session = Depends(get_db),
           admin: Membership = Depends(require_admin)):
    return render(request, "admin/courts.html", club=db.get(Club, admin.club_id),
                  courts=svc.list_courts(db, admin.club_id),
                  items=svc.list_rental_items(db, admin.club_id))


@router.post("/plaetze", dependencies=WRITE)
async def save_court(request: Request, db: Session = Depends(get_db),
                     admin: Membership = Depends(require_admin)):
    raw = await request.form()
    form = dict(raw)
    form["durations"] = raw.getlist("durations")
    court_id = int(form["court_id"]) if form.get("court_id") else None
    try:
        court = svc.save_court(db, admin.club_id, form, court_id)
        flash(request, f"Platz „{court.name}“ gespeichert.")
    except BookingError as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/plaetze")


@router.post("/plaetze/{court_id}/aktiv", dependencies=WRITE)
def toggle_court(request: Request, court_id: int, active: bool = Form(...),
                 db: Session = Depends(get_db), admin: Membership = Depends(require_admin)):
    try:
        court = svc.set_court_active(db, admin.club_id, court_id, active)
        flash(request, f"Platz „{court.name}“ {'aktiviert' if active else 'deaktiviert'}.")
    except BookingError as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/plaetze")


@router.post("/leihartikel", dependencies=WRITE)
async def save_rental_item(request: Request, db: Session = Depends(get_db),
                           admin: Membership = Depends(require_admin)):
    form = dict(await request.form())
    item_id = int(form["item_id"]) if form.get("item_id") else None
    try:
        item = svc.save_rental_item(db, admin.club_id, form, item_id)
        flash(request, f"Leihartikel „{item.name}“ gespeichert.")
    except BookingError as exc:
        flash(request, str(exc), "error")
    return redirect("/admin/plaetze#leihartikel")


@router.post("/leihartikel/{item_id}/aktiv", dependencies=WRITE)
def toggle_rental_item(request: Request, item_id: int, active: bool = Form(...),
                       db: Session = Depends(get_db),
                       admin: Membership = Depends(require_admin)):
    item = svc.set_rental_item_active(db, admin.club_id, item_id, active)
    flash(request, f"„{item.name}“ {'wird wieder angeboten' if active else 'ausgeblendet'}.")
    return redirect("/admin/plaetze#leihartikel")


# --- Sperren ----------------------------------------------------------------------

@router.get("/sperren")
def blocks(request: Request, db: Session = Depends(get_db),
           admin: Membership = Depends(require_admin)):
    return render(request, "admin/blocks.html", courts=svc.list_courts(db, admin.club_id),
                  blocks=svc.list_blocks(db, admin.club_id))


@router.post("/sperren", dependencies=WRITE)
def create_block(request: Request, background: BackgroundTasks, court_id: int = Form(...),
                 start: str = Form(...), end: str = Form(...), reason: str = Form(...),
                 confirm: bool = Form(False), db: Session = Depends(get_db),
                 admin: Membership = Depends(require_admin)):
    try:
        start_dt, end_dt = _parse_local(start), _parse_local(end)
        block, affected = svc.create_block(db, admin, court_id, start_dt, end_dt, reason, confirm)
    except (BookingError, ValueError) as exc:
        flash(request, str(exc) if isinstance(exc, BookingError) else "Ungültiges Datum.", "error")
        return redirect("/admin/sperren")
    if block is None:
        # Bestätigungsschritt: betroffene Buchungen anzeigen (US-10).
        return render(request, "admin/block_confirm.html", affected=affected,
                      form=dict(court_id=court_id, start=start, end=end, reason=reason))
    for b in affected:
        mail.send(background, b.user.email, "Deine Buchung wurde storniert",
                  "booking_cancelled_by_club", name=b.user.name, club=admin.club.name,
                  court=b.court.name, when=fmt_dt(b.start_at), reason=block.reason)
    n = len(affected)
    flash(request, f"Sperre angelegt, {n} {'Buchung' if n == 1 else 'Buchungen'} storniert.")
    return redirect("/admin/sperren")


@router.post("/sperren/{block_id}/loeschen", dependencies=WRITE)
def delete_block(request: Request, block_id: int, db: Session = Depends(get_db),
                 admin: Membership = Depends(require_admin)):
    svc.delete_block(db, admin.club_id, block_id)
    flash(request, "Sperre aufgehoben.")
    return redirect("/admin/sperren")


# --- Vereinseinstellungen (Stammdaten, Öffnungszeiten, Saison, Regeln) ---------------

@router.get("/verein")
def club_settings(request: Request, db: Session = Depends(get_db),
                  admin: Membership = Depends(require_admin)):
    return render(request, "admin/club.html", club=db.get(Club, admin.club_id), form=None)


@router.post("/verein", dependencies=WRITE)
async def save_club(request: Request, db: Session = Depends(get_db),
                    admin: Membership = Depends(require_admin)):
    form = dict(await request.form())
    try:
        svc.update_club(db, admin.club_id, form)
        flash(request, "Einstellungen gespeichert. Sie gelten für neue Buchungen.")
    except BookingError as exc:
        db.rollback()
        flash(request, str(exc), "error")
    return redirect("/admin/verein")


@router.get("/regeln")
def rules_redirect():
    return redirect("/admin/verein")


# --- Auslastung -------------------------------------------------------------------

@router.get("/auslastung")
def utilization(request: Request, start: str | None = None, db: Session = Depends(get_db),
                admin: Membership = Depends(require_admin)):
    try:
        monday = week_start_for(date.fromisoformat(start)) if start else None
    except ValueError:
        monday = None
    monday = monday or week_start_for(now_local().date())
    return render(request, "admin/utilization.html", monday=monday,
                  prev_week=monday - timedelta(days=7), next_week=monday + timedelta(days=7),
                  rows=svc.utilization(db, admin.club_id, monday))
