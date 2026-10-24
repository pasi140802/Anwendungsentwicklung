from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import get_current_user, hash_password, verify_csrf, verify_password
from app.web import redirect, render

router = APIRouter()

LOGIN_ERROR = "E-Mail-Adresse oder Passwort ist falsch."
DUMMY_HASH = hash_password("kein-benutzer-vorhanden")


@router.get("/login")
def login_form(request: Request):
    if request.session.get("user_id"):
        return redirect("/kalender")
    return render(request, "login.html")


@router.post("/login", dependencies=[Depends(verify_csrf)])
def login(request: Request, email: str = Form(...), password: str = Form(...),
          db: Session = Depends(get_db)):
    user = db.scalars(select(User).where(User.email == email.strip().lower())).first()
    # Gleiche Meldung und gleiche Rechenzeit für unbekannte E-Mail und falsches
    # Passwort (US-01): auch ohne Benutzer wird ein Argon2-Hash geprüft.
    password_ok = verify_password(user.password_hash if user else DUMMY_HASH, password)
    if user is None or not user.is_active or not password_ok:
        return render(request, "login.html", status_code=400, error=LOGIN_ERROR, email=email)
    csrf = request.session.get("csrf")
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["sv"] = user.session_version
    request.session["csrf"] = csrf
    return redirect("/kalender")


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    # Sitzungsversion erhöhen: kopierte Cookies dieser Sitzung werden ungültig.
    user.session_version += 1
    db.commit()
    request.session.clear()
    return redirect("/login")
