# Cookie Policy — Mostakhles

<!--
DRAFT — not legal advice. This policy is grounded in the cookies / local storage
and third-party requests the codebase actually uses today (server session cookie,
CSRF token, language cookie, theme in localStorage, Cloudflare Turnstile on forms,
Sentry error monitoring, Google Fonts). If you add analytics or marketing cookies
later, update the table AND add a consent banner. Fill [[FOUNDER TO CONFIRM: …]].
-->

**Effective date:** [[FOUNDER TO CONFIRM: effective date]]
**Last updated:** [[FOUNDER TO CONFIRM: effective date]]

> **Arabic:** نسخة عربية كاملة قيد الإعداد. النص الإنجليزي هو المرجع.

This Cookie Policy explains how Mostakhles uses cookies and similar technologies
(such as browser local storage) on our website and web app.

## 1. What are cookies?

Cookies are small text files a website stores in your browser. "Local storage" is a
related browser feature that stores small settings on your device. We use both only
as described below.

## 2. The cookies and storage we use

We currently use **only strictly necessary and functional** cookies/storage. We do
**not** use advertising cookies, and we do not currently run third-party marketing
or behavioural-analytics trackers.

| Name / item | Type | Purpose | Duration |
|---|---|---|---|
| Session cookie | Strictly necessary (HTTP-only) | Keeps you logged in | Up to ~30 days / until logout |
| CSRF token | Strictly necessary | Protects against cross-site request forgery | Session |
| Language preference | Functional (cookie) | Remembers Arabic/English choice | ~1 year |
| Theme preference | Functional (browser local storage, not a cookie) | Remembers light/dark mode | Until you clear it |
| Cloudflare Turnstile | Strictly necessary (security) | Bot / abuse protection on forms (login, signup, contact) | Short-lived, per interaction |

## 3. Third-party requests

Some pages load resources from third parties. These may allow that third party to
receive your IP address and basic request data:

- **Cloudflare Turnstile** — bot protection on forms. Processes IP and browser
  signals to tell humans from bots. Strictly necessary for abuse prevention.
- **Google Fonts** — some pages load fonts from Google's font service, which means
  your browser makes a request to Google to fetch fonts.
  [[FOUNDER TO CONFIRM: consider self-hosting the font to avoid this third-party
  request entirely — a common privacy hardening step.]]
- **Sentry** — our error-monitoring sub-processor. It runs to capture technical
  diagnostics if something breaks; it is not an advertising or tracking tool.

We do not control third parties' own cookie practices; see their policies for detail.

## 4. What we do NOT use

- No advertising or retargeting cookies.
- No cross-site behavioural tracking.
- No selling of any data collected via cookies.

## 5. Managing cookies

Because we currently use only strictly-necessary and functional cookies/storage, no
consent banner is strictly required for them — but you can still control them:

- Most browsers let you block or delete cookies and clear local storage in their
  settings. Blocking strictly-necessary cookies may break login and forms.
- You can switch language/theme back at any time in the app.

> If Mostakhles later adds analytics or marketing cookies, we will add a consent
> mechanism (opt-in where required) and update this table before those cookies run.

## 6. Changes

We will update this policy if our cookie use changes, and revise the "Last updated"
date.

## 7. Contact

[[FOUNDER TO CONFIRM: privacy contact email]] · contact form at `/contact`.
