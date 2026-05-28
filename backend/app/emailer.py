"""Tiny email sender. SMTP when configured; console fallback for local dev.

Env (set any SMTP provider — Gmail, SendGrid, Mailgun, Resend SMTP relay, ...):
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
If SMTP_HOST is unset, the email body is printed to the server log instead — handy locally.
"""
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger("mostakhles.email")


def send_email(to: str, subject: str, body_text: str, body_html: str | None = None) -> None:
    host = os.getenv("SMTP_HOST")
    if not host:
        log.warning("[email console-fallback] to=%s subject=%s\n%s", to, subject, body_text)
        return
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM") or user

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    ctx = ssl.create_default_context()
    with smtplib.SMTP(host, port) as s:
        s.starttls(context=ctx)
        if user and password:
            s.login(user, password)
        s.send_message(msg)


def send_verification_email(to: str, verify_url: str) -> None:
    subject = "تأكيد بريدك الإلكتروني — مُستخلِص"
    text = (
        f"مرحبًا،\n\n"
        f"اضغط الرابط التالي لتأكيد بريدك الإلكتروني وتفعيل حسابك في مُستخلِص:\n\n"
        f"{verify_url}\n\n"
        f"إن لم تنشئ هذا الحساب، يمكنك تجاهل هذه الرسالة.\n"
    )
    html = (
        f"<div style='font-family:Cairo,system-ui,sans-serif;direction:rtl;text-align:right;"
        f"max-width:520px;margin:auto;line-height:1.8;color:#1b1813'>"
        f"<h2 style='color:#0a564f'>أهلًا بك في مُستخلِص</h2>"
        f"<p>اضغط الزر التالي لتأكيد بريدك الإلكتروني وتفعيل حسابك:</p>"
        f"<p><a href='{verify_url}' style='display:inline-block;background:#0f766e;color:#fff;"
        f"padding:12px 22px;border-radius:10px;text-decoration:none;font-weight:700'>تأكيد البريد</a></p>"
        f"<p style='color:#7a7165;font-size:13px'>أو انسخ هذا الرابط في متصفّحك:<br><code>{verify_url}</code></p>"
        f"<p style='color:#7a7165;font-size:13px'>إن لم تنشئ هذا الحساب، تجاهل هذه الرسالة.</p>"
        f"</div>"
    )
    send_email(to, subject, text, html)
