# daybook_operations_runtime_deploy

Stage one API-backed scheduler in an existing protected macOS importer profile.

This role preserves the existing Full Disk Access interpreter path. It does not
install/update the importer checkout, initialize a ledger, change an activation
marker, or manage the long/native-work labels. Install the exact reviewed Daybook
revision using the existing importer maintenance procedure first; the role
verifies that revision and imports the new runtime with the protected interpreter.
Any source upgrade and its long-lane maintenance window must be reviewed separately.

`action: install` creates root-owned disabled policy, owner-private credential and
journal, and a candidate plist **outside** LaunchAgents. It never changes the
existing scheduler. A root-owned local policy only selects the fixed importer
adapter, binding and API origin. No server-supplied executable or path is accepted.

`action: cutover`, with `confirmed: true`, disables only the regular label,
waits for its current job to finish, unloads it, proves both importer/runtime locks
idle, saves the old plist once, and installs the new command. The journal/ledger
remain intact. Default `start: false` leaves it disabled. `start: true` additionally
requires reconciled journal/API state and an enabled server binding before loading.

`action: rollback` requires the server binding already disabled and no unresolved
assigned/awaiting-application work. It quiesces the same regular label, restores
the saved plist and disables the local policy. Optional `start: true` loads the
legacy command only after the remote active slot has been reconciled. This does
not restore an old ledger or delete API evidence. Failures leave the label disabled.

Example, installation only:

```yaml
- role: local.ops_library.daybook_operations_runtime_deploy
  vars:
    daybook_operations_runtime_user: example
    daybook_operations_runtime_revision: "{{ reviewed_daybook_commit }}"
    daybook_operations_runtime_token: "{{ private_profile_token }}"
    daybook_operations_runtime_api_url: https://operations.example.com
```

The user must have a GUI login for attended label changes. The role uses a
noninteractive login-style sudo user switch (`-H -S -n -i`), which enters the user's
home before Ansible starts its Python module. A root SSH session's working
directory may be inaccessible to that user on macOS. The login shell also loads
the user's shell configuration; recheck deployment after changing it. Commands
still use the absolute protected Python path with isolated mode. Configure credentials
with mode 0600 and the delivery directory with mode 0700. `operations status`
uses the same policy and exposes aggregate state only. After a crash, never clear
the journal: drain its receipt or authorize a linked recovery on the server,
then use `operations recover` locally. Runtime lock inheritance protects orphaned
children. No PID read from disk is killed by recovery.

## Defaults and variables

```yaml
---
ops_library_documentation_category: deployment
daybook_operations_runtime_action: install
daybook_operations_runtime_confirmed: false
daybook_operations_runtime_start: false
daybook_operations_runtime_user: CHANGEME
daybook_operations_runtime_home: "/Users/{{ daybook_operations_runtime_user }}"
daybook_operations_runtime_install_root: /Library/Application Support/Daybook/voice-memo-inbox
daybook_operations_runtime_python: "{{ daybook_operations_runtime_install_root }}/daybook/.venv/bin/python"
daybook_operations_runtime_revision: CHANGEME
daybook_operations_runtime_policy: "{{ daybook_operations_runtime_install_root }}/operations.json"
daybook_operations_runtime_importer_policy: "{{ daybook_operations_runtime_install_root }}/policy.json"
daybook_operations_runtime_credential: "{{ daybook_operations_runtime_home }}/.config/daybook-voice-memo-inbox/operations.json"
daybook_operations_runtime_token: CHANGEME
daybook_operations_runtime_api_url: https://operations.home.example.com
daybook_operations_runtime_binding: regular
daybook_operations_runtime_journal: "{{ daybook_operations_runtime_home }}/.local/state/daybook/operations-importer"
daybook_operations_runtime_label: de.wersdoerfer.daybook.voice-memo-inbox
daybook_operations_runtime_plist: "{{ daybook_operations_runtime_home }}/Library/LaunchAgents/{{ daybook_operations_runtime_label }}.plist"
daybook_operations_runtime_staged_plist: "{{ daybook_operations_runtime_install_root }}/operations.launchd.plist"
daybook_operations_runtime_legacy_plist: "{{ daybook_operations_runtime_install_root }}/regular-importer.before-operations.plist"
```

## Validation

Local contract tests exercise disabled defaults, rendered units/plists and lifecycle
safety. The Daybook suite exercises real PostgreSQL concurrency and dump/restore,
HTTP delivery recovery and importer regression fixtures. Live deployment and
attended import/rollback validation remain required before production acceptance.

## Offline incident rollback

Automated rollback requires central status. If the API is unavailable, fence both
central units independently (stopped and disabled, or server held offline), disable
and drain the regular local label, and use the supported `operations idle` CLI to
prove both local locks free without HTTP. Preserve/inspect journal and source
evidence before manually restoring the saved legacy plist and disabled policy.
Reconcile and disable the central binding before unfencing the server. The private
control runbook contains the attended steps; this is never an automatic bypass.
