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


def send_password_reset_email(to: str, reset_url: str) -> None:
    subject = "إعادة تعيين كلمة المرور — مُستخلِص"
    text = (
        f"تلقّينا طلب إعادة تعيين كلمة مرور حسابك في مُستخلِص.\n\n"
        f"اضغط الرابط التالي لتعيين كلمة مرور جديدة (صالح لمدة ساعة واحدة فقط):\n\n"
        f"{reset_url}\n\n"
        f"إن لم تطلب هذا، يمكنك تجاهل هذه الرسالة — لن يتغيّر شيء.\n"
    )
    html = (
        f"<div style='font-family:Cairo,system-ui,sans-serif;direction:rtl;text-align:right;"
        f"max-width:520px;margin:auto;line-height:1.8;color:#1b1813'>"
        f"<h2 style='color:#0a564f'>إعادة تعيين كلمة المرور</h2>"
        f"<p>تلقّينا طلب إعادة تعيين كلمة مرور حسابك. اضغط الزر لاختيار كلمة مرور جديدة:</p>"
        f"<p><a href='{reset_url}' style='display:inline-block;background:#0f766e;color:#fff;"
        f"padding:12px 22px;border-radius:10px;text-decoration:none;font-weight:700'>تعيين كلمة مرور جديدة</a></p>"
        f"<p style='color:#7a7165;font-size:13px'>الرابط صالح لمدة ساعة واحدة فقط.</p>"
        f"<p style='color:#7a7165;font-size:13px'>إن لم تطلب إعادة التعيين، تجاهل هذه الرسالة.</p>"
        f"</div>"
    )
    send_email(to, subject, text, html)


def send_high_utilization_email(to: str, plan: str, used: int, limit: int,
                                 next_plan: str) -> None:
    """Nudge a paid user who hit ≥75% of monthly cap toward the next tier."""
    pct = int(round(100 * used / max(limit, 1)))
    upgrade_url = (os.getenv("PUBLIC_URL", "").rstrip("/") +
                   f"/billing/checkout?plan={next_plan}") or "/pricing"
    plan_label = plan.capitalize()
    next_label = next_plan.capitalize()
    subject_ar = f"استخدمت {pct}٪ من خطتك — مُستخلِص"
    text_ar = (
        f"مرحبًا،\n\n"
        f"لاحظنا أنك استخدمت {used:,} من أصل {limit:,} نقطة ({pct}٪) في خطة {plan_label} هذا الشهر.\n\n"
        f"إذا واصلت بنفس الوتيرة قد تتجاوز الحد قبل نهاية الشهر. يمكنك الترقية الآن إلى "
        f"خطة {next_label} لمضاعفة سعتك بدون انقطاع في الخدمة:\n\n"
        f"{upgrade_url}\n\n"
        f"إن لم تكن بحاجة للترقية، تجاهل هذه الرسالة — حسابك يستمر بشكل طبيعي حتى تستهلك الحد.\n"
    )
    html_ar = (
        f"<div style='font-family:Cairo,system-ui,sans-serif;direction:rtl;text-align:right;"
        f"max-width:520px;margin:auto;line-height:1.8;color:#1b1813'>"
        f"<h2 style='color:#0a564f'>استخدمت {pct}٪ من خطتك</h2>"
        f"<p>وصلت إلى <strong>{used:,}</strong> من أصل <strong>{limit:,}</strong> نقطة في خطة "
        f"<strong>{plan_label}</strong> هذا الشهر.</p>"
        f"<p>للحفاظ على استمرار الخدمة بدون انقطاع، يمكنك الترقية إلى خطة <strong>{next_label}</strong>:</p>"
        f"<p><a href='{upgrade_url}' style='display:inline-block;background:#0f766e;color:#fff;"
        f"padding:12px 22px;border-radius:10px;text-decoration:none;font-weight:700'>"
        f"الترقية إلى {next_label}</a></p>"
        f"<p style='color:#7a7165;font-size:13px'>إن لم تكن بحاجة، تجاهل هذه الرسالة.</p>"
        f"</div>"
    )
    send_email(to, subject_ar, text_ar, html_ar)


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


def send_renewal_reminder_email(to: str, *, plan: str, renews_on: str,
                                amount_usd: float, days_remaining: int,
                                provider: str, manage_url: str) -> None:
    """Notify a paid user N days before their subscription renews.

    The subscription will auto-renew at the provider (Paymob or PayPal); this
    email is informational + a chance to cancel before the next charge.
    Bilingual content like the other transactional emails."""
    plan_label = plan.capitalize()
    provider_label = "PayPal" if provider == "paypal" else "Paymob"

    subject = f"تجديد خطة {plan_label} بعد {days_remaining} أيام — مُستخلِص"

    text = (
        f"مرحبًا،\n\n"
        f"خطة {plan_label} الخاصة بك ستتجدّد تلقائيًا في {renews_on} عبر {provider_label} "
        f"بمبلغ {amount_usd:g} دولار.\n\n"
        f"لا تحتاج لفعل أي شيء — التجديد تلقائي. إن أردت الإلغاء قبل التجديد، "
        f"يمكنك ذلك بنقرة واحدة من إعدادات الحساب:\n\n"
        f"{manage_url}\n\n"
        f"شكرًا لاستخدامك مُستخلِص.\n"
    )
    html = (
        f"<div style='font-family:Cairo,system-ui,sans-serif;direction:rtl;text-align:right;"
        f"max-width:560px;margin:auto;line-height:1.8;color:#1b1813'>"
        f"<h2 style='color:#0a564f;margin:0 0 14px'>تجديد خطّتك بعد {days_remaining} أيام</h2>"
        f"<p>خطة <strong>{plan_label}</strong> الخاصة بك ستتجدّد تلقائيًا في "
        f"<strong>{renews_on}</strong>.</p>"
        f"<table style='width:100%;border-collapse:collapse;margin:18px 0;background:#f9faf7;"
        f"border-radius:10px;padding:0'>"
        f"<tr><td style='padding:10px 14px;color:#5b554b'>المبلغ</td>"
        f"<td style='padding:10px 14px;text-align:left;font-weight:700;font-family:ui-monospace,monospace'>"
        f"${amount_usd:g}</td></tr>"
        f"<tr><td style='padding:10px 14px;color:#5b554b'>طريقة الدفع</td>"
        f"<td style='padding:10px 14px;text-align:left;font-weight:700'>{provider_label}</td></tr>"
        f"<tr><td style='padding:10px 14px;color:#5b554b'>تاريخ التجديد</td>"
        f"<td style='padding:10px 14px;text-align:left;font-weight:700'>{renews_on}</td></tr>"
        f"</table>"
        f"<p>التجديد تلقائي — لا تحتاج لفعل أي شيء. إن أردت الإلغاء قبل ذلك:</p>"
        f"<p><a href='{manage_url}' style='display:inline-block;background:#0f766e;color:#fff;"
        f"padding:12px 22px;border-radius:10px;text-decoration:none;font-weight:700'>"
        f"إدارة الاشتراك</a></p>"
        f"<p style='color:#7a7165;font-size:13px;margin-top:24px'>"
        f"Your <strong>{plan_label}</strong> plan auto-renews on {renews_on} via "
        f"{provider_label} for ${amount_usd:g}. Cancel any time from your account.</p>"
        f"</div>"
    )
    send_email(to, subject, text, html)
