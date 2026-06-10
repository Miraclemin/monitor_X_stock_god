import smtplib
from email.message import EmailMessage

from config import load_config


def send_email(subject, body_text, body_html=None):
    settings = (load_config().get("email") or {})
    if not settings.get("enabled"):
        return False

    recipients = settings.get("to") or []
    if isinstance(recipients, str):
        recipients = [recipients]
    if not recipients:
        print("email warning: no recipients configured")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.get("from") or settings.get("user")
    msg["To"] = ", ".join(recipients)
    msg.set_content(body_text or "")
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    try:
        with smtplib.SMTP(settings["smtp_host"], int(settings.get("smtp_port", 587)), timeout=30) as smtp:
            if settings.get("use_tls", True):
                smtp.starttls()
            smtp.login(settings["user"], settings["password"])
            smtp.send_message(msg)
        return True
    except Exception as exc:
        print(f"email warning: {exc}")
        return False
