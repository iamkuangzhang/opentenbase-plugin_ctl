# Security Policy

## Supported Versions

The current public candidate is `v0.1.0`. It is intended for source release testing and local OpenTenBase plugin governance validation, not production use.

## Reporting A Vulnerability

Please report security issues through GitHub issues unless the report includes private credentials or exploit details. Do not include passwords, tokens, private keys, or live database credentials in public reports.

## Execution Safety

OpenTenBase PluginCtl separates read-only governance commands from lifecycle commands that may modify the database.

Role hooks are currently planned, linted, archived, and checked for consistency, but they are not executed automatically. A future hook execution feature must require an explicit flag such as `--execute-hooks`.

`rollback` is best-effort and should be reviewed before execution. It only executes when `--execute` is passed.
