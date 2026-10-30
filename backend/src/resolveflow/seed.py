"""Synthetic demo workspace: users per role, customers, tickets with histories, tags, audit.

Run with `python -m resolveflow.seed [--if-empty]`. All names and addresses are fictional.
"""

import argparse
import json
import random
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from resolveflow.context import SystemContext
from resolveflow.db import system_engine
from resolveflow.notifications import service as notif
from resolveflow.rules.schema import RuleDefinition, canonical_hash
from resolveflow.security import hash_password
from resolveflow.sla import service as sla_service
from resolveflow.sla.defaults import create_defaults

DEMO_PASSWORD = "resolveflow-demo"  # noqa: S105 - documented demo credential, synthetic data only
SLUG = "brightwork"

USERS = {
    "owner": ("owner@brightwork.test", "Priya Raman"),
    "admin": ("admin@brightwork.test", "Jonas Weber"),
    "agent": ("agent@brightwork.test", "Lena Okafor"),
    "viewer": ("viewer@brightwork.test", "Tom Alvarez"),
}

CUSTOMERS = [
    ("Sana Iqbal", "sana@harborcafe.test"),
    ("Marcus Lindqvist", "marcus@northwind-bikes.test"),
    ("Aiko Tanaka", "aiko@tanaka-dental.test"),
    ("Dev Patel", "dev@patel-logistics.test"),
    ("Hannah Brooks", "hannah@brooksandco.test"),
    ("Luis Ortega", "luis@ortega-tiles.test"),
    ("Freya Nilsen", "freya@nilsen-yoga.test"),
    ("Omar Haddad", "omar@haddad-bakery.test"),
    ("Chloe Martin", "chloe@martin-florals.test"),
    ("Ravi Menon", "ravi@menon-legal.test"),
    ("Isla Campbell", "isla@campbell-vets.test"),
    ("Kwame Boateng", "kwame@boateng-print.test"),
    ("Elena Petrova", "elena@petrova-studio.test"),
    ("Noah Fischer", "noah@fischer-garden.test"),
    ("Mei Lin", "mei@linhomes.test"),
    ("Tariq Aziz", "tariq@aziz-motors.test"),
    ("Grace Adeyemi", "grace@adeyemi-events.test"),
    ("Pablo Vega", "pablo@vega-coffee.test"),
    ("Yara Khoury", "yara@khoury-optics.test"),
    ("Sven Larsen", "sven@larsen-boats.test"),
    ("Amara Obi", "amara@obi-fashion.test"),
    ("Jack Sullivan", "jack@sullivan-plumbing.test"),
    ("Nina Rossi", "nina@rossi-pizza.test"),
    ("Hiro Sato", "hiro@sato-ramen.test"),
    ("Zoe Carter", "zoe@carter-books.test"),
]

SUBJECTS = [
    (
        "Logo files never arrived",
        "Hi, we paid for the logo package last week but I still have not received the final files. Could you send them over?",
    ),
    (
        "Question about invoice 1042",
        "The total on invoice 1042 looks higher than the quote we agreed. Can someone explain the difference?",
    ),
    (
        "Website is down",
        "Our homepage is showing an error since this morning. We have customers trying to book. Please help!",
    ),
    (
        "Can we move the launch date?",
        "Our team needs another week before launch. Is it possible to push the go-live to the 21st?",
    ),
    (
        "Contact form not sending",
        "Test submissions from the contact form on our site are not reaching our inbox.",
    ),
    (
        "Need an extra page added",
        "We would like to add a Careers page to the site. What would it cost and how long would it take?",
    ),
    (
        "Refund for cancelled session",
        "I cancelled the workshop more than 48 hours ahead but was still charged. Could I get a refund?",
    ),
    (
        "How do I update my opening hours?",
        "We changed our opening hours for the summer. Where can I update them on the site?",
    ),
    (
        "Photos look blurry on mobile",
        "The gallery photos look blurry on phones. They are fine on desktop.",
    ),
    (
        "Password reset email missing",
        "I asked for a password reset three times and nothing arrives.",
    ),
    (
        "Quote for a newsletter template",
        "We are planning a monthly newsletter and need a template that matches our brand.",
    ),
    (
        "Domain renewal reminder",
        "Our domain seems to expire next month. Is renewal included in our plan?",
    ),
    (
        "Wrong phone number in footer",
        "The footer shows our old phone number. Please change it to the new one.",
    ),
    (
        "Feedback on the first mockups",
        "We love the direction. A few notes on the colour palette and the hero image, see below.",
    ),
    (
        "Booking widget double-charging",
        "A customer says they were charged twice when booking through the widget on our site.",
    ),
    (
        "Can I get a copy of last month's report?",
        "Could you resend the analytics report for last month? I cannot find the email.",
    ),
    ("Menu PDF out of date", "The menu PDF linked on the site still shows the old prices."),
    (
        "SSL certificate warning",
        "Some visitors see a security warning when opening our site. Is the certificate expired?",
    ),
    (
        "Training session for my team",
        "Could you run a short training session on how to edit the site for three of our staff?",
    ),
    (
        "Delivery area map is wrong",
        "The map on the delivery page still shows the old postcode area.",
    ),
]

REPLIES = [
    "Thanks for getting in touch. I'm looking into this now and will come back to you shortly.",
    "Good news: this is fixed on our side. Could you check and let me know if it looks right to you?",
    "I've sent the details to your email address. Let me know if anything is missing.",
    "Thanks for your patience. We've scheduled the change for tomorrow morning and will confirm once it's live.",
    "Apologies for the trouble. I've corrected the issue and refunded the difference.",
]
FOLLOW_UPS = [
    "Thanks! One more thing: could you also check the mobile version?",
    "Still not working on my end, I'm afraid. Screenshot attached.",
    "That looks great now, thank you for the quick turnaround.",
]
NOTES = [
    "Checked the hosting logs: nothing unusual. Waiting for the customer to confirm.",
    "Customer is on the premium plan, please prioritise.",
    "Spoke to Jonas about pricing; fine to waive the call-out fee this time.",
]
TAGS = ["billing", "bug", "feature-request", "onboarding", "vip", "refund"]


@dataclass
class SeedSummary:
    workspace_id: uuid.UUID
    users: dict[str, str]
    tickets: int
    customers: int


def _summary(s: Session, ws: uuid.UUID) -> SeedSummary:
    users = {
        r.role: r.email
        for r in s.execute(
            text(
                "select m.role, u.email from memberships m join users u on u.id = m.user_id "
                "where m.workspace_id = :w"
            ),
            {"w": ws},
        )
    }
    tickets = s.execute(
        text("select count(*) from tickets where workspace_id = :w"), {"w": ws}
    ).scalar_one()
    customers = s.execute(
        text("select count(*) from customers where workspace_id = :w"), {"w": ws}
    ).scalar_one()
    return SeedSummary(ws, users, int(tickets), int(customers))


def _audit(
    s: Session,
    ws: uuid.UUID,
    actor_type: str,
    actor: uuid.UUID | None,
    action: str,
    entity: uuid.UUID,
    at: datetime,
    before: Any = None,
    after: Any = None,
) -> None:
    s.execute(
        text(
            "insert into audit_log (workspace_id, actor_type, actor_id, action, entity_type, "
            "entity_id, before, after, created_at) values (:w, :t, :a, :ac, 'ticket', :e, "
            "cast(:b as jsonb), cast(:af as jsonb), :at)"
        ),
        {
            "w": ws,
            "t": actor_type,
            "a": actor,
            "ac": action,
            "e": entity,
            "at": at,
            "b": json.dumps(before) if before is not None else None,
            "af": json.dumps(after) if after is not None else None,
        },
    )


def _seed_rules(s: Session, ws: uuid.UUID, user_ids: dict[str, uuid.UUID]) -> None:
    """A Support team and three tested, live automations that show off the rules engine."""
    team = s.execute(
        text("insert into teams (workspace_id, name) values (:w, 'Support') returning id"),
        {"w": ws},
    ).scalar_one()
    for role in ("agent", "admin"):
        s.execute(
            text("insert into team_members (team_id, workspace_id, user_id) values (:t, :w, :u)"),
            {"t": team, "w": ws, "u": user_ids[role]},
        )
    definitions = [
        (
            "Refund requests",
            {
                "trigger": {"event": "ticket.created"},
                "conditions": {
                    "op": "and",
                    "items": [
                        {
                            "field": "subject",
                            "operator": "contains_any",
                            "value": ["refund", "money back", "chargeback"],
                        }
                    ],
                },
                "actions": [
                    {"type": "set_priority", "value": "high"},
                    {"type": "add_tag", "tag": "refund"},
                    {"type": "assign", "target": "round_robin", "team_id": str(team)},
                ],
            },
        ),
        (
            "Urgent follow-ups",
            {
                "trigger": {"event": "message.received"},
                "conditions": {
                    "op": "and",
                    "items": [
                        {
                            "field": "body",
                            "operator": "contains_any",
                            "value": ["urgent", "asap", "immediately"],
                        }
                    ],
                },
                "actions": [
                    {"type": "set_priority", "value": "urgent"},
                    {
                        "type": "notify",
                        "target": "owners_admins",
                        "message": "A customer marked their ticket as urgent",
                    },
                ],
            },
        ),
        (
            "Escalate missed deadlines",
            {
                "trigger": {"event": "sla.threshold", "level": "breach"},
                "conditions": {
                    "op": "and",
                    "items": [{"field": "priority", "operator": "in", "value": ["high", "urgent"]}],
                },
                "actions": [
                    {
                        "type": "escalate",
                        "assign": {"target": "user", "user_id": str(user_ids["admin"])},
                        "message": "A high-priority ticket missed its deadline",
                    }
                ],
            },
        ),
    ]
    for position, (name, raw) in enumerate(definitions, start=1):
        defn = RuleDefinition.model_validate(raw)
        h = canonical_hash(defn)
        rule_id = s.execute(
            text(
                "insert into rules (workspace_id, name, position, status, active_version, current_version) "
                "values (:w, :n, :p, 'active', 1, 1) returning id"
            ),
            {"w": ws, "n": name, "p": position},
        ).scalar_one()
        s.execute(
            text(
                "insert into rule_versions (workspace_id, rule_id, version, definition, content_hash, created_by) "
                "values (:w, :r, 1, cast(:d as jsonb), :h, :u)"
            ),
            {
                "w": ws,
                "r": rule_id,
                "d": json.dumps(defn.model_dump(mode="json")),
                "h": h,
                "u": user_ids["owner"],
            },
        )
        s.execute(
            text(
                "insert into rule_tests (workspace_id, rule_id, version, content_hash, expectation, matched, "
                "passed, context, result, created_by) values (:w, :r, 1, :h, 'match', true, true, "
                "cast('{}' as jsonb), cast('{}' as jsonb), :u)"
            ),
            {"w": ws, "r": rule_id, "h": h, "u": user_ids["owner"]},
        )


def seed_demo(engine: Engine) -> SeedSummary:
    rng = random.Random(42)  # noqa: S311 - deterministic demo data, not security
    now = datetime.now(UTC)
    with Session(engine) as s, s.begin():
        existing = s.execute(
            text("select id from workspaces where slug = :s"), {"s": SLUG}
        ).scalar()
        if existing:
            return _summary(s, existing)

        pw = hash_password(DEMO_PASSWORD)
        user_ids: dict[str, uuid.UUID] = {}
        for role, (email, name) in USERS.items():
            user_ids[role] = s.execute(
                text(
                    "insert into users (email, name, password_hash) values (:e, :n, :p) returning id"
                ),
                {"e": email, "n": name, "p": pw},
            ).scalar_one()
        ws = s.execute(
            text(
                "insert into workspaces (slug, name, inbound_token) values (:s, 'Brightwork Studio', :t) returning id"
            ),
            {"s": SLUG, "t": secrets.token_hex(8)},
        ).scalar_one()
        create_defaults(s, ws)
        for role, uid in user_ids.items():
            s.execute(
                text("insert into memberships (workspace_id, user_id, role) values (:w, :u, :r)"),
                {"w": ws, "u": uid, "r": role},
            )
        _seed_rules(s, ws, user_ids)
        customer_ids: list[uuid.UUID] = []
        for name, email in CUSTOMERS:
            customer_ids.append(
                s.execute(
                    text(
                        "insert into customers (workspace_id, email, name) values (:w, :e, :n) returning id"
                    ),
                    {"w": ws, "e": email, "n": name},
                ).scalar_one()
            )
        tag_ids = {
            t: s.execute(
                text("insert into tags (workspace_id, name) values (:w, :n) returning id"),
                {"w": ws, "n": t},
            ).scalar_one()
            for t in TAGS
        }

        total = 60
        times = sorted(now - timedelta(minutes=rng.randint(30, 14 * 24 * 60)) for _ in range(total))
        statuses = rng.choices(
            ["new", "open", "pending", "resolved", "closed"], weights=[14, 18, 10, 12, 6], k=total
        )
        # Guarantee every status/priority/channel appears at least once.
        statuses[:5] = ["new", "open", "pending", "resolved", "closed"]
        priorities = rng.choices(
            ["low", "normal", "high", "urgent"], weights=[10, 30, 14, 6], k=total
        )
        priorities[:4] = ["low", "normal", "high", "urgent"]
        channels = rng.choices(["email", "form", "manual"], weights=[38, 14, 8], k=total)
        channels[:3] = ["email", "form", "manual"]
        staff = [user_ids["agent"], user_ids["agent"], user_ids["admin"], user_ids["owner"]]

        ticket_ids: list[uuid.UUID] = []
        subject_by_idx: dict[int, str] = {}
        customer_by_idx: dict[int, uuid.UUID] = {}
        for i in range(total):
            subject, body = SUBJECTS[i % len(SUBJECTS)]
            if i == 40:  # the duplicate pair: same requester, "Re:" subject a few minutes later
                customer_by_idx[i] = customer_by_idx[39]
                subject, body = (
                    "Re: " + subject_by_idx[39],
                    "Following up on my message, any update?",
                )
                statuses[i] = "new"
            customer_id = customer_by_idx.get(i) or customer_ids[i % len(customer_ids)]
            customer_by_idx[i] = customer_id
            subject_by_idx[i] = subject
            created = times[i]
            if i == 40:
                created = times[39] + timedelta(minutes=12)
            status, channel = statuses[i], channels[i]
            assignee = (
                None if status == "new" else (rng.choice(staff) if rng.random() < 0.85 else None)
            )
            tid = s.execute(
                text(
                    "insert into tickets (workspace_id, number, subject, status, priority, channel, "
                    "requester_id, assignee_id, last_activity_at, created_at) "
                    "values (:w, :n, :s, :st, :p, :c, :r, :a, :t, :t) returning id"
                ),
                {
                    "w": ws,
                    "n": i + 1,
                    "s": subject,
                    "st": status,
                    "p": priorities[i],
                    "c": channel,
                    "r": customer_id,
                    "a": assignee,
                    "t": created,
                },
            ).scalar_one()
            ticket_ids.append(tid)
            last = created
            s.execute(
                text(
                    "insert into messages (workspace_id, ticket_id, kind, direction, author_customer_id, "
                    "body, message_id, created_at) values (:w, :t, 'public', 'inbound', :c, :b, :m, :at)"
                ),
                {
                    "w": ws,
                    "t": tid,
                    "c": customer_id,
                    "b": body,
                    "m": f"<seed-{i + 1}-0@customer.test>" if channel == "email" else None,
                    "at": created,
                },
            )
            _audit(
                s,
                ws,
                "system",
                None,
                "ticket.created",
                tid,
                created,
                after={"number": i + 1, "subject": subject, "channel": channel},
            )
            if assignee:
                last = created + timedelta(minutes=rng.randint(5, 90))
                _audit(
                    s,
                    ws,
                    "user",
                    user_ids["owner"],
                    "ticket.updated",
                    tid,
                    last,
                    before={"assignee_id": None},
                    after={"assignee_id": str(assignee)},
                )
            if status in ("open", "pending", "resolved", "closed") and assignee:
                for k in range(rng.randint(1, 2)):
                    last += timedelta(minutes=rng.randint(20, 600))
                    s.execute(
                        text(
                            "insert into messages (workspace_id, ticket_id, kind, direction, author_user_id, "
                            "body, message_id, delivery_status, delivery_attempts, created_at) "
                            "values (:w, :t, 'public', 'outbound', :u, :b, :m, 'sent', 1, :at)"
                        ),
                        {
                            "w": ws,
                            "t": tid,
                            "u": assignee,
                            "b": rng.choice(REPLIES),
                            "m": f"<seed-{i + 1}-out{k}@inbound.resolveflow.local>",
                            "at": last,
                        },
                    )
                    if status in ("open", "pending") and k == 0 and rng.random() < 0.5:
                        last += timedelta(minutes=rng.randint(15, 300))
                        s.execute(
                            text(
                                "insert into messages (workspace_id, ticket_id, kind, direction, "
                                "author_customer_id, body, created_at) values (:w, :t, 'public', "
                                "'inbound', :c, :b, :at)"
                            ),
                            {
                                "w": ws,
                                "t": tid,
                                "c": customer_id,
                                "b": rng.choice(FOLLOW_UPS),
                                "at": last,
                            },
                        )
                if rng.random() < 0.3:
                    last += timedelta(minutes=5)
                    s.execute(
                        text(
                            "insert into messages (workspace_id, ticket_id, kind, direction, author_user_id, "
                            "body, created_at) values (:w, :t, 'note', 'internal', :u, :b, :at)"
                        ),
                        {"w": ws, "t": tid, "u": assignee, "b": rng.choice(NOTES), "at": last},
                    )
            if i == 6:  # guarantee at least one note even with an unlucky draw
                s.execute(
                    text(
                        "insert into messages (workspace_id, ticket_id, kind, direction, author_user_id, "
                        "body, created_at) values (:w, :t, 'note', 'internal', :u, :b, :at)"
                    ),
                    {
                        "w": ws,
                        "t": tid,
                        "u": user_ids["owner"],
                        "b": NOTES[1],
                        "at": last + timedelta(minutes=3),
                    },
                )
            if status in ("resolved", "closed"):
                last += timedelta(minutes=rng.randint(10, 240))
                _audit(
                    s,
                    ws,
                    "user",
                    assignee or user_ids["owner"],
                    "ticket.updated",
                    tid,
                    last,
                    before={"status": "open"},
                    after={"status": status},
                )
            for tag in rng.sample(TAGS, rng.choice([0, 0, 1, 1, 2])):
                s.execute(
                    text(
                        "insert into ticket_tags (workspace_id, ticket_id, tag_id) values (:w, :t, :g)"
                    ),
                    {"w": ws, "t": tid, "g": tag_ids[tag]},
                )
            s.execute(
                text("update tickets set last_activity_at = :l where id = :i"),
                {"l": last, "i": tid},
            )

        s.execute(
            text("update tickets set possible_duplicate_of = :d where id = :i"),
            {"d": ticket_ids[39], "i": ticket_ids[40]},
        )
        # A merged pair: ticket 51 was merged into 50; its message now lives on 50.
        source, target = ticket_ids[50], ticket_ids[49]
        s.execute(
            text("update messages set ticket_id = :t where ticket_id = :s"),
            {"t": target, "s": source},
        )
        s.execute(
            text(
                "insert into messages (workspace_id, ticket_id, kind, direction, author_user_id, body) "
                "values (:w, :t, 'note', 'internal', :u, 'Merged ticket #51 into this one.')"
            ),
            {"w": ws, "t": target, "u": user_ids["agent"]},
        )
        s.execute(
            text("update tickets set status = 'closed', merged_into_id = :t where id = :s"),
            {"t": target, "s": source},
        )
        s.execute(
            text("update workspaces set next_ticket_number = :n where id = :w"),
            {"n": total + 1, "w": ws},
        )
        # Give every seeded ticket its SLA clock, reconstructed from the history just created.
        sctx = SystemContext(s, ws)
        for tid in ticket_ids:
            if tid != source:
                sla_service.backfill_events(sctx, tid)
        sla_service.recompute(sctx, target)
        for n, kind, title in (
            (3, "assigned", "Assigned to you: ticket #4"),
            (5, "customer_reply", "New reply on ticket #6"),
        ):
            notif.notify(
                sctx,
                [user_ids["agent"]],
                kind,
                ticket_ids[n],
                title,
                subject_by_idx[n],
                f"seed:{n}",
            )
        return _summary(s, ws)


def seed_if_empty(engine: Engine) -> bool:
    with Session(engine) as s:
        if s.execute(text("select count(*) from workspaces")).scalar_one() > 0:
            return False
    seed_demo(engine)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the ResolveFlow demo workspace.")
    parser.add_argument(
        "--if-empty", action="store_true", help="only seed when no workspace exists"
    )
    args = parser.parse_args()
    engine = system_engine()
    if args.if_empty:
        if not seed_if_empty(engine):
            print("Database already has data; skipping demo seed.")
            return
    else:
        seed_demo(engine)
    print(f"Demo workspace ready: sign in as owner@brightwork.test / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
