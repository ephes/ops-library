# rust_release_binary (internal helper)

Installs, pins and prunes pinned release binaries of the Rust crates under
`rust/` (`metrics-httpd`, `echoport-command-guard`, `software-live`), as
published by `rust-release.yml` at
`https://github.com/ephes/ops-library/releases/tag/<crate>-v<version>`. It is
slice F3 of [`rust/PLAN-foundation.md`](../../rust/PLAN-foundation.md)
(sections 6.1 and 6.2), generalised from `mailgun_relay_deploy`'s
`tasks/rust.yml`. It is an internal helper, not a public entry point: a
consumer role includes one of its task files.

```yaml
- name: Install the pinned metrics-httpd release
  ansible.builtin.include_role:
    name: local.ops_library.rust_release_binary
    tasks_from: install          # or pin, prune
  vars:
    rust_release_binary_name: metrics-httpd
    rust_release_binary_version: "{{ backup_metrics_endpoint_rust_version }}"
    rust_release_binary_sha256: "{{ backup_metrics_endpoint_rust_sha256 }}"
    rust_release_binary_validate_user: backup-metrics
    rust_release_binary_fail_hard: "{{ backup_metrics_endpoint_impl == 'rust' }}"
```

Including the role without `tasks_from` fails. The helper targets Linux with
GNU coreutils and GNU or BSD tar; it handles no secrets and sets no task
`environment:`.

## On-host layout

```
<root>/<version>/<name>               root:root 0755, never modified in place
<root>/<version>/LICENSE              root:root 0644 (and any other member)
<root>/<version>/.archive-sha256      root:root 0644, "<sha256 of the archive>\n"
<root>/.pins/<consumer>               root:root 0644, "<version>\n": the version the consumer runs, verified live
<root>/.pins/<consumer>.previous      root:root 0644, "<version>\n": the version it ran (verified) before that
<root>/.staging-<version>/            transient, removed on success and on failure
```

`<root>` is `rust_release_binary_install_root` (default `/opt/<name>`).
Several consumers share one root; each owns its two pin files. The pyinfra
helper of ops-deploy (F4) writes the same files with the same bytes.

A **version** is `MAJOR.MINOR.PATCH` with an optional pre-release
(`1.2.3-rc.1`), no build metadata, no leading zeros: the grammar of the tag
`<crate>-v<version>`. Only directories with such names are ever pruned. A
**consumer** name has lower-case letters, digits, `-` and `_` and no dot, so
`<consumer>.previous` never collides with another consumer's pin.

## `tasks_from: install`

1. Validates the inputs (inside the guarded block, so without `fail_hard` even
   invalid inputs only warn).
2. If `<root>/<version>` exists, it must be a plain directory whose
   `.archive-sha256` equals the pinned archive's sha256; a different archive
   for an installed version is refused (an installed version is never
   replaced in place).
3. Otherwise, outside check mode: download `release_url` with `get_url` and
   `checksum: sha256:<sha256>` (or copy `local_archive`, whose sha256 is
   checked on the controller first and must equal `sha256` when that is
   set) into `<root>/.staging-<version>/`; list the archive and require
   exactly the regular files of `members` at its root, once each (no links,
   devices, directories or nested paths); unpack with `tar --no-same-owner`;
   set owner/group and modes (`executables` 0755, the rest 0644); record
   `.archive-sha256`; `mv --no-target-directory` the tree into place; remove
   the staging directory.
4. Runs `<root>/<version>/<name> --version` as `validate_user` and requires
   the first line to start with `<name> <version> (` (the release smoke
   format `<name> <version> (<commit>)`). In check mode an installed version
   is still validated; a version that is not installed yet is not.
5. Sets `rust_release_binary_path` (`<root>/<version>/<name>`) and
   `rust_release_binary_failed: false`.

On any failure the `rescue` removes the version directory if this run created
it (never one that existed before), removes the staging directory, sets
`rust_release_binary_failed: true`, `rust_release_binary_path: ""` and adds
`<name>` to `rust_release_binary_failed_names` (sticky for the rest of the
playbook run), then either fails (`fail_hard: true`) or warns with an ignored
failed task (`ignored=1` in the recap) and lets the play continue. Install
never moves a pin and never deletes another version.

## `tasks_from: pin`

Run it only after the consumer verified that its unit (or other entry point)
really runs the version, e.g. `readlink /proc/<MainPID>/exe` equals
`rust_release_binary_path`, or the forced command in `authorized_keys` was
written and probed.

| Call | Current pin | Previous pin |
| --- | --- | --- |
| `state: present`, `version: V`, current pin is `C ≠ V` | `V` | `C` |
| `state: present`, `version: V`, current pin is `V` | unchanged | unchanged (no change reported) |
| `state: present`, `version: V`, no current pin | `V` | unchanged |
| `state: absent`, current pin `C` (switch back to Python) | removed | `C` (`keep_previous: false`: removed) |
| `state: absent`, no current pin | — | unchanged (`keep_previous: false`: removed) |

`previous: P` replaces the automatic choice of the previous pin (ignored when
`P` equals the new current version); a consumer that knows the version that
ran before from its live state, but has no current pin yet, passes it. The
previous pin is written before the current pin changes, so a version that ran
is never unpinned in between. `state: present` requires
`<root>/<version>/<name>` to be installed (not checked in check mode). An
existing pin file that is not a regular file or does not hold exactly one
version fails the task and changes nothing. Sets `rust_release_binary_pins`
(`{current, previous}`).

Example (the owner's sequence of 2026-10-21): v1 live (pin v1); switch to v2 →
current v2, previous v1; roll back to v1 → current v1, previous v2; switch to
v3 → current v3, previous v1. The version a Rust-to-Rust rollback returns to is
always pinned and therefore installed, independent of `keep_versions` and of
the order of installs.

## `tasks_from: prune`

Keeps

- the `keep_versions` newest version directories by mtime (ties by version
  name, descending),
- every version named by any file in `<root>/.pins/` (every consumer's
  current **and** previous pin),
- every version in `protect`,

and removes the other version directories. Symlinks, hidden entries
(`.pins`, `.staging-*`) and directories not named like a version are never
touched.

`protect` is filled by the consumer from the **live state**, so a version that
something still runs survives even when no pin names it (a drop-in or forced
command left by a play whose verification failed, a hand edit, lost pin
files). Each entry is either

- a version (`1.2.0`), or
- an absolute executable path as the live state shows it: an `ExecStart=`
  path, a forced command's path, or `readlink /proc/<pid>/exe` of a running
  process, including the executables of a still-running **oneshot** run (a
  collector that still executes vN after its unit and pins moved on; read all
  PIDs of the unit's cgroup) and its helper children. A trailing
  ` (deleted)` is accepted. `<root>/<version>/<file>` and the same path below
  the resolved root (`realpath <root>`, as `/proc` prints it) protect
  `<version>`; a path elsewhere (e.g. `/usr/bin/python3`) protects nothing.

**Fail closed.** Nothing is deleted, with an ignored warning task (`ignored=1`)
instead of a failure, when

- the consumer sets `live_state_unknown: true` (it could not read a drop-in,
  a unit, a cgroup or an executable it needs),
- an install of this crate failed earlier in this playbook run
  (`rust_release_binary_failed_names`),
- a `protect` entry is neither a version nor an absolute path, is not
  normalised (`//`, `.`, `..`), lies under the root but not as
  `<version>/<file>`, or names the binary `<name>` outside both spellings of
  the root (an alias the role cannot map),
- `.pins` is not a directory, or an entry in it is not a regular file or does
  not hold exactly one version.

In check mode nothing is deleted (the removal tasks report what they would
do). Sets `rust_release_binary_prune` (`{skipped: [reasons], versions, keep,
removed}`).

A consumer prunes only at the end of a successful, verified deploy, after
`pin`. A play that stops earlier (failed install with `fail_hard`, failed
verification) never reaches prune; a failure the consumer rescues itself must
be passed as `live_state_unknown: true` or prune must not be included.

## Variables

| Variable | Default | Used by | Meaning |
| --- | --- | --- | --- |
| `rust_release_binary_name` | `""` | all | Crate name = binary name = tag prefix. |
| `rust_release_binary_install_root` | `/opt/<name>` | all | Root of the layout above (normalised absolute path). |
| `rust_release_binary_owner` / `rust_release_binary_group` | `root` / `root` | all | Owner of everything the role creates. Only the localhost tests change it. |
| `rust_release_binary_version` | `""` | install, pin | Version to install / pin. |
| `rust_release_binary_sha256` | `""` | install | sha256 of the release archive (64 lowercase hex). Required unless `local_archive` is set. |
| `rust_release_binary_release_url` | `https://github.com/ephes/ops-library/releases/download/<name>-v<version>/<name>-<version>-x86_64-unknown-linux-gnu.tar.gz` | install | Download URL (`https://`, or `file://` for tests). A variant archive (`…-<variant>.tar.gz`, foundation section 4) is passed here. |
| `rust_release_binary_local_archive` | `""` | install | Controller path of an archive with the same layout (development, tests); replaces the download. |
| `rust_release_binary_members` | `[]` → `[<name>, LICENSE]` | install | Exactly the regular files the archive holds at its root, e.g. `[software-live, software-live-apt, LICENSE, LICENSE-software-live-apt]`. |
| `rust_release_binary_executables` | `[]` → `[<name>]` | install | Members installed 0755 (must include `<name>`); the others 0644. |
| `rust_release_binary_validate_user` | `nobody` | install | User that runs `--version` (become). Empty: the connection user, no become (localhost tests only). |
| `rust_release_binary_fail_hard` | `true` | install | `false`: a failure warns and sets `rust_release_binary_failed` instead of stopping the play (the consumer's Python rollback is never blocked). |
| `rust_release_binary_consumer` | `""` | pin | Pin file name. |
| `rust_release_binary_state` | `present` | pin | `present` pins `version`; `absent` removes the current pin. |
| `rust_release_binary_previous` | `""` | pin | Explicit previous pin (see above). |
| `rust_release_binary_keep_previous` | `true` | pin | With `state: absent`, keep the removed version as the previous pin. |
| `rust_release_binary_keep_versions` | `3` | prune | Newest version directories kept on top of pins and `protect` (≥ 1). |
| `rust_release_binary_protect` | `[]` | prune | Versions or executable paths from the live state. |
| `rust_release_binary_live_state_unknown` | `false` | prune | `true`: delete nothing. |

Facts set: `rust_release_binary_path`, `rust_release_binary_failed`,
`rust_release_binary_failed_names` (install), `rust_release_binary_pins` (pin),
`rust_release_binary_prune` (prune).

The decisions (pin moves, prune plan, the version and consumer grammar) are
the filters in `plugins/filter/rust_release.py`
(`local.ops_library.rust_release_pin_plan`, `rust_release_prune_plan`,
`rust_release_pin_records`, `rust_release_pin_content`,
`rust_release_version_ok`, `rust_release_consumer_ok`).

## Tests

`just test-rust-release-binary` (part of `just test`) runs
`tests/test_rust_release_binary.py`: static checks of the task files, unit
tests of the filters, and `ansible-playbook` runs against localhost with fake
release archives in a temporary root: install, idempotent re-run, extra
members, download with checksum, different-archive refusal, member refusals,
the warn-and-continue path, check mode, pin moves, prune with pins of two
consumers and `protect`, the rollback sequence v1 → v2 → v1 → v3 → v4,
repeated failed deploys with different targets, the executables of a running
oneshot run under a symlinked root, and the fail-closed cases. On macOS the
playbook runs need Homebrew coreutils (`gmv`).

The existing `mailgun_relay_deploy` and `nyxmon_deploy` roles keep their own
install code (foundation 6.2, non-goal).
