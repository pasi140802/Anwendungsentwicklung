from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import verify_csrf, verify_password
from app.web import redirect, render

router = APIRouter()

LOGIN_ERROR = "E-Mail-Adresse oder Passwort ist falsch."


@router.get("/login")
def login_form(request: Request):
    if request.session.get("user_id"):
        return redirect("/kalender")
    return render(request, "login.html")


@router.post("/login", dependencies=[Depends(verify_csrf)])
def login(request: Request, email: str = Form(...), password: str = Form(...),
          db: Session = Depends(get_db)):
    user = db.scalars(select(User).where(User.email == email.strip().lower())).first()
    # Gleiche Meldung für unbekannte E-Mail und falsches Passwort (US-01).
    if user is None or not user.is_active or not verify_password(user.password_hash, password):
        return render(request, "login.html", status_code=400, error=LOGIN_ERROR, email=email)
    csrf = request.session.get("csrf")
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["csrf"] = csrf
    return redirect("/kalender")


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request):
    request.session.clear()
    return redirect("/login")
