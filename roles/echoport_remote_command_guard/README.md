# echoport_remote_command_guard

Forced-command allowlist for the SSH key the Echoport remote backup runners
(`echoport_backup` templates `homepage_production_db_backup`,
`python_podcast_production_db_backup`, `homepage_staging_backup`,
`python_podcast_staging_backup`, `marina_staging_backup`,
`villakunterbunt_staging_backup`) use to log in as `root` on the hosts they
back up and restore.

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
| `systemctl show --property=LoadState --value <u>`, `systemctl start\|stop <u>` | `u` in `units` |
| `scp -f <path>` (download) | a dump file, the private media archive, or a path inside a `path_roots` entry |
| `scp -t <path>` (upload) | a restore dump file, or `<path>.tmp` inside a root |
| `rsync --server --sender <flags> --safe-links . <dir>/` | `dir` inside a root |
| `rsync --server <flags> --delete . <dir>/` | `dir` inside a root |
| `readlink -f`, `test -e\|-d`, `mkdir -p`, `mv <p>.tmp <p>` | paths inside a root |
| `chown [-R] <owner> <path>` | path inside a root whose `owner` matches |
| `rm -f <dump>`, `rm -f <db>-wal <db>-shm` | dump file pattern, or inside a root |
| `sh -c '<probe>'`, `du -sb -- <p>`, `mktemp -d /tmp/echoport-pp-private-media.XXXXXXXX`, `umask 077 && tar -C <parent> -czf <tmpdir>/private_media.tar.gz -- <name>`, `rm -rf -- <tmpdir>` | the python-podcast private media backup, `<p>` in `private_media_paths` |

"Inside a root" is decided on the resolved path (`os.path.realpath`), so a
symlink inside a root that points elsewhere is refused. Paths may only
contain `[A-Za-z0-9._/-]` and no `.`/`..` components.

Everything else is refused with `command not allowed` (exit 1), including an
interactive session, the SFTP subsystem (which is why the runners call
`scp -O`), command chaining and any other user than `postgres` for `sudo`.
Accepted and refused commands are logged to syslog (`LOG_AUTH`) as
`echoport-remote-command-guard`.

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
  units: [homepage.service, homepage-db-worker, marina.service]
  private_media_paths: [/home/python-podcast/site/private_media]
  path_roots:
    - {path: /home/marina/site, owner: "marina:marina"}
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
just molecule-test echoport_remote_command_guard  # real sshd, fish login shell, scp -O, rsync
```

The unit tests render each remote runner template, drive a backup and a
restore from that backup with the network faked, and require every command
the runner would send to pass the guard for its host. A runner change that
sends a new command fails there first.
