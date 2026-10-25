"""Mailversand: Inhalt der Mails und Übergabe an den SMTP-Server."""

from app import config, mail


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout):
        self.calls = [("connect", host, port)]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        FakeSMTP.sent.append(self.calls)

    def starttls(self):
        self.calls.append(("starttls",))

    def login(self, user, password):
        self.calls.append(("login", user))

    def send_message(self, msg):
        self.calls.append(("send", msg["To"]))


def test_mail_has_text_and_html(world):
    msg = mail.build("lena@a.de", "Gebucht", "booking_confirmed", name="Lena", club="TC A & B",
                     court="Padel 1", when="Di 03.11.2026, 17:00 Uhr", until="18:30",
                     price=2400, link="http://x/meine-buchungen")
    text = msg.get_body(("plain",)).get_content()
    html = msg.get_body(("html",)).get_content()
    assert "TC A & B" in text and "24\u00a0€" in text  # Textteil ohne HTML-Escaping
    assert "TC A &amp; B" in html and "http://x/meine-buchungen" in html


def test_deliver_via_smtp(monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.de")
    monkeypatch.setattr(config, "SMTP_USER", "user")
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent.clear()
    msg = mail.build("x@example.de", "Test", "deleted", name="X")
    mail.deliver(msg)
    calls = FakeSMTP.sent[0]
    assert calls[0] == ("connect", "smtp.example.de", config.SMTP_PORT)
    assert ("starttls",) in calls and ("login", "user") in calls
    assert ("send", "x@example.de") in calls
    assert mail.OUTBOX == []


def test_deliver_failure_is_logged_not_raised(monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise OSError("keine Verbindung")

    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.de")
    monkeypatch.setattr(mail.smtplib, "SMTP", broken)
    mail.deliver(mail.build("x@example.de", "Test", "deleted", name="X"))
    assert "fehlgeschlagen" in caplog.text
