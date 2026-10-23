# echoport_backup

Registers an Echoport backup service with FastDeploy.

This role sets up a backup runner that can be triggered by Echoport (or directly via FastDeploy) to:

1. Safely backup SQLite databases using `sqlite3 .backup` (every runner that
   copies a live SQLite database shares `templates/_sqlite_backup.py.j2`: it
   waits up to 30 s for a writer's lock with `.timeout`, retries a failed
   backup up to 3 times 5 s apart, removes a partial copy, requires the
   integrity check to print exactly `ok`, and the failure step names the
   sqlite3 error)
2. Archive additional files/directories
3. Create a compressed tarball with manifest
4. Upload to MinIO object storage
5. Output `ECHOPORT_RESULT:{...}` for Echoport to parse

The runners include `_sqlite_backup.py.j2` with a Jinja `{% include %}`, so
render them from their file in this role's `templates/` directory (as
`fastdeploy_runner_template` does: Ansible resolves the include next to the
template). The GoToSocial runner takes its snapshot on the host through the
`echoport_remote_command_guard` and sends `sqlite3 <db> ".timeout 30000"
".backup '<tmpdir>/<name>'"`; deploy the guard (2.53.0 or later) on the
GoToSocial host before the runner. A retry writes a new file
(`retry<N>-sqlite.db`) in the same private temp dir. The heis and
villakunterbunt runners keep their own snapshot code.

For media backup services (for example homepage/python-podcast templates in this role), object data is
stored in a rolling prefix (`<service>/current/objects`) while each run still writes a per-run manifest
under `ECHOPORT_KEY_PREFIX`.

## Requirements

- FastDeploy must be installed and running
- MinIO server must be accessible
- `sqlite3` package (installed by this role)
- `mc` MinIO client (installed by this role)

## Role Variables

### Required

```yaml
# MinIO configuration - must be provided
echoport_backup_minio_url: "https://minio.example.com"
echoport_backup_minio_access_key: "your-access-key"
echoport_backup_minio_secret_key: "your-secret-key"
```

### Optional

```yaml
# Service identity
echoport_backup_service_name: "echoport-backup"

# MinIO settings
echoport_backup_minio_alias: "minio"
echoport_backup_default_bucket: "backups"
echoport_backup_minio_alias_users: ["{{ echoport_backup_user }}"]
echoport_backup_minio_retired_aliases: []
echoport_backup_minio_prefix_aliases: {}
echoport_backup_minio_require_prefix_alias: false

# Root-owned runner location and FastDeploy service sync
echoport_backup_libexec_root: "/usr/local/libexec/fastdeploy"
echoport_backup_sync_services: true
```

### Runner location

The runner runs as root (`echoport_backup_user`) through FastDeploy's sudo
chain, so the role installs it with
[`fastdeploy_runner`](../fastdeploy_runner/README.md):
`<echoport_backup_libexec_root>/<echoport_backup_service_name>/backup.py`
(root:`deploy` `0750`, every directory above it root-owned), `config.json`
in `echoport_backup_service_dir` names that absolute path, and
`/etc/sudoers.d/echoport_backup` allows only that path. A runner left in the
service directory by an older version is removed after the sync.

With `echoport_backup_sync_services` true (default) the role runs
FastDeploy's `commands.py syncservices` as the fastdeploy user.
`echoport_backup_api_base` and `echoport_backup_api_token` are no longer used
(the role used to call `POST /services/sync`); existing playbooks that set
them keep working.

### MinIO alias

The role gives `echoport_backup_minio_alias_users` the mc alias
`echoport_backup_minio_alias` with `mc alias import`, which reads the
credentials on stdin. They never appear in a command line, where
`mc alias set <alias> <url> <key> <secret>` would show them in the host's
process list. The alias is imported only when the stored URL or credentials
differ, and every alias in `echoport_backup_minio_retired_aliases` is removed
from those users' mc configuration.

Other plays use the same tasks for their own runner:

```yaml
- name: Configure the mc alias of the delve backup
  ansible.builtin.include_role:
    name: local.ops_library.echoport_backup
    tasks_from: minio_alias
  vars:
    echoport_backup_minio_alias: backup-delve
    echoport_backup_minio_url: "http://127.0.0.1:9001"
    echoport_backup_minio_access_key: "{{ account_user }}"
    echoport_backup_minio_secret_key: "{{ account_secret }}"
    echoport_backup_minio_alias_users: [root]
    echoport_backup_minio_retired_aliases: []
```

The generic runner (`backup.py.j2`) serves several Echoport targets. With
`echoport_backup_minio_prefix_aliases` it uses a separate alias, and so a
separate MinIO account (`minio_deploy`, "Backup accounts"), per target: the
alias is chosen by the first segment of the object key, which is the target
name. A key without an entry uses `echoport_backup_minio_alias`.

```yaml
echoport_backup_minio_prefix_aliases:
  nyxmon: backup-nyxmon
  homelab: backup-homelab
```

The runner fails closed on a missing alias. mc reads `<alias>/<bucket>/<key>`
with an alias it does not know as a local path, so `mc cp` would write the
archive below the runner's working directory and `mc stat` would then find
it there, and Echoport would record a backup that never reached MinIO. Before
it archives anything, and again before every `mc cp` (upload, restore
download) and `mc stat` (upload check), the runner runs
`mc --json alias list <alias>` as the runner user and fails the backup or
restore unless the alias exists with an http(s) URL. The error names the
alias and the key prefix; the command's output carries the secret key and is
never printed.

Set `echoport_backup_minio_require_prefix_alias: true` once every target of
the runner has its own entry: a key without one then fails instead of
falling back to `echoport_backup_minio_alias`. Leave it `false` while a target
still uses the shared alias, or to roll a target back to it.

## Dependencies

Includes `local.ops_library.fastdeploy_runner` (runner installation and
registration) and `local.ops_library.minio_backup` (mc installation).

## Example Playbook

```yaml
- hosts: fastdeploy
  roles:
    - role: echoport_backup
      vars:
        echoport_backup_minio_url: "{{ minio_url }}"
        echoport_backup_minio_access_key: "{{ minio_access_key }}"
        echoport_backup_minio_secret_key: "{{ minio_secret_key }}"
```

## Backup Context Variables

When triggering a backup via FastDeploy/Echoport, the following context variables are used:

| Variable | Description |
|----------|-------------|
| `ECHOPORT_TARGET` | Name of the backup target |
| `ECHOPORT_RUN_ID` | Echoport run ID for tracking |
| `ECHOPORT_DB_PATH` | Path to SQLite database to backup |
| `ECHOPORT_BACKUP_FILES` | Comma-separated list of additional files/dirs |
| `ECHOPORT_BUCKET` | MinIO bucket name |
| `ECHOPORT_KEY_PREFIX` | Object key prefix (e.g., `nyxmon/2024-01-15T02-00-00`) |
| `ECHOPORT_TIMESTAMP` | Backup timestamp |
| `ECHOPORT_MEDIA_OBJECTS_PREFIX` | Optional override for rolling media object prefix (default `<prefix_root>/current`) |

FastDeploy writes the Echoport context to the runner config file nested under
`context.env`; runners must read it from there. The FastDeploy runner
(`fastdeploy_backup.py.j2`) falls back to `<target>/<timestamp>` when
`ECHOPORT_KEY_PREFIX` is empty and refuses to upload when it cannot build a
prefix, so a backup never lands on the shared key `.tar.gz`.

## Media Rolling Mode Notes

Media templates in this role use rolling object storage by default:

- Objects are copied to `.../current/objects` (incremental destination).
- Per-run manifests/checksums are still written under the run key prefix for traceability.
- Point-in-time media restore is not supported in this rolling mode; restore reads from the current objects prefix.

Operational tradeoff:

- Media templates use `rclone copy`, which does not delete objects from the destination if they were removed at source.
- This is safer for backup retention, but destination may accumulate deleted-from-source objects over time.

## Paperless Template Notes

`templates/paperless_backup.py.j2` adds service-specific restore safeguards:

- SQL restore uses `--no-owner` dumps and then reconciles ownership/privileges to the app owner.
- Reconciliation includes `public` tables, views, materialized views, and sequences.
- Rollback path runs service-active and DB app-role checks before reporting rollback success.
- Intended probes:
  - HTTP: `http://127.0.0.1:10030/api/schema/view/` -> `200`
  - DB query: `SELECT COUNT(*) FROM paperless_applicationconfiguration;`

## Homepage / Python Podcast Template Notes

`templates/homepage_production_db_backup.py.j2`, `templates/homepage_staging_backup.py.j2`,
`templates/python_podcast_production_db_backup.py.j2` and
`templates/python_podcast_staging_backup.py.j2` restore a PostgreSQL dump by
dropping and recreating the target database. Every process holding a connection
must be down for that window, not just the web service:

- `SERVICE_NAME` is always stopped before the drop and started after `pg_restore`.
- The production-DB runners (`homepage_production_db_backup`,
  `python_podcast_production_db_backup`) run
  `psql -X -v ON_ERROR_STOP=1 -d <db> -c 'ALTER SCHEMA public OWNER TO "<role>"'`
  as postgres right after `createdb --owner=<role> <db>`, inside the
  `drop_recreate_db` step (a failure fails the step and the restore). `createdb`
  copies `template1`, whose `public` schema still belongs to `postgres` on a
  cluster upgraded from PostgreSQL < 15, and `pg_restore --no-owner` skips the
  dump's `ALTER SCHEMA public OWNER`; without this, every nightly staging refresh
  left `public` owned by `postgres` and the next pyinfra deploy planned the ALTER.
- `AUX_SERVICE_NAMES` lists additional units to stop and start, defaulting to
  `<service>-db-worker` (the Django Tasks worker deployed by `wagtail_deploy`).
  Override per service with `<prefix>_aux_service_names`, e.g.
  `homepage_prod_db_backup_aux_service_names`. The register playbooks are not
  consistent about the `.service` suffix on `<prefix>_service_name` — the
  production-DB ones pass `homepage.service`, the staging ones pass `homepage` —
  so the suffix is stripped before `-db-worker` is appended.
- A failed probe raises rather than reporting the unit absent. Reading a
  transient SSH error as "no such unit" would silently skip the very protection
  this adds.
- Auxiliary units are probed with `systemctl show --property=LoadState` and
  skipped when not present, so a site without a worker restores unchanged.
- Units are started in the order they were stopped, and only removed from the
  pending list once actually started, so the `finally` block retries the rest.

A worker left running during the drop crashes with
`relation "django_tasks_database_dbtaskresult" does not exist`, which reaches
Sentry as the misleading `current transaction is aborted, commands ignored until
end of transaction block` — `django_tasks_db` retries the query inside the same
already-aborted transaction.

## Remote runners and the pinned SSH key

The remote runners (`homepage_*`, `python_podcast_*`, `marina_staging_backup`,
`villakunterbunt_staging_backup`, `django_chat_staging_db_backup`,
`gotosocial_backup`, `heis_production_backup`) run on macmini as the `deploy`
user and SSH to their hosts as `root` with deploy's key. On hosts where that
key is pinned to `echoport_remote_command_guard` (production and staging),
only the commands these templates send are accepted, so:

- every runner except heis calls `scp -O` (classic protocol: the remote side
  sees `scp -f|-t <path>`, which the guard can check; the default SFTP mode
  cannot be path-restricted);
- rsync uses exactly `-a --safe-links` for downloads and `-a --no-D` (with or
  without `--delete`) for uploads; the guard accepts only the server commands
  of these options (no device or special files on the host);
- `gotosocial_backup` sends one plain command per SSH call (no shell script)
  and reads its SQLite snapshot with `cat`, which the guard opens without
  following symlinks (the temp dir belongs to the service user);
- a new remote command in a template needs a matching guard rule.
  `just test-echoport-remote-command-guard` renders each runner, drives a
  backup and a restore with the network faked, and fails on any command the
  guard would refuse. When the commands a runner sends change, it also fails
  until the Rust port's fixtures, which record them, are regenerated with
  `just echoport-command-guard-fixtures`;
- the opt-in python-podcast private media restore (`--include-private-media`)
  is refused by the guard.

The register playbooks must re-run (so macmini gets these versions) before a
host's key is pinned; the new forms also work unpinned.

## External work dir (`_work_dir.py.j2`)

`templates/_work_dir.py.j2` is the shared fail-closed work dir logic. The
runners in the table below include it (see the header of the include for the
constants a template defines first); templates not in the table still use
`echoport_backup_temp_dir`. Runners that include it do not read
`echoport_backup_temp_dir` or their old `*_temp_dir` variable and never fall
back to `/tmp`, `/` or the system temp dir.

Before any other work (for the homepage DB runner: before `pg_dump` on
production, before the MinIO download and before staging is touched), a run
checks that:

- the work mount is a normalized absolute path, not `/`, not a symlink, a mount
  point (`os.path.ismount`) and on a different device than `/`;
- every component from the mount down to the work dir is a plain directory (no
  symlink) on the mount's device; missing components are created `0700`;
- the work dir is owned by the runner's expected owner (`WORK_OWNER_UID`) and is
  forced to `0700`.

Each run then gets a fresh `mkdtemp` dir (`0700`) below the work dir, which is
removed in `finally` on success and on failure. Leftover run dirs (direct
children with the runner's prefixes, real directories on the mount, older than
the retention window) are pruned at the start of a run without following
symlinks; removal failures are reported in `init` and do not stop the run.

| Runner | Variables (default) | Owner | Run dir prefixes |
|--------|---------------------|-------|------------------|
| UniFi | `unifi_echoport_backup_work_dir` (`/mnt/cryptdata/backups/tmp/unifi-backup`), `unifi_echoport_backup_work_mount` (`/mnt/cryptdata`), `unifi_echoport_backup_work_retention_hours` (`24`) | root (runs via `sudo -n`) | `unifi_backup_`, `unifi_restore_` |
| homepage production DB | `homepage_prod_db_backup_work_dir` (`/mnt/cryptdata/backups/tmp/homepage-production-db-backup`), `homepage_prod_db_backup_work_mount` (`/mnt/cryptdata`), `homepage_prod_db_backup_work_retention_hours` (`24`) | the runner user (`deploy`) | `homepage-backup-`, `homepage-restore-` |
| homepage media | `homepage_media_backup_work_dir` (`/mnt/cryptdata/backups/tmp/homepage-media-backup`), `homepage_media_backup_work_mount` (`/mnt/cryptdata`), `homepage_media_backup_work_retention_hours` (`24`) | the runner user (`deploy`) | `homepage-media-` |
| delve | `delve_echoport_backup_work_dir` (`/mnt/cryptdata/backups/tmp/delve-backup`), `delve_echoport_backup_work_mount`, `delve_echoport_backup_work_retention_hours` | root (runs via `sudo -n`) | `delve_backup_`, `delve_restore_` |
| SnappyMail | `snappymail_echoport_backup_work_dir` (`/mnt/cryptdata/backups/tmp/snappymail-backup`), `snappymail_echoport_backup_work_mount`, `snappymail_echoport_backup_work_retention_hours` | root (runs via `sudo -n`) | `snappymail_backup_`, `snappymail_restore_` |
| Vaultwarden | `vaultwarden_echoport_backup_work_dir` (`/mnt/cryptdata/backups/tmp/vaultwarden-backup`), `vaultwarden_echoport_backup_work_mount`, `vaultwarden_echoport_backup_work_retention_hours` | root (runs via `sudo -n`) | `vaultwarden_backup_`, `vaultwarden_restore_` |
| PostfixAdmin | `postfixadmin_echoport_backup_work_dir` (`/mnt/cryptdata/backups/tmp/postfixadmin-backup`), `postfixadmin_echoport_backup_work_mount`, `postfixadmin_echoport_backup_work_retention_hours` | root (runs via `sudo -n`) | `postfixadmin_backup_`, `postfixadmin_restore_` |
| Minecraft Java | `minecraft_java_echoport_backup_work_dir` (`/mnt/cryptdata/backups/tmp/minecraft-java-backup`), `minecraft_java_echoport_backup_work_mount`, `minecraft_java_echoport_backup_work_retention_hours` | root (runs via `sudo -n`) | `minecraft_backup_`, `minecraft_restore_` |
| Home Assistant | `homeassistant_backup_work_dir` (`/mnt/cryptdata/backups/tmp/homeassistant-backup`), `homeassistant_backup_work_mount`, `homeassistant_backup_work_retention_hours` | root (runs via `sudo -n`) | `ha-backup-`, `ha-restore-` |
| Graphyard | `graphyard_echoport_backup_work_dir` (`/mnt/cryptdata/backups/tmp/graphyard-backup`), `graphyard_echoport_backup_work_mount`, `graphyard_echoport_backup_work_retention_hours` | root (runs via `sudo -n`) | `graphyard-backup-`, `graphyard-restore-` |
| FastDeploy, weeknotes-home (`fastdeploy_backup.py.j2`) | `fastdeploy_echoport_backup_work_dir` (`/mnt/cryptdata/backups/tmp/fastdeploy-backup`), `fastdeploy_echoport_backup_work_mount`, `fastdeploy_echoport_backup_work_retention_hours` | root (runs via `sudo -n`) | `fd-backup-`, `fd-restore-` |
| Echoport self (`echoport_backup.py.j2`) | `echoport_self_backup_work_dir` (`/mnt/cryptdata/backups/tmp/echoport-self-backup`), `echoport_self_backup_work_mount`, `echoport_self_backup_work_retention_hours` | root (runs via `sudo -n`) | `echoport-self-backup-`, `echoport-self-restore-` |
| Paperless | `paperless_echoport_backup_work_dir` (`/mnt/cryptdata/backups/tmp/paperless-backup`), `paperless_echoport_backup_work_mount`, `paperless_echoport_backup_work_retention_hours` | root (runs via `sudo -n`) | `paperless-backup-`, `paperless-restore-` |
| mail DB | `mail_db_echoport_backup_work_dir` (`/mnt/cryptdata/backups/tmp/mail-db-backup`), `mail_db_echoport_backup_work_mount`, `mail_db_echoport_backup_work_retention_hours` | root (runs via `sudo -n`) | `mail_db_backup_`, `mail_db_restore_` |
| generic (`backup.py.j2`, all SQLite/file targets) | role defaults `echoport_backup_work_dir` (`/mnt/cryptdata/backups/tmp/echoport-backup`), `echoport_backup_work_mount` (`/mnt/cryptdata`), `echoport_backup_work_retention_hours` (`24`) | root (runs via `sudo -n`) | `echoport_`, `echoport_restore_` |

The homepage runners run as `deploy` (FastDeploy's `sudo -u deploy`, no rule to
root: their SSH key and `mc` config belong to `deploy`), so `deploy` cannot
create directories below `/mnt/cryptdata/backups` (`root:postgres 0770`). The
register playbook in the control repo provisions the work dir (`deploy:deploy
0700`) and a traverse-only ACL for `deploy` on the parents; without that the run
fails closed in `init` with a permission error.

File modes in the homepage runners:

- production DB backup: umask `077`, so the dump, manifest and archive are
  `0600`;
- production DB restore: the system umask is kept; the downloaded archive is
  chmodded to `0600`, and the extracted dump to `0644` right before it is copied
  to staging, because classic `scp` creates the remote file with the local mode
  and `pg_restore` reads it there as `postgres` (archives made under umask `077`
  carry the dump as `0600`). Locally it stays private inside the `0700` run dir;
- media: umask `077` for backup and restore (rclone config with credentials and
  the manifest are `0600`; objects go S3 <-> MinIO without touching the disk).

The other runners keep the process umask. Their files are private because the
run dir is `0700` below a `0700` work dir (root runners: `root:root`), and the
archives keep the modes they had before, so a restore puts files back into
live paths with the same modes as before the move. Where a runner already set
modes explicitly (for example `0600` for credentials or a restored database),
that is unchanged.

Root runners (they re-run themselves through `sudo -n`) create their work dir
`root:root 0700` on the first run; `/mnt/cryptdata/backups/tmp` must exist
(the control repo does not provision anything for them). A missing mount fails
the run before any command: for runners that validate their configuration
first, after that validation and before the first write. Free-space checks
that looked at the old temp dir (Graphyard, FastDeploy, Echoport self and
Paperless restores) now measure the work dir.

The generic runner serves every SQLite/file target through one work dir, so a
missing mount fails all of its targets at once. It reports the refusal as an
`init` failure with `ECHOPORT_RESULT` success `false` (backup and restore),
after the path and MinIO alias checks and before anything is copied,
downloaded or stopped. `echoport_backup_temp_dir` stays in the role defaults
only for the templates that do not include the work dir yet.

The FastDeploy template serves two runners; the weeknotes-home register
playbook sets `fastdeploy_echoport_backup_work_dir` to its own directory.

PostgreSQL steps never read or write the work dir as `postgres`, which cannot
traverse the root-only run dir:

- `pg_dump` runs as `postgres` and writes to stdout; the runner (root) writes
  the file (FastDeploy, Paperless, mail DB);
- `pg_restore` (FastDeploy, mail DB) and the Paperless `psql` restore read the
  dump on stdin. The Paperless restore used to copy the dump to
  `<temp dir>/restore-db/` (outside the run dir, `0644`) and pass that path to
  `psql --file`; it now opens the dump in the run dir before dropping the
  database and runs `psql --file -` with the file on stdin, so nothing is
  staged outside the run dir.

## UniFi Template Notes

The UniFi runner (`unifi_backup.py.j2`) keeps its per-run work dirs (MongoDB
dump, staging copies of data/config, the archive, the restore download and
extraction, the pre-restore safety snapshot) on the external encrypted disk
only. It does not read `echoport_backup_temp_dir`.
The checks below come from the shared include described in
[External work dir](#external-work-dir-_work_dirpyj2).

| Variable | Default | Description |
|----------|---------|-------------|
| `unifi_echoport_backup_work_dir` | `/mnt/cryptdata/backups/tmp/unifi-backup` | Parent of the per-run dirs; must be below the work mount |
| `unifi_echoport_backup_work_mount` | `/mnt/cryptdata` | Mount point the work dir must live on |
| `unifi_echoport_backup_work_retention_hours` | `24` | Leftover run dirs older than this are removed at the start of a run (minimum 1) |

Before any other work, backup and restore check (fail closed, no fallback to
`/tmp` or `/`):

- the work mount is a normalized absolute path, not `/`, not a symlink, a mount
  point (`os.path.ismount`) and on a different device than `/`;
- every component from the mount down to the work dir is a plain directory (no
  symlink) on the mount's device (`st_dev`); missing components are created
  root-owned `0700`;
- the work dir is owned by root and is forced to `0700`.

Each run creates a fresh `unifi_backup_*`/`unifi_restore_*` dir (`mkdtemp`,
`0700`) and removes it in `finally`, on success and on failure. The backup runs
with umask `077`, so runner-created files (dumps, manifests, archive) are
`0600`; the restore keeps the system umask because it writes into live service
paths, and chmods the downloaded archive to `0600`. At the start of each run,
direct children of the work dir named `unifi_backup_*`/`unifi_restore_*` that
are real directories on the mount and older than the retention window are
removed; symlinks and other entries are left alone and `shutil.rmtree` does not
follow symlinks inside a tree. Removal failures are reported in the `init` step
and do not stop the run.

The work dir is not one of `unifi_echoport_backup_allowed_roots`; a
`/tmp/unifi-backup/` entry left in that list is unused.

## FastDeploy runner restores

The FastDeploy runner (`fastdeploy_backup.py.j2`) does not restore the
services, runner entries and sudoers files retired by the FastDeploy privilege
reduction (`fastdeploy_echoport_backup_retired_entries`,
`fastdeploy_echoport_backup_retired_sudoers`), even from older archives, and it restores other archived sudoers files only when they hold nothing but
narrow per-script rules (older `fastdeploy_register_service` files with
`deploy ALL=(root) NOPASSWD: ALL` are skipped).

## Python Podcast Private Media

`templates/python_podcast_production_db_backup.py.j2` also backs up
python-podcast's private media: contributor voice references and the
known-speaker suggestion sidecar, kept on the server filesystem and off the
public S3 bucket, so neither `pg_dump` nor the S3 media backup covers them.

| Variable | Default | Purpose |
|----------|---------|---------|
| `pp_prod_db_backup_private_media_path` | `/home/python-podcast/site/private_media` | Directory on the backup host; `""` disables the step |
| `pp_prod_db_backup_private_media_max_bytes` | `2147483648` | `du` size guard; a larger tree fails the backup |
| `pp_prod_db_backup_restore_private_media` | `false` | Restore private media to staging by default |
| `pp_prod_db_backup_restore_private_media_path` | `/home/python-podcast/site/private_media` | Restore target on the staging host |
| `pp_prod_db_backup_restore_private_media_owner` | `python-podcast:python-podcast` | Owner of the restored tree |

Backup:

- The directory is probed first. Missing is a warning (recorded as
  `"included": false` in the manifest); a failed probe, a symlink or a
  non-directory fails the backup rather than silently dropping the clips.
- `tar -C <parent> -czf` runs read-only on the source and writes into a fresh
  `mktemp -d` directory (0700, removed afterwards), never a predictable `/tmp`
  file name; the archive is copied back, every member is checked (same safety check as the
  outer archive, plus: under the directory's own name, regular files and
  directories only, uncompressed size within the guard) and it is shipped as
  `private_media/private_media.tar.gz` in the same uploaded archive. The
  manifest's `private_media` entry carries its own `checksum_sha256`.

Restore (staging):

- Skipped by default, and the private media members are not even extracted
  (names are normalized first, and the outer archive may not contain links,
  which this runner never writes), so
  production voice clips do not spread to staging unasked. Staging's own
  private media stays untouched.
- Opt in with `pp_prod_db_backup_restore_private_media: true` or by running
  the runner manually with `--include-private-media`. Nothing in the Echoport
  restore context can switch it on.
- When opted in, the nested archive's checksum and members are verified
  before any service is stopped. The tree is swapped in after `pg_restore`
  while the services are still stopped; the previous tree is moved back if
  the swap fails.

## Django Chat Staging Database Template Notes

`templates/django_chat_staging_db_backup.py.j2` backs up the Django Chat
PostgreSQL database on the staging host (Django Chat has no production). It
runs on macmini as the deploy user and reaches the staging host as root over
SSH with the deploy key; only the deploy user's mc alias touches MinIO.

- Backup: `pg_dump --format=custom` runs on the staging host as `postgres` and
  streams to macmini. `pg_restore --list` must show data for every table in
  `django_chat_staging_db_backup_required_tables`; the row counts of
  `_counted_tables` are read from the dump, not the live database. The
  tarball holds the dump, `manifest.json` (host, database, server version,
  tables, row counts) and `manifest.sha256`. A failed or empty dump, a missing
  table or a stored size that differs fails the run.
- Restore: never touches the live database. After the archive checksum, both
  manifest checksums and the dump are verified, the dump goes into a fresh
  `mktemp -d` directory (root, 0700) on the staging host, is compared by
  SHA-256, and is restored into the new database `<prefix>_<restore id>`
  (`--no-owner --no-privileges --exit-on-error`, an existing name is refused).
  Its row counts are compared with the manifest; the temp directory is removed
  either way. Dropping the scratch database, or swapping it in, is left to
  ops-control.
- `pg_restore` on macmini reads the dump, so its major version must not be
  older than the staging server's; otherwise the run fails at `--list`.
- Variables: `django_chat_staging_db_backup_host`, `_remote_user`, `_db_name`,
  `_postgres_os_user`, `_restore_db_prefix`, `_required_tables`,
  `_counted_tables`, plus the shared `echoport_backup_*` MinIO settings. Media
  is not included: Django Chat keeps it, private voice references too, in S3.

## Graphyard Template Notes

`templates/graphyard_backup.py.j2` is the service-owned same-host runner for Graphyard:

- Backup scope:
  - Django SQLite DB
  - native InfluxDB backup payload from the `graphyard-influxdb` container
  - `/etc/graphyard/graphyard.env`
  - Graphyard systemd units
  - optional `/var/lib/graphyard/influxdb2-config`
- Restore ordering is explicit:
  - restore InfluxDB first
  - restore SQLite second
  - restore env/systemd/config
  - start `graphyard-web`
  - run `manage.py start_agent --run-once`
  - start `graphyard-agent`
  - verify `/v1/health`
- Safety snapshot + rollback use the same native InfluxDB backup format, so rollback restores both
  the time-series state and SQLite state.
- Grafana DB state is intentionally excluded. Dashboards/provisioning live in the Graphyard repo and
  Grafana datasource/admin reconciliation is handled by the Graphyard bootstrap/deploy path.

## Output Format

The backup script outputs a special line for Echoport to parse:

```
ECHOPORT_RESULT:{"success": true, "bucket": "backups", "key": "nyxmon/2024-01-15T02-00-00.tar.gz", "size_bytes": 12345, "checksum_sha256": "abc123...", "manifest": {...}}
```

## License

MIT

## Verified release downloads

The mc installer reuses `minio_backup/tasks/mc_install.yml`. Each deploy reconciles the existing mc binary at `echoport_backup_mc_install_path` (default `/usr/local/bin/mc`) against the pinned SHA-256, replacing a different binary. The default GitHub URL replaces the discontinued dl.min.io endpoint. Override `echoport_backup_mc_download_url` only with an artifact matching `echoport_backup_mc_checksum`. Linux amd64 remains the supported target.

Pinned defaults (checksum map keys identify the release architecture/target):

| Variable | Default |
| --- | --- |
| `echoport_backup_mc_version` | `RELEASE.2025-08-13T08-35-41Z` |
| `echoport_backup_mc_checksum` | `sha256:01f866e9c5f9b87c2b09116fa5d7c06695b106242d829a8bb32990c00312e891` |

To update, bump the version and checksum together. Fetch the SHA-256 from the
project’s published checksum file or release-page asset digest over HTTPS,
and update the source URL comment beside the checksum in `defaults/main.yml`.
Never reuse the old checksum for a new version. Supply matching checksums for
every enabled architecture. Run `just test-root-downloads` before deploying.
