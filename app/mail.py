"""E-Mail-Versand über SMTP mit Text- und HTML-Teil.

Ohne SMTP_HOST werden Mails nicht verschickt, sondern protokolliert und in
OUTBOX abgelegt (Entwicklung und Tests). Lokal fängt Mailpit alle Mails ab.
"""

import logging
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

from fastapi import BackgroundTasks

from app import config
from app.web import templates

log = logging.getLogger("courtslot.mail")
OUTBOX: list[EmailMessage] = []


def build(to: str, subject: str, template: str, **context) -> EmailMessage:
    context.setdefault("base_url", config.BASE_URL)
    msg = EmailMessage()
    msg["From"] = config.MAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="courtslot")
    msg.set_content(templates.get_template(f"mail/{template}.txt").render(**context))
    msg.add_alternative(
        templates.get_template(f"mail/{template}.html").render(**context), subtype="html"
    )
    return msg


def deliver(msg: EmailMessage) -> None:
    if not config.SMTP_HOST:
        OUTBOX.append(msg)
        log.info("Mail (nicht versendet) an %s: %s", msg["To"], msg["Subject"])
        return
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as smtp:
            if config.SMTP_STARTTLS:
                smtp.starttls()
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException):
        log.exception("Mailversand an %s fehlgeschlagen", msg["To"])


def send(background: BackgroundTasks | None, to: str, subject: str, template: str,
         **context) -> None:
    """Baut die Mail sofort und verschickt sie nach der Antwort an den Browser."""
    msg = build(to, subject, template, **context)
    if background is None:
        deliver(msg)
    else:
        background.add_task(deliver, msg)


def link_in(msg: EmailMessage) -> str:
    """Erster Link im Textteil (für Tests)."""
    import re

    body = msg.get_body(preferencelist=("plain",)).get_content()
    return re.search(r"https?://\S+", body).group(0)
