# journald_config

Configure systemd-journald storage, size and retention limits through one
managed drop-in, `/etc/systemd/journald.conf.d/60-ops-library.conf`.

The role declares Ubuntu 24.04 and Debian 12/13 support.

## Why a host can keep far less than its size limit

journald deletes archived journal files when **any** of these limits is hit,
whichever comes first:

- `SystemMaxUse=` – total size (default 10% of the file system, capped at 4G)
- `SystemMaxFiles=` – number of files (default **100**)
- `MaxRetentionSec=` – age (default off)

The file-count limit is the one that surprises. journald keeps a separate
journal per regular user UID (`SplitMode=uid`; system and dynamic users log to
the system journal), and every rotation archives the system journal **and**
every per-UID journal at once. A host whose eight service accounts have regular
UIDs (1000 and up) archives nine files per rotation, so the default of 100
holds only about eleven rotations.

Rotation itself is not only size-driven. Each file gets a data hash table
sized from `SystemMaxFileSize=` (default 1/8 of `SystemMaxUse`, capped at
128M), and journald rotates once that table is 75% full. Logs with many
distinct values (access logs, IDs, timestamps in the message) fill it long
before the file reaches its size limit. `journalctl --header --file <file>`
shows `Data hash table fill: 75.0%` on files rotated for that reason.

Together that can cap retention at a day while `journalctl --disk-usage` shows
a fraction of `SystemMaxUse` in use. To keep a given number of days, size all
three limits from the measured daily volume:

1. **Daily volume:** `journalctl --disk-usage` divided by the time between the
   oldest entry (`journalctl -o short-iso | head -1`) and now.
2. **`SystemMaxUse`:** daily volume × wanted days, plus headroom, and check
   that the file system can spare it.
3. **`SystemMaxFiles`:** rotations per day × (1 + number of per-UID journals)
   × wanted days, with margin. Count the per-UID journals with
   `ls /var/log/journal/*/ | sed -E 's/[@.].*//' | sort -u`.
4. **`SystemMaxFileSize`:** a larger value gives a larger hash table and so
   fewer rotations and fewer files. Disk usage stays about the same, because
   each per-UID file preallocates a proportionally larger table.
5. **`MaxRetentionSec`:** an upper bound, so a quieter host does not keep
   logs much longer than intended. journald deletes an archived file once its
   *first* entry is older than this, so the oldest kept entry can be up to one
   file's time span younger than the limit; it is not a minimum.

## Variables

| Variable | Default | journald key |
|---|---|---|
| `journald_config_state` | `present` | `absent` removes the drop-in and restarts journald, returning to the distribution defaults. |
| `journald_config_dropin_path` | `/etc/systemd/journald.conf.d/60-ops-library.conf` | Must be a `*.conf` file directly in `/etc/systemd/journald.conf.d/`. |
| `journald_config_storage` | `persistent` | `Storage=` (`persistent`, `volatile`, `auto`, `none`; empty leaves the default `auto`) |
| `journald_config_system_max_use` | `""` | `SystemMaxUse=` |
| `journald_config_system_keep_free` | `""` | `SystemKeepFree=` |
| `journald_config_system_max_file_size` | `""` | `SystemMaxFileSize=` |
| `journald_config_system_max_files` | `""` | `SystemMaxFiles=` |
| `journald_config_max_retention_sec` | `""` | `MaxRetentionSec=` |
| `journald_config_max_file_sec` | `""` | `MaxFileSec=` |
| `journald_config_extra_settings` | `{}` | Further `[Journal]` keys, e.g. `{Compress: true}`. Booleans render as `yes`/`no`. Values must be single-line: control characters (CR, LF, NUL, ...) are rejected, since systemd would treat them as line breaks. |
| `journald_config_restart_on_change` | `true` | Restart `systemd-journald` when the drop-in changes. |

An empty string leaves the systemd default in place and writes nothing for
that key. Sizes take a `K`/`M`/`G`/`T`/`P`/`E` suffix (base 1024, e.g.
`16G` or `1.5G`); time spans use systemd syntax (`21day`, `1.5day`, `3week`,
`1month`). `SystemMaxFiles=0` disables the file-count limit. The role
rejects malformed values, and an extra setting whose key one of the
first-class variables already covers, before it writes anything.

## Applying a change

journald has no configuration reload, so the role restarts
`systemd-journald` when the drop-in changes. Services keep their
stdout/stderr streams through journald's file descriptor store; Ubuntu's own
package upgrades restart journald the same way.

With `Storage=persistent` the role then runs `journalctl --flush`. A restart
alone does not move a journal that was in `/run` (previously `volatile`, or
`auto` without `/var/log/journal`) to disk; the flush does, and on a host that
already writes to `/var/log/journal` it is a no-op.

Raising limits takes effect immediately: journald simply stops deleting files
it would have deleted. Lowering them deletes archived files at the restart or the next rotation.

## Example

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.journald_config
      vars:
        journald_config_system_max_use: "16G"
        journald_config_system_max_file_size: "512M"
        journald_config_system_max_files: 2000
        journald_config_max_retention_sec: "21day"
```

Rendered drop-in:

```ini
[Journal]
Storage=persistent
SystemMaxUse=16G
SystemMaxFileSize=512M
SystemMaxFiles=2000
MaxRetentionSec=21day
```

## Verify

```bash
systemd-analyze cat-config systemd/journald.conf   # drop-in is listed last
journalctl -u systemd-journald -n 5                 # "System Journal (...) is X, max 16.0G, ..."
journalctl --disk-usage
journalctl -o short-iso | head -1                   # oldest entry still available
```

## Testing

```bash
just molecule-test journald_config
```

The scenario applies the role in a systemd container, checks the rendered
drop-in and `systemd-analyze cat-config`, checks that malformed and
conflicting values are rejected without touching the file, and removes the
drop-in again with `journald_config_state: absent`.
