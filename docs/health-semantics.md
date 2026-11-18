# Health and recovery signals

`GET /health` is the unauthenticated liveness endpoint. A successful response
means the HTTP process can answer; `ok: true` is not a data-integrity guarantee.
`memory` is `empty` when no database exists, `ok` when a database exists with no
recorded recovery, or `rebuilt` after corruption was quarantined and a fresh
database created. Database presence is not a full SQLite integrity check.
`memory: rebuilt` makes `status: degraded`, while retaining liveness.

The private `facts.db.recovered.json` marker survives restarts. It records the
quarantine location for the operator; the public endpoint returns only the
status, never that path. Inspect the preserved database and restore/export any
recoverable facts before explicitly acknowledging recovery by removing the
marker. Restarting alone does not acknowledge data loss.

`GET /v2/health` is operational readiness. Bridge and watchdog are required;
TLS is required when enabled. Missing watchdog activity or enabled-but-unready
TLS returns `ok: false`, `status: unhealthy`. CDP and cluster are optional:
unconfigured/disconnected optional integrations are shown in `checks` but do
not make an otherwise healthy bridge unhealthy. `required_checks` and
`optional_checks` identify that policy in the response.

`GET /v1/doctor` reports individual diagnostics. `passed` counts only successful
checks. Failed optional checks count as `degraded`; failed critical checks count
as `failed`. The three counts sum to `total`. Any critical failure makes `ok`
false and the status unhealthy; otherwise optional failures produce degraded
status. An empty facts collection is not an error; a facts-query exception is
a critical error, not zero facts. Recorded memory recovery is degraded pending
operator acknowledgement. The doctor CLI prints all three counts and status.
