# Troubleshooting

## The stack will not start

**"Docker Desktop is not installed" or Docker never becomes ready.** Install Docker Desktop and start it once manually. `start.bat` waits up to two minutes for it.

**A port is already in use.** The defaults are web 3000, API 8000, database 5433, Redis 6379, Mailpit 8025 and 1025. Change the matching `*_PORT` value in `.env` (created from `.env.example` on first run) and run `start.bat` again. The database uses 5433 so it does not clash with a local PostgreSQL on 5432.

**The API never becomes ready.** Run `docker compose logs api`. The most common causes are a still-starting database (wait a few seconds) or a stale volume from an older version; `reset.bat` deletes all data and starts clean.

**Everything is slow on first start.** The first run builds all images. Later starts take seconds.

## I cannot sign in

The seeded accounts are `owner@`, `admin@`, `agent@` and `viewer@brightwork.test` with the password `resolveflow-demo`. Seeding only runs when the database has no workspace at all. If you signed up for your own workspace first, the demo accounts do not exist: run `reset.bat` to recreate them.

Too many failed attempts are rate limited; wait a minute and try again.

## Email

**Where did my outgoing email go?** To Mailpit at http://localhost:8025. Nothing is sent to the internet by default.

**How do I receive a customer email locally?** In **Channels**, use **Send simulated email**. It runs the same code as the real Postmark webhook.

**Using Postmark for real.** Put `EMAIL_PROVIDER=postmark` and `POSTMARK_SERVER_TOKEN=...` in `.env`, then `docker compose up -d`. A new Postmark account can only send to addresses on the same domain as your verified sender until it is approved. Mail from a university or company domain may be marked as spam if that domain's mail policy does not allow Postmark; check the spam folder first.

## Deadlines and notifications look wrong

**A ticket has no deadline.** Service levels may be switched off (Service levels page), or the ticket is paused because its status is *pending*.

**Deadlines seem to be in the wrong time.** Targets count business hours in the workspace timezone set on the Service levels page. Deadlines are shown in your browser's local time.

**The notification bell is behind.** It refreshes about every 20 seconds. Notification emails are sent by the scheduler about every 30 seconds.

**Warnings and breaches are not appearing.** The scheduler (`beat`) and `worker` containers must be running: `docker compose ps`. After a restart they catch up immediately.

## Automations

**"Make live" is disabled.** The current version has no passing test yet, or you have unsaved changes. Save, run **Test it**, choose **Record as test** (the test must be expected to match and must pass), then **Make live**.

**A rule did not run.** Check that it is live (not draft or archived), that its trigger matches the event, and that an earlier rule has not already set the same thing. Open the ticket and expand **Automations that ran** to see what happened and why.

**Two rules fight over the assignee.** The first rule in the list wins. Reorder them on the Automations page.

## Data

**Where is my data?** In the Docker volume `resolveflow_pgdata`. `stop.bat` keeps it; `reset.bat` deletes it.

**I want to start over.** `reset.bat`.

## Developing

**Backend tests fail to start.** They need Docker running (they start PostgreSQL and Redis). Alternatively set `TEST_DATABASE_URL` and `TEST_REDIS_URL`.

**Playwright cannot find a browser.** Run `npx playwright install chromium` or set `E2E_CHANNEL=chrome` to use installed Chrome.

**The browser shows an old version of the app.** Rebuild with `docker compose up -d --build`, and hard-reload the page.

**A file shows odd characters.** Write source files as UTF-8.
