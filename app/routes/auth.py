"""Anmeldung, Registrierung, E-Mail-Bestätigung und Passwort vergessen."""

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from sqlalchemy.orm import Session

from app import mail, ratelimit
from app.config import BASE_URL
from app.db import get_db
from app.models import User
from app.security import get_current_user, start_session, verify_csrf
from app.services import accounts
from app.services.accounts import AccountError
from app.web import flash, redirect, render

router = APIRouter()
WRITE = [Depends(verify_csrf)]

LOGIN_ERROR = "E-Mail-Adresse oder Passwort ist falsch."
TOO_MANY = "Zu viele Versuche. Bitte warte ein paar Minuten."


def _safe_next(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/kalender"


def send_verification(background: BackgroundTasks, user: User) -> None:
    link = f"{BASE_URL}/registrieren/bestaetigen/{accounts.verify_token(user)}"
    mail.send(background, user.email, "Bitte bestätige deine E-Mail-Adresse", "verify",
              name=user.name, link=link)


# --- Anmelden und Abmelden -----------------------------------------------------------

@router.get("/login")
def login_form(request: Request, next: str | None = None):
    if request.session.get("user_id"):
        return redirect(_safe_next(next))
    return render(request, "login.html", next=next)


@router.post("/login", dependencies=WRITE)
def login(request: Request, email: str = Form(...), password: str = Form(...),
          next: str | None = Form(None), db: Session = Depends(get_db)):
    key = email.strip().lower()
    if not (ratelimit.login_by_email.hit(key)
            and ratelimit.login_by_ip.hit(ratelimit.client_ip(request))):
        return render(request, "login.html", status_code=429, error=TOO_MANY, email=email,
                      next=next)
    user = accounts.authenticate(db, email, password)
    if user is None:
        return render(request, "login.html", status_code=400, error=LOGIN_ERROR, email=email,
                      next=next)
    if not user.is_verified:
        return render(request, "login.html", status_code=400, email=email, next=next,
                      unverified=True,
                      error="Bitte bestätige zuerst deine E-Mail-Adresse über den Link "
                            "in unserer Mail.")
    start_session(request, user)
    return redirect(_safe_next(next))


@router.post("/logout", dependencies=WRITE)
def logout(request: Request, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    # Sitzungsversion erhöhen: kopierte Cookies dieser Sitzung werden ungültig.
    user.session_version += 1
    db.commit()
    request.session.clear()
    return redirect("/login")


# --- Registrierung ------------------------------------------------------------------

@router.get("/registrieren")
def register_form(request: Request, next: str | None = None, email: str | None = None,
                  invite: str | None = None):
    return render(request, "register.html", next=next, invite=invite,
                  form={"email": email or ""})


@router.post("/registrieren", dependencies=WRITE)
def register(request: Request, background: BackgroundTasks, name: str = Form(""),
             email: str = Form(""), password: str = Form(""), password2: str = Form(""),
             consent: str | None = Form(None), next: str | None = Form(None),
             invite: str | None = Form(None), db: Session = Depends(get_db)):
    form = {"name": name, "email": email}
    ctx = {"form": form, "next": next, "invite": invite}
    error = None
    if password != password2:
        error = "Die beiden Passwörter stimmen nicht überein."
    elif not consent:
        error = "Bitte bestätige, dass du die Datenschutzerklärung gelesen hast."
    elif not ratelimit.mail_by_ip.hit(ratelimit.client_ip(request)):
        error = TOO_MANY
    if error:
        return render(request, "register.html", status_code=400, error=error, **ctx)
    # Kommt die Registrierung aus einer Einladung an genau diese Adresse, ist sie
    # damit bereits bestätigt.
    invited = False
    if invite:
        try:
            inv = accounts.invitation_from_token(db, invite)
            invited = inv.email == email.strip().lower()
        except AccountError:
            invited = False
    try:
        new, existing = accounts.register(db, name, email, password, verified=invited)
    except AccountError as exc:
        return render(request, "register.html", status_code=400, error=str(exc), **ctx)
    if new is not None and invited:
        start_session(request, new)
        return redirect(f"/einladung/{invite}")
    if new is not None:
        send_verification(background, new)
        if next:
            request.session["after_verify"] = _safe_next(next)
    else:
        mail.send(background, existing.email, "Du hast bereits ein CourtSlot-Konto",
                  "already_registered", name=existing.name,
                  link=f"{BASE_URL}/passwort-vergessen")
    return render(request, "check_email.html", email=email.strip().lower(), purpose="register")


@router.get("/registrieren/bestaetigen/{token}")
def confirm(request: Request, token: str, db: Session = Depends(get_db)):
    try:
        user = accounts.confirm_email(db, token)
    except AccountError as exc:
        return render(request, "message.html", status_code=400, title="Link nicht gültig",
                      message=str(exc), action=("/bestaetigung-erneut", "Neuen Link anfordern"))
    after = request.session.pop("after_verify", None)
    start_session(request, user)
    flash(request, "E-Mail-Adresse bestätigt. Willkommen bei CourtSlot!")
    return redirect(after or "/start")


@router.get("/bestaetigung-erneut")
def resend_form(request: Request):
    return render(request, "resend.html")


@router.post("/bestaetigung-erneut", dependencies=WRITE)
def resend(request: Request, background: BackgroundTasks, email: str = Form(""),
           db: Session = Depends(get_db)):
    if ratelimit.mail_by_ip.hit(ratelimit.client_ip(request)):
        user = accounts.find_user(db, email.strip().lower())
        if user is not None and not user.is_verified and not user.is_deleted:
            send_verification(background, user)
    return render(request, "check_email.html", email=email.strip().lower(), purpose="register")


# --- Passwort vergessen -------------------------------------------------------------

@router.get("/passwort-vergessen")
def forgot_form(request: Request):
    return render(request, "forgot.html")


@router.post("/passwort-vergessen", dependencies=WRITE)
def forgot(request: Request, background: BackgroundTasks, email: str = Form(""),
           db: Session = Depends(get_db)):
    if ratelimit.mail_by_ip.hit(ratelimit.client_ip(request)):
        user = accounts.find_user(db, email.strip().lower())
        if user is not None and user.is_active and not user.is_deleted:
            link = f"{BASE_URL}/passwort-neu/{accounts.reset_token(user)}"
            mail.send(background, user.email, "Neues Passwort für CourtSlot", "reset",
                      name=user.name, link=link)
    # Immer dieselbe Antwort, egal ob die Adresse existiert.
    return render(request, "check_email.html", email=email.strip().lower(), purpose="reset")


@router.get("/passwort-neu/{token}")
def reset_form(request: Request, token: str, db: Session = Depends(get_db)):
    try:
        accounts.user_for_reset(db, token)
    except AccountError as exc:
        return render(request, "message.html", status_code=400, title="Link nicht gültig",
                      message=str(exc), action=("/passwort-vergessen", "Neuen Link anfordern"))
    return render(request, "reset.html", token=token)


@router.post("/passwort-neu/{token}", dependencies=WRITE)
def reset(request: Request, token: str, password: str = Form(""), password2: str = Form(""),
          db: Session = Depends(get_db)):
    try:
        user = accounts.user_for_reset(db, token)
        if password != password2:
            raise AccountError("Die beiden Passwörter stimmen nicht überein.")
        accounts.set_password(db, user, password)
    except AccountError as exc:
        return render(request, "reset.html", status_code=400, token=token, error=str(exc))
    start_session(request, user)
    flash(request, "Passwort geändert. Alle anderen Sitzungen wurden abgemeldet.")
    return redirect("/kalender")
