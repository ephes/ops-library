# daybook_voice_memo_work_deploy

Installs a separate five-minute macOS LaunchAgent that asks Daybook to start
capable work for newly imported voice memos. It reuses the owner's installed
work runtime, native provider registration and pinned notification transport.
It does not install Daybook, transcribe memos, or alter the
voice-memo importer, retired attention reviewer, notifier, sessions, or
weeknotes jobs.

The first enabled deployment persists `daybook_voice_memo_work_imported_since`
in the private runtime directory. Later deployments keep that value, so changing
inventory cannot silently move the historical boundary. The CLI's durable source
identity prevents a successfully submitted memo from being started again.

AWS access uses an owner-private shared credentials file rendered from private
control-repository variables at `memos/aws-credentials`, with profile
`daybook-work`. Credentials are never rendered into the plist, but the
same-owner capable session can read this file and receives its path. The plist
clears ambient AWS identity variables and ignores the owner's AWS config so the
memo lookup uses this designated profile. Codex deployments pass the existing socket and capable Codex home explicitly. The default working
directory is the owner's home so the session can discover the owner's projects.

Set `daybook_voice_memo_work_enabled: true` to enable and bootstrap the agent.
Changing the plist reloads only this label. Setting it to `false` disables and
boots out only this label while preserving the work database, cutoff and logs.

The dedicated production database is
`~/.local/share/daybook/work-runtime/memos/work.sqlite3`; acceptance data is not
used. Before enabling, verify that the configured credential can list/read the
exact imported memo prefix and that the installed CLI exposes
`work memos --imported-since`.

Validate with:

```sh
uv run python -m unittest tests.test_daybook_voice_memo_work_deploy
just test
just lint-strict
just docs-build
```
