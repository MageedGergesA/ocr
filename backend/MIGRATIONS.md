# Database migrations (production)

Alembic owns the production schema. The app **never** migrates automatically and
never runs destructive DDL at startup.

## Deploy order (must be followed)

1. Deploy the new code to the server (do not start/restart the app yet).
2. Apply migrations **before** starting the new app:

   ```bash
   cd backend
   ENV=prod /etc/mostakhles.env  # or however you load secrets
   alembic upgrade head
   ```

3. Start/restart the app.

On startup with `ENV=prod`, the app runs two fail-fast checks and refuses to boot
if either fails (it does not attempt to fix them):

- `settings.assert_production_ready()` — required env vars are present.
- `db.assert_schema_current()` — the database's Alembic revision equals the code
  head. If the DB is behind (you skipped step 2) it raises:

  > Database schema revision '…' is not the code head […]. Run `alembic upgrade head` …

This is the guard against the old failure mode: booting cleanly against a stale
schema and then erroring at query time.

## Rollback

```bash
alembic downgrade -1   # one step back
```

Read the target migration's docstring first — some downgrades are **not**
reversible for data:

- `e1a2b3c4d5f6` (api-key hashing) — hashing is one-way; downgrade restores the
  column shape but not usable plaintext keys. Do not downgrade after real keys
  were migrated; re-issue keys instead.
- `f2b3c4d5e6a7` (idempotency uniqueness) — upgrade deletes duplicate cache rows;
  downgrade only drops the constraint.
- `a3c4d5e6f7b8` (subscriptions.user_id nullable) — downgrade re-imposes NOT NULL
  and fails if any detached (anonymized) subscriptions exist.

## Migration chain (linear, single head)

```
c1e4613a6e6e  baseline
… (existing)
c3f1a7e9d2b4  correction scope_key            (previous head)
e1a2b3c4d5f6  api key hashing                 (P0.2)
f2b3c4d5e6a7  idempotency UNIQUE(user_id,key) (P0.4)
a3c4d5e6f7b8  subscriptions.user_id nullable  (P0.5)   <-- head
```

## Note on SQLite

Some existing migrations use PostgreSQL-only DDL (e.g. `drop_constraint` on a FK),
so `alembic upgrade head` cannot run end-to-end on SQLite. Dev/test databases are
built by `create_all()` from the models, not by the migration chain. New
migrations use `batch_alter_table` so they are individually SQLite-compatible.
```
