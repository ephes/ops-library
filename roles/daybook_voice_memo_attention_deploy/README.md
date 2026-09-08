# daybook_voice_memo_attention_deploy

Installs the Daybook voice-memo attention pilot on macOS **disabled and unloaded**.
Both native provider paths and phone round trips remain activation prerequisites;
this role rejects `enabled: true` rather than implying those checks passed.
It does not run discovery, initialize/baseline tracking, launch a conversation,
send a notification, or touch the independent voice-memo importer.

## Requirements

- macOS with the selected non-root owner logged into an Aqua GUI session.
- Root/become deployment privileges, `/opt/homebrew/bin/uv`, and
  `/opt/homebrew/bin/python3.14` already installed.
- A controller-local `daybook-*.whl` wheel containing `daybook.attention`. Build and
  validate it in the application repo before deploying. The role installs the
  supplied wheel with its declared dependencies into a separate virtual
  environment and verifies `import daybook.attention` as the service owner with
  isolated Python before
  recording installation success. This import runs no discovery or pilot command;
  the role does not claim a pinned source commit or locked dependencies. The
  installation receipt compares a separately read destination SHA1 on every
  converge, so it does not depend on copy-action return fields.
- The import check keeps Ansible's module running as root, changes to the
  validated service home, then runs only the isolated Python subprocess as the
  service owner using noninteractive `sudo -H -u`. This avoids inheriting an
  inaccessible root SSH working directory during unprivileged module startup.
  No shell command or world-readable temporary module is used.
- Private configuration supplied by the control repository. Production discovery
  additionally needs a separately provisioned prefix-limited S3 reader; the
  importer writer credential must never be reused. This role provisions no
  credentials, notifier, native runtime, or activation approval.

## Variables

All defaults are in `defaults/main.yml`; paths are validated to keep this pilot
separate from Git checkouts, the synced vault, and importer state.

| Variable prefix `daybook_voice_memo_attention_` | Default / purpose |
| --- | --- |
| `enabled` | `false`; `true` is unsupported and rejected |
| `service_user` | `CHANGEME`; required non-root macOS owner |
| `service_home` | `/Users/<service_user>`; fixed owner home |
| `wheel_src` | `CHANGEME`; absolute controller-local `daybook-*.whl` path |
| `install_root` | `/Library/Application Support/Daybook/voice-memo-attention` |
| `venv` | `<install_root>/venv` |
| `uv_bin` | `/opt/homebrew/bin/uv` |
| `python_source` | `/opt/homebrew/bin/python3.14` |
| `runtime_dir` | `<service_home>/.local/state/daybook/voice-memo-attention` (0700) |
| `config_path` | `<runtime_dir>/config.json` (0600) |
| `config` | `{}`; required mapping described below |
| `launchd_label` | `de.wersdoerfer.daybook.voice-memo-attention` |
| `plist_path` | `<service_home>/Library/LaunchAgents/<launchd_label>.plist` |

The config requires `version: 1`, `enabled: false`, `profile: synthetic` or
`production`, `state_path: <runtime_dir>/state.sqlite3`, and a `source` mapping
with `kind: synthetic` or `s3`. The application owns full schema validation.
Private values are copied with `no_log: true`; the plist contains no credentials
or memo bodies.

## Example

```yaml
- hosts: macos_owner_host
  become: true
  roles:
    - role: local.ops_library.daybook_voice_memo_attention_deploy
      vars:
        daybook_voice_memo_attention_service_user: example
        daybook_voice_memo_attention_wheel_src: /private/build/daybook-0.0.0-py3-none-any.whl
        daybook_voice_memo_attention_config:
          version: 1
          enabled: false
          profile: synthetic
          state_path: /Users/example/.local/state/daybook/voice-memo-attention/state.sqlite3
          source:
            kind: synthetic
```

## Installation and lifecycle

The role disables and unloads only its own launchd label before changing files,
verifies the label is unloaded, installs the wheel/configuration, and writes a
plist with `Disabled: true`, `RunAtLoad: true`, and failed-exit restart throttled
to 900 seconds. It remains unloaded. Once explicitly activated later, a single
persistent supervisor owns the native sessions and runs a 900-second discovery
loop; launching a new supervisor per tick would lose in-memory runtime ownership.
The dormant command is:

```text
<venv>/bin/python -I -m daybook.attention --config <config_path> serve
```

The role's `launchctl disable gui/<uid>/<label>` also writes a persistent
per-user disabled override. It survives plist removal and is re-applied on every
converge. After readiness and owner approval, later activation must explicitly
run both steps below in the owner's GUI domain (with its real UID and paths):

```text
launchctl enable gui/<uid>/de.wersdoerfer.daybook.voice-memo-attention
launchctl bootstrap gui/<uid> <plist_path>
```

The explicit enable override takes precedence over the installed plist's
`Disabled: true`; editing that plist alone does not clear a disabled override.
The application configuration and bound activation record must also authorize
`serve`. These are separate operator steps in the private runbook, not role
side effects. The role reports the repeated disable guard as unchanged because
it does not diff launchd's private override database.

There is no bootstrap, enable, kickstart, tick, or baseline task. Existing tracking
state and activation markers are never removed. Removal uses
`daybook_voice_memo_attention_remove`, which also preserves the installation and
all runtime data. Backup/restore roles are intentionally absent for this disabled
pilot: retain the private runtime directory for explicit operator recovery;
missing prior state must not become a new automatic baseline. A tested recovery
and backup procedure remains necessary before activating real memos.

Use application status and production read-only discovery dry-run commands from
the private runbook when their prerequisites are configured. Installing a plist
or passing role tests is not proof of native phone answering or live readiness.

## Validation

`uv run python -m unittest tests.test_daybook_voice_memo_attention_deploy` tests
real Ansible input rejection plus rendered plist and lifecycle invariants.
Run `just test`, `just lint-strict`, and `just docs-build` in the collection.
Live deployment and both phone round trips must be recorded separately.
