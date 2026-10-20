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
- sets the fact `echoport_remote_command_guard_forced_command`
  (`/usr/bin/python3 -I <guard> <policy>`) for the `authorized_keys` entry.

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

## Testing

```bash
just test-echoport-remote-command-guard   # guard rules + every remote runner's real commands
just molecule-test echoport_remote_command_guard  # real sshd, fish login shell, scp -O, rsync, snapshot, dump upload
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
