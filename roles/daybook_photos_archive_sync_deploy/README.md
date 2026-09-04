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
- Daybook's owner-only nonblocking state lock suppresses simultaneous manual
  and scheduled invocations. Deployment quiesces launchd before replacing
  files, while the operation journal recovers an interrupted copy.
- State, configuration, and logs are owner-only. No credentials are variables.

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
Before activation, run the installed launcher once in that Aqua session and
grant macOS Photos/Full Disk Access if prompted; otherwise TCC may prevent the
background process from reading the Photos library.
