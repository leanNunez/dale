# 0012. Hosting, packaging, release and deploy

Date: 2026-11-26
Status: accepted (decided before the code: it lands in slices 14 to 16; the domain is open, log D14)

## Context

v0.3 puts the host on a public address. Four rules already hold and shape every choice below.
The host binds `127.0.0.1` only, with one worker and no option to change it
([decision 0005](0005-web-confirmation-safety.md), `src/dale/apps/web.py:54,219`). Conversation
state is in memory, so there is one instance. `scripts/check_no_api_key.sh` fails CI when a tracked
file of a scanned kind names an Anthropic key in an assignment-shaped pattern, `secrets.anthropic`
in a workflow included (`scripts/check_no_api_key.sh:15-17`), and live runs use the owner's own
`ant auth login` profile. The scan is narrower than that sounds: it reads only `*.py *.sh *.toml
*.yml *.yaml *.cfg *.ini *.json *.jsonl` outside `openspec`, so it does not read a `Dockerfile`,
`deploy/Caddyfile`, `.env*`, `.dockerignore`, an extensionless script or Markdown. Slice 14 extends
it to `Dockerfile`, `deploy/Caddyfile`, `.env*`, `.dockerignore` and the extensionless scripts under
`deploy/`.
And the goal of v0.3 is a demo with no risk to the owner's account. This record states DD44 to
DD46 of the `v03-demo` design and log D1, D2, D3, D5 and D7. The release criterion is
[decision 0013](0013-release-eval-criterion.md).

## Decision

| Topic | Decision |
|---|---|
| Hosting (log D5) | One 2 GB VPS running Docker Compose, with Caddy on the host for TLS and HSTS (DigitalOcean Basic at USD 12 per month, price verified 2026-11-26; Hetzner CX23 at EUR 5.99 if a plan can be ordered). The app keeps the `127.0.0.1` bind and Caddy proxies to `127.0.0.1:8000`. Buying the server is a user gate. The domain is open (log D14); until it is chosen, the Caddyfile value, the host allow-list, the HSTS scope and the smoke targets stay placeholders |
| Compose (DD44) | `app` runs on `network_mode: host`, so its loopback bind is the server's loopback; `read_only`, `cap_drop: [ALL]`, `no-new-privileges`, a 150 s stop grace and bounded logs. `db` is Postgres 17 on a bridge, published only on `127.0.0.1:5432`, so it never listens on a public interface. A `migrate` service in profile `ops` runs `alembic upgrade head` as the owner role. Every image is pinned by digest (planned) |
| Image (DD44) | A multi-stage build, all stages pinned by digest: the page build on Node 24.22.2 with `npm ci --ignore-scripts` ([decision 0006](0006-frontend-contract-node.md)), the Python environment from `uv sync --locked --no-dev`, and a slim Python 3.13 runtime running as a non-root user. It holds the host, the built page, `migrations/` and `db/roles.sql`, and serves the page with no source checkout. `.dockerignore` is an allow-list, so no `.env`, transcript or export enters |
| Secrets (log D3) | The demo workspace key, the session secret and the database passwords live only in root-only files under `/etc/dale` on the server, outside the repository. Only Markdown may name the variable, and the scan does not read Markdown; every other tracked file stays inside the scan's extended scope (slice 14). The demo workspace carries its own USD 15 per month limit (log D7), a backstop for the code cap of [decision 0009](0009-public-demo.md); creating it is a user gate |
| Release trigger (DD45, log D1) | `release.yml` runs only on a pushed tag `v*`, and continues only when the tagged commit is reachable from `main`. Jobs in order: `on-main`, `ci` (the full CI, eval replay included, called through `workflow_call`), `report`, `image` and `release`. A job that fails stops the chain and nothing is published |
| Release report check | `scripts/check_release.py` (planned) checks the committed live report of the default model against decision 0013, and that no guarded path changed between the report commit and the tag. Guarded paths: the `dale` package, the eval cases and harness, `evals/pricing.toml`, `migrations`, `db/roles.sql`, `uv.lock`, `pyproject.toml`, decision 0013 and the script itself. Docs and the report may change. Unexpected writes are two counters and both must be 0 (`gates.disallowed_writes` and `metrics.unexpected_writes`, log D22). The newest committed report counts, every run is committed, and a measurement path that changed after decision 0013's commit needs a decision record added in between (log D21). It also fails on a changed price table, a case set other than 40, or a criterion commit that does not precede the report commit. The workflow makes no model call |
| Credentials in CI (log D1, D2) | The only credential the release workflow uses is `GITHUB_TOKEN`, with `packages: write` on the image job and `contents: write` on the release job. No Anthropic key, no SSH key and no connection to the server. The owner runs the paid live eval locally and commits the report; CI only checks it |
| Image publication | The `image` job builds, scans and pushes `ghcr.io/<repo>:<tag>`, and the release body records the digest. `scripts/scan_image.sh` (planned) exports the image filesystem and fails on the key value pattern `sk-ant-` followed by 20 or more key characters, on any `.env*` file and on any `dale-export-*` file. It matches key values, not names, because the SDK's own source names `api_key` |
| Deploy (DD45, log D2) | The owner deploys from their own machine with `deploy/deploy.sh <version>`. It validates the version, reads the one digest from the GitHub release with `gh`, and runs one fixed command over the owner's own SSH, `dale-deploy <version> <digest>`, then a public smoke check. On the server `dale-deploy` validates its arguments again, pauses the demo with reason `deploy` (skipped on a first deploy, when no app exists), pulls by digest and checks that the tag resolves to the same digest, runs the migration, starts the app and checks the local `/health`. A failed migration resumes only its own pause and leaves the old version serving. A failed smoke check rolls back to the previous digest, smokes it again and resumes only if that passes; with no previous version the app is stopped. The first deploy stays `paused, initial` until the owner resumes it by hand |
| Smoke check | Over the public URL, with no model call: `/health` over HTTPS, HTTP redirecting to HTTPS (301 or 308), HSTS present, the CSP on `/`, and a create request with `{}` answering `notice_not_accepted` (so the host is in demo mode and found a client IP). From the owner's machine, ports 8000 and 5432 must not be connectable |
| Migrations (DD46) | Revisions from 0006 on may only add. A unit test rejects `DROP`, `RENAME`, `ALTER ... TYPE` and `SET NOT NULL` in their DDL. The previous image therefore keeps working against the new schema, and a rollback never needs a downgrade |

## Alternatives rejected

- A key in a GitHub Environment so CI runs the live eval. `check_no_api_key.sh` would fail on it,
  and a key in CI is the exposure the demo must avoid (log D1).
- CI deploying over SSH with a key stored in GitHub. That gives CI root on the server (log D2).
- Fly.io, Render, Railway or Vercel with a hosted database. A stateful single-worker host that
  spawns the verifier subprocess fits a plain VPS, and a platform proxy would change the
  loopback bind (log D5).
- A published port 8000 or a public Postgres. The app and the database are reachable only from
  the server itself, and the smoke check tests that from outside.
- Deploying by tag name alone. A tag can move; pulling by digest makes the image immutable.

## Consequences

- One server, one instance, no high availability. Patching and backups are the owner's, covered
  by a runbook (slice 17).
- A deploy or restart ends live conversations, and the nightly reset does the same on purpose.
- The release is blocked until the owner has run the live eval after decision 0013's commit,
  bought the server, set the domain and the key, merged `dev` to `main` and pushed the tag. Each
  step is a user gate and none is automated.
- Rolling back is a redeploy of the previous digest. It works because migrations only add.
- The release workflow, the deploy scripts and the smoke check are tested with stubs for `docker`,
  `ssh`, `gh`, `curl` and `nc`; the real run happens only on the gated tag and deploy.
