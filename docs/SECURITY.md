# Security and privacy

## What is enforced

- **Authentication.** Email and password, hashed with Argon2. Sessions are random tokens stored only as a SHA-256 hash, delivered in an HTTP-only, SameSite cookie. State-changing requests need a per-session CSRF token header.
- **Brute-force limits.** Login attempts are limited per address and per account; the public form is limited per address and workspace. The web proxy overwrites `X-Forwarded-For` so a client cannot spoof the address the limiter sees.
- **Roles.** Owner, Admin, Agent and Viewer. Every endpoint declares the permission it needs and the UI hides what you cannot use. The last owner cannot be removed.
- **Tenant isolation.** Row-level security on every tenant table, forced even for the table owner. The API role cannot bypass it. Tests check that another workspace's tickets, rules, notifications and customers are never returned.
- **Input handling.** SQL is parameterised. Email subjects and headers are stripped of line breaks. Search snippets are escaped before highlighting, and the UI renders them as text.
- **Response headers.** `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on every API response, and a same-origin Content-Security-Policy on the web app.
- **Secrets.** `.env` is git-ignored and `.env.example` holds development defaults only. The demo data is synthetic.

## Data retention

Under **Privacy**, an owner or admin can choose to remove content after 30 days to 2 years. Resolved and closed tickets untouched for that long lose their message text, subject and notifications. A customer whose tickets have all expired loses their name and email. The ticket number, dates, priority and SLA results stay so analytics remain correct. A check runs every hour, and **Remove expired content now** runs it on demand. Both are recorded in the audit log.

## Known limits

- The audit log is append-only by design, so it keeps the subject recorded when a ticket was created, even after redaction. Backups and database snapshots are outside the application's reach.
- Rule and email-provider credentials are not encrypted in the database. The Postmark token is read from the environment only.
- The demo setup uses plain HTTP on localhost. A real deployment needs HTTPS and `COOKIE_SECURE=true`.
- There is no two-factor sign-in and no single sign-on.
- Notifications are delivered by polling every 20 seconds rather than a live connection.
