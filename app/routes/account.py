"""Konto, Einstieg ohne Verein, Verein registrieren, beitreten, wechseln, Einladungen."""

import json

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import mail
from app.config import BASE_URL
from app.db import get_db
from app.models import Club, MembershipStatus, User
from app.security import active_memberships, get_current_user, verify_csrf
from app.services import accounts
from app.services.accounts import AccountError
from app.web import flash, redirect, render

router = APIRouter()
WRITE = [Depends(verify_csrf)]


def _context(request: Request, db: Session, user: User) -> dict:
    memberships = active_memberships(db, user)
    request.state.memberships = memberships
    if memberships:  # Navigation wie auf den Vereinsseiten anzeigen
        wanted = request.session.get("club_id")
        request.state.member = next((m for m in memberships if m.club_id == wanted),
                                    memberships[0])
    all_m = accounts.all_memberships(db, user)
    return {"all_memberships": all_m,
            "pending": [m for m in all_m if m.status == MembershipStatus.PENDING]}


# --- Einstieg ohne aktive Mitgliedschaft -----------------------------------------------

@router.get("/start")
def start(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return render(request, "start.html", **_context(request, db, user))


@router.post("/beitreten", dependencies=WRITE)
def join(request: Request, code: str = Form(""), db: Session = Depends(get_db),
         user: User = Depends(get_current_user)):
    try:
        m = accounts.join_with_code(db, user, code)
    except AccountError as exc:
        return render(request, "start.html", status_code=400, join_error=str(exc), code=code,
                      **_context(request, db, user))
    club = db.get(Club, m.club_id)
    if m.status == MembershipStatus.ACTIVE:
        request.session["club_id"] = club.id
        flash(request, f"Du bist bereits Mitglied bei {club.name}.")
        return redirect("/kalender")
    flash(request, f"Anfrage an {club.name} gesendet. Die Vereinsverwaltung schaltet dich frei.")
    return redirect("/start")


@router.get("/verein/neu")
def club_new_form(request: Request, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    return render(request, "club_new.html", form={}, **_context(request, db, user))


@router.post("/verein/neu", dependencies=WRITE)
async def club_new(request: Request, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    form = dict(await request.form())
    try:
        club = accounts.create_club(db, user, form)
    except AccountError as exc:
        return render(request, "club_new.html", status_code=400, error=str(exc), form=form,
                      **_context(request, db, user))
    request.session["club_id"] = club.id
    flash(request, f"{club.name} ist angelegt. Lege jetzt deine Plätze an.")
    return redirect("/admin/plaetze")


@router.post("/verein/wechseln", dependencies=WRITE)
def switch_club(request: Request, club_id: int = Form(...), db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    if any(m.club_id == club_id for m in active_memberships(db, user)):
        request.session["club_id"] = club_id
    return redirect("/kalender")


# --- Einladungen ------------------------------------------------------------------

@router.get("/einladung/{token}")
def invitation(request: Request, token: str, db: Session = Depends(get_db)):
    try:
        inv = accounts.invitation_from_token(db, token)
    except AccountError as exc:
        return render(request, "message.html", status_code=400, title="Einladung nicht gültig",
                      message=str(exc), action=("/login", "Zur Anmeldung"))
    user = None
    if request.session.get("user_id"):
        try:
            user = get_current_user(request, db)
        except Exception:  # abgelaufene Sitzung: wie nicht angemeldet behandeln
            user = None
    return render(request, "invitation.html", inv=inv, token=token, user=user)


@router.post("/einladung/{token}", dependencies=WRITE)
def accept(request: Request, token: str, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    try:
        inv = accounts.invitation_from_token(db, token)
        m = accounts.accept_invitation(db, user, inv)
    except AccountError as exc:
        return render(request, "message.html", status_code=400, title="Einladung nicht möglich",
                      message=str(exc), action=("/start", "Weiter"))
    request.session["club_id"] = m.club_id
    flash(request, f"Willkommen bei {inv.club.name}!")
    return redirect("/kalender")


# --- Konto ------------------------------------------------------------------------

@router.get("/konto")
def account(request: Request, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    return render(request, "account.html", **_context(request, db, user))


@router.post("/konto/name", dependencies=WRITE)
def account_name(request: Request, name: str = Form(""), db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    try:
        accounts.rename(db, user, name)
        flash(request, "Name gespeichert.")
    except AccountError as exc:
        flash(request, str(exc), "error")
    return redirect("/konto")


@router.post("/konto/passwort", dependencies=WRITE)
def account_password(request: Request, background: BackgroundTasks, current: str = Form(""),
                     password: str = Form(""), password2: str = Form(""),
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        if password != password2:
            raise AccountError("Die beiden neuen Passwörter stimmen nicht überein.")
        accounts.change_password(db, user, current, password)
    except AccountError as exc:
        flash(request, str(exc), "error")
        return redirect("/konto")
    request.session["sv"] = user.session_version  # diese Sitzung bleibt angemeldet
    mail.send(background, user.email, "Dein Passwort wurde geändert", "password_changed",
              name=user.name, link=f"{BASE_URL}/passwort-vergessen")
    flash(request, "Passwort geändert. Andere Geräte wurden abgemeldet.")
    return redirect("/konto")


@router.get("/konto/export")
def account_export(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    data = json.dumps(accounts.export_data(db, user), ensure_ascii=False, indent=2)
    return Response(data, media_type="application/json", headers={
        "Content-Disposition": 'attachment; filename="courtslot-meine-daten.json"'})


@router.post("/konto/verein/{club_id}/verlassen", dependencies=WRITE)
def account_leave(request: Request, club_id: int, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    try:
        accounts.leave_club(db, user, club_id)
        flash(request, "Du hast den Verein verlassen. Kommende Buchungen dort sind storniert.")
    except AccountError as exc:
        flash(request, str(exc), "error")
    return redirect("/konto")


@router.post("/konto/loeschen", dependencies=WRITE)
def account_delete(request: Request, background: BackgroundTasks, password: str = Form(""),
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    email, name = user.email, user.name
    try:
        accounts.delete_account(db, user, password)
    except AccountError as exc:
        flash(request, str(exc), "error")
        return redirect("/konto")
    mail.send(background, email, "Dein CourtSlot-Konto wurde gelöscht", "deleted", name=name)
    request.session.clear()
    return render(request, "message.html", title="Konto gelöscht",
                  message="Deine Daten sind gelöscht und kommende Buchungen storniert.",
                  action=("/login", "Zur Startseite"))
