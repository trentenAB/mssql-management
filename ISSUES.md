# Issues and validation status

## Functional limitations

1. **Audit history is not a schema snapshot.** Table alterations and DML cannot safely recreate past table state. They are shown as activity; table/index/type/trigger/drop replay and table-data rollback are not implemented. Complete view, procedure, and function definitions are the supported deployment targets. A schema migration planner and baseline snapshots would be needed for safe table restoration.
2. **Audit success is not transaction success.** SQL Server's `succeeded` indicates permission-check success. A recorded change may have rolled back later. Read-only users see a clearly labeled latest-recorded assumption, not verified live state.
3. **Live SQL Server integration remains unverified.** No real SQL Server, credentials, or `.sqlaudit` fixtures were provided. Audit reading, actual role behavior, fragment semantics, definition matching, and live deployment must be checked against the target server before operational use. Unit tests simulate driver responses and transaction outcomes.
4. **Incomplete audit text is review-only.** Missing leading/intermediate fragments and a final 4,000-character fragment are blocked. The audit format provides no explicit final-fragment flag; short truncated tails can remain undetectable. Review source SQL before applying. The app requires SQL Server 2016 SP1+ and uses `sequence_group_id`.
5. **Conservative T-SQL support.** Single-batch module definitions and balanced BEGIN/END bodies are supported. GO batches, explicit transaction blocks detected by the fallback parser, and statements outside a module body are blocked. Complex valid syntax can be classified review-only. This is not a complete T-SQL parser or a sandbox; deploy only trusted, reviewed audit SQL using a least-privilege login. Module creation can change future application behavior.
6. **Session options are not reconstructed.** Audit text does not reliably preserve original ANSI_NULLS/QUOTED_IDENTIFIER settings. Deployment uses both ON. Dependencies, encrypted definitions, schema-bound objects, signatures, or unsupported features can cause rejection or behavior differences. Test on staging first. Normalization changes only CREATE/ALTER prefixes, line endings, and comments; semantically equivalent formatting may not match.
7. **Concurrent external DDL.** A fingerprint rejects a stale page, and an application lock serializes this app's deployments. External tools do not necessarily acquire that lock; a small check/execute race remains. Coordinate deployments or add a server-side governance mechanism.
8. **Two separate persistence systems.** SQL Server commit and SQLite deployment-log persistence cannot be atomically committed together. A committed SQL deployment followed by a local logging failure is reported explicitly; reloading checks live state. A connection loss during commit can make its outcome ambiguous; inspect the database before retrying.
9. **Shared history visibility.** Any SQL-authenticated user admitted to this app can browse the configured database's cached audit text, regardless of individual SQL object visibility. Use only within an authorized team and separate deployments per security boundary. Audit SQL may include sensitive literals.
10. **Local/small-team scale.** History is loaded into memory for each page/import; there is no pagination, streaming import, background polling, or retention policy yet. Use bounded audit-file patterns. SQL credentials and the login rate limiter live in one process; keep the supplied one-worker Gunicorn configuration. Restarts require new logins. Horizontal scaling, SSO, Windows integrated authentication, and distributed rate limits are not implemented.
11. **Object identity is name-based.** Rename, drop/recreate, and reused schema/name combinations can split or merge history. Audit event deduplication is scoped to this database and audit sequence identity; changing the target server requires a separate history file.
12. **Registry CI needs infrastructure.** GitLab Docker-in-Docker requires a privileged TLS-enabled runner. ECR/GitLab pushes have not been performed; no credentials or destinations were supplied. Jobs are manual and scripts only publish when run explicitly.

## Problems encountered and corrected

- Object versions previously displayed global history record IDs (for example a procedure starting at #4). Display numbering now starts at #1 for each object across history, comparison, current status, deployment confirmation, and deployment logs. Internal record IDs are retained for correct targeting.
- Copy feedback previously remained indefinitely. Success and failure messages now return to Copy SQL after three seconds, and a repeated click restarts that interval.

- Bare `pytest` did not initially find the `app` package. Added `pytest.ini` with an explicit project-root Python path.
- sqlparse's generic statement splitter incorrectly separated one valid procedure containing `COUNT(*) AS …`. Added a conservative token-based balanced-block fallback and tests for valid bodies and rejected trailing statements.
- Cloud Docker's default config path was read-only. Build validation uses a task-owned Docker config under `/tmp`.
- Cloud Docker could not resolve the approved proxy inside its build network. Validation uses an explicit proxy-host mapping and existing proxy build arguments.
- Build-container trust was initially unavailable. Added an optional BuildKit CA secret, HTTPS apt sources, strict apt update failures, and CA configuration for dependency installation. TLS and repository signatures remain verified; no verification bypass was used.
- A browser check initially expected the wrong diff count: CREATE → ALTER changes the header as well as the query. Corrected the expectation to include that visible change.

## Validation evidence

- **40 automated tests passed**, covering Flask workflows, session handling, audit parsing, and deployment commit/rollback with simulated SQL Server responses.
- Chromium browser workflow: history, per-object version numbering, combined column filters, inclusive/open-ended/invalid date ranges, filter reset, clipboard feedback/reset (including repeated clicks and clipboard denial), arbitrary version selection, swapped comparison, and mobile layout checked; no JavaScript errors.
- Desktop and mobile screenshots saved in the project root.
- **Docker image built and ran successfully** as UID 10001 with Microsoft ODBC Driver 18. The functional HTTP check passed; the named-volume history retained exactly nine demo events through container recreation and restart. Compose configuration and shell syntax checks passed.
- Live SQL Server audit/deployment: **not run** (no server supplied).
- ECR/GitLab push and CI runner execution: **not run** (no credentials or runner supplied).
