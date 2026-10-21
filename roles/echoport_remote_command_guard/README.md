# echoport_remote_command_guard

Forced-command allowlist for the SSH key the Echoport remote backup runners
(`echoport_backup` templates `homepage_production_db_backup`,
`python_podcast_production_db_backup`, `homepage_staging_backup`,
`python_podcast_staging_backup`, `marina_staging_backup`,
`villakunterbunt_staging_backup`, `django_chat_staging_db_backup`,
`gotosocial_backup`) use to log in as `root` on the hosts they back up and
restore.

Without it that key is plain root on every host that trusts it. With it, the
key can only run the commands those runners send, with the databases, units
and paths named in a per-host policy.

## What the role does

- installs `files/echoport-remote-command-guard.py` to
  `/usr/local/sbin/echoport-remote-command-guard` (root, `0755`);
- writes the policy as JSON to `/etc/echoport/remote-command-guard.json`
  (root, `0644`), validated by the guard itself (`--check-policy`) before it
  replaces the old one;
- sets the fact `echoport_remote_command_guard_forced_command` for the
  `authorized_keys` entry: `/usr/bin/python3 -I <guard> <policy>` with the
  default impl `python` (see [Rust guard](#rust-guard-impl-selector) for
  `shadow` and `rust`);
- with `echoport_remote_command_guard_rust_version` set, installs the Rust
  port of the guard as well (below).

The role does not touch `authorized_keys`. The consumer pins the key, for
example with `ssh_authorized_keys_manage`:

```text
from="<runner host addresses>",restrict,command="<echoport_remote_command_guard_forced_command>" ssh-ed25519 AAAA... deploy@macmini
```

Install the guard (this role) before pinning the key, otherwise the forced
command does not exist yet and every run fails.

## Allowed commands

sshd hands the requested command to the guard in `SSH_ORIGINAL_COMMAND`. It
is parsed with `shlex` and must match one of these shapes exactly; the guard
then executes it directly (no shell) with a fixed `PATH`:

| Shape | Allowed when |
|---|---|
| `sudo -u postgres pg_dump --format=custom --file=<f> --dbname=<db>` | `db` in `postgres.dump_databases`, `f` is `/tmp/echoport_<prefix>_dump_<stamp>.dump` |
| `sudo -u postgres dropdb --if-exists --force <db>`, `createdb --owner=<role> <db>`, `pg_restore --exit-on-error --dbname=<db> --no-owner --role=<role> <f>` | `postgres.restore_databases[db] == role`, `f` is `/tmp/echoport_<prefix>_restore_<stamp>.dump` |
| `sudo -u postgres psql -d <db> -c 'SELECT 1'` | `db` in either database list |
| `runuser -u postgres -- <tool> ...` | the same tools and rules as `sudo -u postgres`, plus the Django Chat shapes below |
| `runuser -u postgres -- pg_dump --format=custom --dbname=<db>` (to stdout) | `db` in `postgres.dump_databases` |
| `runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -qAt -d <db> -c <sql>` | `SHOW server_version;` on a dump database; `SELECT 1 FROM pg_database WHERE datname = '<scratch>';` on `postgres`; `SELECT count(*) FROM public.<table>;` on a scratch database |
| `runuser -u postgres -- createdb <scratch>`, `runuser -u postgres -- pg_restore --no-owner --no-privileges --exit-on-error --dbname=<scratch> < <tmpdir>/<name>.dump` | `<scratch>` is `<prefix>_<digits>` for a `postgres.scratch_restore_prefixes` entry; the guard opens the dump itself |
| `umask 077 && cat > <tmpdir>/<name>.dump`, `sha256sum <tmpdir>/<name>.dump` | `<tmpdir>` from a `temp_dirs` template; the guard creates the file itself (exclusive, `0600`) |
| `systemctl show --property=LoadState --value <u>`, `systemctl start\|stop <u>` | `u` in `units` |
| `scp -f <path>` (download) | a dump file, the private media archive, a `read_files` entry, or a path inside a `path_roots` entry; must be missing or a regular file |
| `scp -t <path>` (upload) | a restore dump file (runs as `postgres`), or `<path>.tmp` / `<path>.restore-tmp` inside a root (runs as the root's owner); must be new or a regular file with one link (no symlink, device, FIFO, directory) |
| `rsync <server args> . <dir>/` | `dir` inside a root, server args exactly one of the three below; a receiver (upload) runs as the root's owner |
| `readlink -f`, `test -e\|-d\|-f`, `mv <p>.tmp <p>` | paths inside a root |
| `mkdir -p <path>` | path inside a root; runs as the root's owner |
| `mv <a> <b>` | both inside the same root, `<b>` does not exist |
| `chmod 0600\|0700 <path>` | path inside a root |
| `chown [-R] <owner> <path>` | path inside a root whose `owner` matches |
| `rm -f <dump>`, `rm -f <db>-wal <db>-shm` | dump file pattern, or inside a root |
| `mktemp -d <template>`, `rm -rf -- <tmpdir>` | `<template>` in `temp_dirs` or a `sqlite_snapshots` entry's `temp_dir` |
| `chown <owner> <tmpdir>`, `runuser -u <user> -- sqlite3 <database> [".timeout <ms>"] ".backup '<tmpdir>/<name>'"`, `runuser -u <user> -- sqlite3 <tmpdir>/<name> 'PRAGMA integrity_check;'`, `cat <tmpdir>/<name>` | a `sqlite_snapshots` entry (the GoToSocial online snapshot): `<tmpdir>` from its `temp_dir`, `<owner>`/`<user>` its owner; `cat` is fed by the guard, which opens the file without following symlinks |
| `curl -fsS -o /dev/null <url>` | `url` in `ready_urls` |
| `sh -c '<probe>'`, `du -sb -- <p>`, `mktemp -d /tmp/echoport-pp-private-media.XXXXXXXX`, `umask 077 && tar -C <parent> -czf <tmpdir>/private_media.tar.gz -- <name>`, `rm -rf -- <tmpdir>` | the python-podcast private media backup, `<p>` in `private_media_paths` |

"Inside a root" is decided on the resolved path (`os.path.realpath`), so a
symlink inside a root that points elsewhere is refused. Paths may only
contain `[A-Za-z0-9._/-]` and no `.`/`..` components.

Uploads run as an unprivileged user (`runuser -u <user> --`): into a root as
the root's `owner` (which must not be root), restore dumps as `postgres`. The
scp sink takes the file mode from the sender and the rsync receiver would
keep the sender's owner, mode and devices as root; as the owner the sender
cannot create root-owned, setuid-root or device files, and a symlink swapped
in by that user only redirects a write that user could do anyway. The tar
archive and the `sha256sum`/redirect targets must lie in a private directory
of the guard's own user (a fresh `mktemp -d`), which nobody else can fill or
replace.

### rsync

Only the server side of the runners' exact client options is accepted
(derived with a recording `-e` program from rsync 3.2.7, Ubuntu 24.04, the
runner host, and rsync 3.5.0, Debian 13; both send the same):

| Runner client call | Server command the guard accepts |
|---|---|
| `rsync -a --safe-links <host>:<dir>/ <local>/` (download) | `rsync --server --sender -logDtpre.iLsfxCIvu --safe-links . <dir>/` |
| `rsync -a --no-D <local>/ <host>:<dir>/` (upload) | `rsync --server -logtpre.iLsfxCIvu . <dir>/` |
| `rsync -a --no-D --delete <local>/ <host>:<dir>/` (upload, mirror) | `rsync --server -logtpre.iLsfxCIvu --delete . <dir>/` |

Anything else is refused: `-L`/`--copy-links` (read through a symlink out of
the root), `-K` (write through one), device and special files (`D`, which
plain `-a` sends), `--remove-source-files` and other options. A different
rsync client version that sends other strings fails closed; derive the new
strings and add them to `RSYNC_SERVER_ARGS`.

### Files the guard opens itself

For `< file` (Django Chat `pg_restore`), `> file` (`umask 077 && cat >`) and
the GoToSocial snapshot `cat`, the guard opens the directory with
`O_NOFOLLOW|O_DIRECTORY` (it must belong to the guard's user, or the
snapshot's service user, with no group/other access) and the file inside it
with `O_NOFOLLOW` (create: `O_EXCL`, `0600`); the file must be a regular file
with one link. Downloads (`scp -f`, the rsync sender) run as root and open
their own paths after the guard's checks: a local user who can write inside a
root could swap a path for a symlink in between and have root read another
file into the backup (not new; the runners did the same before the pin).

**Known race, accepted for the Rust guard 0.1.0 only (owner decision
2026-10-21):** `chmod 0600|0700 <path>`, `chown [-R] <owner> <path>`, both
`mv` forms (including `mv <p>.tmp <p>`) and `rm -f <db>-wal <db>-shm` are
checked on the resolved path, then run **as root** on the original pathname,
which the tool resolves again. A local user who can write inside a policy
root (its service user) can swap the path, or a directory on it, for a
symlink in between and have root change the mode or owner of a file outside
the root, or rename or delete one there (service user → root). The Python
guard has this race today, and the Rust guard 0.1.0 ports it unchanged
(`rust/echoport-command-guard/PLAN.md` 4.5 and R12). The fix, in both guards,
is work item `echoport-guard-toctou-hardening` (slice H1 of that plan); it
must be merged and released before the Rust guard is installed on any host,
so no host runs 0.1.0.

Everything else is refused with `command not allowed` (exit 1), including an
interactive session, the SFTP subsystem (which is why the runners call
`scp -O`), command chaining and any other user than `postgres` for `sudo`.
Accepted and refused commands are logged to syslog (`LOG_AUTH`) as
`echoport-remote-command-guard`.

Accepted risk: restores run `pg_restore` in a PostgreSQL superuser session
(`--role=` / scratch databases); a crafted dump can run code as the OS user
`postgres` on the host. The runners only restore dumps of their own backups.

Not supported: the opt-in python-podcast private media *restore*
(`--include-private-media`), whose installer script cannot be matched
exactly. Restore private media through ops-control instead.

## Variables

| Variable | Default | Purpose |
|---|---|---|
| `echoport_remote_command_guard_policy` | `{}` | The policy (see below). Empty allows nothing. |
| `echoport_remote_command_guard_path` | `/usr/local/sbin/echoport-remote-command-guard` | Guard location. |
| `echoport_remote_command_guard_policy_path` | `/etc/echoport/remote-command-guard.json` | Policy location. |
| `echoport_remote_command_guard_python` | `/usr/bin/python3` | Interpreter for the forced command. |
| `echoport_remote_command_guard_impl` | `python` | Which guard decides: `python`, `shadow` or `rust` (below). |
| `echoport_remote_command_guard_rust_version` | `""` | Rust guard release to install (e.g. `0.1.0`); installed even with impl `python`. Empty: no Rust guard. |
| `echoport_remote_command_guard_rust_sha256` | `""` | sha256 of the release archive; required unless a local archive is set. |
| `echoport_remote_command_guard_rust_local_archive` | `""` | Archive on the controller instead of the GitHub release (development, molecule). |
| `echoport_remote_command_guard_rust_install_root` | `/usr/local/lib/echoport-command-guard` | `<root>/<version>/echoport-command-guard`. |
| `echoport_remote_command_guard_rust_keep_versions` | `3` | Newest Rust versions `confirm_live.yml` keeps, on top of the pins and the versions `authorized_keys` names. |
| `echoport_remote_command_guard_authorized_keys_path` | `/root/.ssh/authorized_keys` | `confirm_live.yml`: the file the playbook wrote. |
| `echoport_remote_command_guard_confirm_public_key` | `""` | `confirm_live.yml`: the pinned key (`<type> <base64> [comment]`) whose line carries the forced command. |

Policy shape:

```yaml
echoport_remote_command_guard_policy:
  postgres:
    dump_databases: [homepage, python-podcast]
    restore_databases: {homepage: homepage, python-podcast: python-podcast}
    temp_file_prefixes: [homepage, pp]
    scratch_restore_prefixes: [django_chat_restore]   # <prefix>_<digits>
  units: [homepage.service, homepage-db-worker, marina.service, gotosocial]
  private_media_paths: [/home/python-podcast/site/private_media]
  path_roots:
    - {path: /home/marina/site, owner: "marina:marina"}
  temp_dirs: [/var/tmp/django-chat-db-restore.XXXXXXXX]   # mktemp -d templates, root-only
  sqlite_snapshots:
    - database: /var/lib/gotosocial/sqlite.db
      owner: "gotosocial:gotosocial"
      temp_dir: /var/tmp/gotosocial-echoport.XXXXXX
  read_files: [/etc/gotosocial/config.yaml]               # scp -f only
  ready_urls: ["http://127.0.0.1:10070/readyz"]           # curl -fsS -o /dev/null
```

## Example

```yaml
- hosts: staging
  become: true
  tasks:
    - name: Install the guard
      ansible.builtin.include_role:
        name: local.ops_library.echoport_remote_command_guard
      vars:
        echoport_remote_command_guard_policy: "{{ my_policy }}"

    - name: Pin the backup key
      ansible.builtin.include_role:
        name: local.ops_library.ssh_authorized_keys_manage
      vars:
        ssh_authorized_keys_manage_user: root
        ssh_authorized_keys_manage_group: root
        ssh_authorized_keys_manage_home: /root
        ssh_authorized_keys_manage_entries:
          - key: "{{ deploy_public_key }}"
            comment: deploy@macmini backup automation
            key_options: >-
              from="100.64.0.10",restrict,command="{{ echoport_remote_command_guard_forced_command }}"
```

## Rust guard (impl selector)

The guard is being ported to Rust (`rust/echoport-command-guard/PLAN.md`,
binary `echoport-command-guard`, released as
`echoport-command-guard-v<version>` on GitHub). The role switches between
them with `echoport_remote_command_guard_impl`:

| impl | Forced command | Who decides |
|---|---|---|
| `python` (default) | `/usr/bin/python3 -I <guard> <policy>`, byte for byte as before | the Python guard |
| `shadow` | `<bin> --shadow <policy> /usr/bin/python3 -I <guard> <policy>` | the Python guard; the Rust guard logs its decision first (identifier `echoport-remote-command-guard-shadow`, one JSON record, same `_PID` as the Python line) and then always execs Python |
| `rust` | `<bin> <policy>` | the Rust guard |

`<bin>` is `<rust_install_root>/<rust_version>/echoport-command-guard`.
Every part is a plain path, so nothing needs quoting inside `command="…"`.

With `echoport_remote_command_guard_rust_version` set (required for `shadow`
and `rust`, together with `_rust_sha256` or `_rust_local_archive`) the main
tasks also

- install the release through the internal helper `rust_release_binary`
  (verified download, exact archive members, root:root `0755`, and
  `<bin> --version` as `nobody` must name the version);
- assert that every component of `<bin>`'s path up to `/` is no symlink,
  belongs to root and is not group- or world-writable (sshd runs it as
  root), and that `<bin>`, its version directory and the install root are
  root:root `0755`;
- run the Rust `--check-policy` on the rendered policy before the policy is
  installed (the Python guard still validates it on install, as before).

The Python guard is always installed: it is the rollback target and what
`shadow` execs.

**Rollback independence.** With impl `python` every Rust step only warns
(an ignored failed task): a missing, broken or unrunnable Rust release
never blocks a switch back to Python. With `shadow` or `rust` a Rust failure
stops the play before the forced command is published, so the old line
stays.

**No pin and no prune in the main tasks.** When they run, the new
`authorized_keys` line is not written yet. The consumer includes
`tasks_from: confirm_live.yml` after it wrote the line and probed through
it (in the same play, for every impl, the rollback included):

```yaml
- name: Confirm the guard live, pin and prune
  ansible.builtin.include_role:
    name: local.ops_library.echoport_remote_command_guard
    tasks_from: confirm_live.yml
  vars:
    echoport_remote_command_guard_confirm_public_key: "{{ deploy_public_key }}"
```

`confirm_live.yml`

1. reads `authorized_keys` and requires exactly one line for the pinned key,
   with exactly the published `command="…"` (fatal for every impl); with
   `shadow`/`rust`, `<bin> --version` must name the target version;
2. builds the protect list: every version any line names as
   `<root>/<version>/echoport-command-guard` (also other keys' and hand-edited
   lines), plus `rust_version`. A line that mentions the install root in any
   other form, or an unreadable file, makes the live state unknown and the
   prune deletes nothing;
3. moves the pins of the consumer `echoport_remote_command_guard`
   (`<root>/.pins/`): `shadow`/`rust` pin the target version (the old one
   becomes the previous pin); `python` removes the current pin and keeps its
   version as the previous pin, so the last Rust version verified live stays
   installed for a quick switch back;
4. prunes: keeps the `rust_keep_versions` newest versions, every pinned
   version and the protect list.

A play that stops before step 3 moves no pin and prunes nothing. With impl
`python` steps 3 and 4, and invalid Rust inputs (version, install root,
`keep_versions`), only warn; the line is still verified. In check mode nothing changes; a line that
is not written yet is reported instead of failing.

Switch and rollback are the same play with another impl: set
`echoport_remote_command_guard_impl: rust` (or `shadow`) and run it; to roll
back, run it with `python`. The ops-control wiring (pins in the inventory,
the playbook's `confirm_live.yml` include, the pre-probe switch for a broken
Rust binary, the shadow compare script) is slice S8 of the plan.

## Testing

```bash
just test-echoport-remote-command-guard   # guard rules + every remote runner's real commands + the impl selector
just molecule-test echoport_remote_command_guard  # impl python: real sshd, fish login shell, scp -O, rsync, snapshot, dump upload
just test-echoport-remote-command-guard-molecule  # the scenarios default, shadow, rust and pins
```

The unit tests render each remote runner template, drive a backup and a
restore from that backup with the network faked, and require every command
the runner would send to pass the guard for its host; rsync calls are mapped
from the runner's real client options to the server command (unknown options
fail). They also cover the refusals (rsync `-L`/`-K`/devices, scp onto
symlinks, devices, FIFOs and hard links, the redirect files). Molecule runs
the runners' rsync/scp options, a SQLite snapshot fetched through the guard's
`cat` (a symlink in its place is refused) and a dump upload into a root-only
temp dir against a real sshd.

The molecule scenarios `default` (impl python), `shadow` and `rust` run the
same playbooks (`molecule/shared/`) on Ubuntu 24.04 and Debian 13: the role,
the `authorized_keys` line, the post-probe and `confirm_live.yml`, then the
verify above. `shadow` and `rust` install the guard built from the checkout
as its crate version (`rust/echoport-command-guard/Cargo.toml`, `0.1.0`;
`rust/echoport-command-guard/parity/e2e/build-local-archive.sh`
builds it in a Debian 12 container for the Docker host's architecture; set
`ECHOPORT_GUARD_LOCAL_ARCHIVE` to use another archive). The shadow run also
requires one shadow journal line per guard line with the same `_PID`.
The `pins` scenario runs simulated playbook runs cut after any step with
stub releases and impl `shadow`: repeated failed deployments with different
targets, a stale line, a written but unverified line, protection from the
live state alone, an unknown live state, the switch to Python, check mode,
and the rollback-independence cases (a binary that exits 1 and an archive
that is not gzip converge with impl `python`; `rust` stops).
`tests/test_echoport_remote_command_guard_role.py` covers the live-state
filter, the forced command per impl and `confirm_live.yml` against
localhost.

The guard is being ported to Rust (`rust/echoport-command-guard/PLAN.md`);
the Python guard stays the reference. Its decisions are frozen as fixtures in
`rust/echoport-command-guard/fixtures/`, generated from this guard and the
runners' recorded commands. `just test-echoport-remote-command-guard` fails
when the guard or a runner template changed without them, so after such a
change run

```bash
just echoport-command-guard-fixtures   # needs uv; generates under Python 3.12, checks 3.13
```

and commit the regenerated fixtures (and, once the port has rules, the Rust
rule) in the same change.
