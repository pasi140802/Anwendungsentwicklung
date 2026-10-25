"""Impressum und Datenschutzerklärung (Pflichtseiten für den Echtbetrieb)."""

from fastapi import APIRouter, Request

from app import config
from app.web import render

router = APIRouter()


def _operator() -> dict:
    return {"name": config.OPERATOR_NAME, "address": config.OPERATOR_ADDRESS,
            "email": config.OPERATOR_EMAIL}


@router.get("/impressum")
def imprint(request: Request):
    return render(request, "legal/imprint.html", operator=_operator())


@router.get("/datenschutz")
def privacy(request: Request):
    return render(request, "legal/privacy.html", operator=_operator())
