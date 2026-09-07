# daybook_photos_archive_sync_deploy

Deploy Daybook's one-way Nikon NX Studio working-folder archive reconciler as a
macOS Aqua user LaunchAgent. The role is disabled by default and intended for a
single explicitly named writer host.

The installed job runs every two hours, requires the configured Fractal SMB
share to be mounted already, and calls `daybook photos archive-sync --execute
--summary-only`. It never mounts or authenticates. Daybook verifies the exact
SMB server/share, uses Apple Photos only as the folder-completion signal, never
deletes remote-only folders, and keeps verified camera originals immutable.

## Safety model

- `daybook_photos_archive_sync_enabled` defaults to `false`.
- `enabled: false` is an inert no-op, not an uninstall switch. Use the private
  control repository's emergency-disable playbook, or run this role with
  `enabled: true` and `launchd_enabled: false`, to stop a deployed agent.
- General deployment must pass
  `daybook_photos_archive_sync_launchd_enabled: false`; use a separate guarded
  control-repository playbook for activation.
- The expected writer must equal `inventory_hostname`, preventing accidental
  installation on a second Mac.
- The role requires the Ansible connection user to equal the service user; it
  never creates a root-owned checkout or virtual environment under that user's
  home.
- Deployment disables and boots out the exact LaunchAgent before changing its
  pinned checkout or configuration.
- The Daybook source arrives as a controller-verified bundle and is checked out
at one exact 40-character commit. A dirty managed checkout is rejected.
An interrupted first `--no-checkout` clone has no Git index; the next deploy
recognizes that role-created state, resumes the exact fetch/checkout, and then
applies the normal clean-tree assertion.
- A GNU `timeout` watchdog terminates runs before the next two-hour interval.
- A short same-runtime preflight opens one byte of `Photos.sqlite` before the
  full run. `daybook_photos_archive_sync_photos_access_timeout_seconds`
  defaults to 15 seconds. Missing launchd Full Disk Access therefore exits 77
  with a clear error instead of occupying the main job's watchdog window.
- Daybook's owner-only nonblocking state lock suppresses simultaneous manual
  and scheduled invocations. With the remediated Daybook revision, the first
  overlap exits 0; repeated overlap with the same holder or a holder older than
  90 minutes exits 75 (`lock_contention`). Attended reports include PID/start
  evidence; the scheduler emits only the outcome. Deployment quiesces launchd before replacing
  files, while the operation journal recovers an interrupted copy.
- State, configuration, and logs are owner-only. Log-file overrides must stay
  under the private log directory, and the virtualenv must stay under the
  verified checkout. All managed paths reject relative paths and dot traversal.
  No credentials are variables.

## Required variables

```yaml
daybook_photos_archive_sync_enabled: true
daybook_photos_archive_sync_service_user: jochen
daybook_photos_archive_sync_repo_ref: 0123456789abcdef0123456789abcdef01234567
daybook_photos_archive_sync_repo_bundle_src: /absolute/controller/source.bundle
daybook_photos_archive_sync_expected_smb_server: fractal.example.invalid
daybook_photos_archive_sync_expected_smb_share: photos
daybook_photos_archive_sync_expected_writer_host: atlas
```

The source bundle must advertise exactly one `refs/heads/main` ref at the
requested commit; the private controller playbook creates and verifies that
shape.

Set `daybook_photos_archive_sync_use_folder_map: true` only after placing the
reviewed owner-mode-0600 closed map at
`daybook_photos_archive_sync_folder_map_path`.

## Activation

An activation play may call this same role with
`daybook_photos_archive_sync_launchd_enabled: true`. The role then enables and
bootstraps the user LaunchAgent; `RunAtLoad=true` performs the first scheduled
context run immediately. The user must have an active Aqua login session and
the Fractal share must already be mounted at the configured exact mount point.
Before activation, grant Full Disk Access to `/bin/bash`, the interpreter of
the script launchd starts. This is a broad macOS permission, so keep the agent
disabled if that tradeoff is not acceptable and run the managed checkout's
`daybook photos archive-sync` command directly from Terminal instead. Do not
use the launchd-only wrapper for that attended fallback: its privacy preflight
is intentionally bounded and cannot wait for an interactive macOS consent
dialog. Terminal access is not proof that launchd has access because macOS
attributes the background process separately. Without the permission the
launcher's bounded preflight exits 77 before Daybook starts; verify the grant
by activating once and checking that launchctl records exit 0.


## Source-root migration and recovery

Source-root migration requires the already-mounted Fractal share and validates
its configured SMB identity before binding. Only the local ledger is written;
the mount requirement also applies to this migration-only command.

The remediated Daybook command binds the local source root's device, inode, and
filesystem birthtime. An existing legacy ledger requires attended inspection,
then the usual CLI arguments plus `--execute --bind-source-root` once. This
operation requires an empty journal and writes only the local identity binding;
it cannot rebind a different already-bound root. Follow with a fresh plan.
The launcher never carries this flag. A restore or remount can change filesystem
identity and requires investigation, not automatic rebinding.

Verified camera hashes remain authoritative during missing-target recovery.
Only durable evidence from successful exclusive creation permits quarantine of
an owned partial; legacy `writing` or `create_intent` records require attended
repair if the target differs. Preserve ambiguous files and journal evidence.
Keep the job disabled until the safety fixes and integrated result are reviewed
and an exact repaired revision is separately deployed and verified.

The copied source bundle must remain beneath `install_root`; the controller-side
`repo_bundle_src` is a separate read-only input and may live elsewhere.
