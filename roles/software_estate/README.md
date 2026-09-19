# software_estate

Installs a read-only software discovery program and, optionally, a pinned Syft
scanner. It does not enable scheduling, install application updates, refresh APT,
pull images or restart observed services. The stdlib collector can also be streamed
over SSH without deploying this role.

## Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `software_estate_install_dir` | `/usr/local/lib/software-estate` | Dedicated fixed program directory |
| `software_estate_install_syft` | `false` | Install optional scanner; Linux x86_64 only |
| `software_estate_syft_version` | `1.52.0` | Fixed supported scanner release; the adapter and tests must be updated before changing it |
| `software_estate_syft_sha256` | See defaults | Verified Linux x86_64 release archive checksum; checksum for the fixed supported release |

## Example

```yaml
- name: Install software observation tools
  hosts: application_servers
  become: true
  roles:
    - role: local.ops_library.software_estate
      software_estate_install_syft: true
```

Invoke `collect.py --policy-json '{"host":"example","applications":[]}'` using
Python 3.9+ (3.11+ recommended). Output collector schema 2 contains timestamped category
results and explicit gaps. Linux requires dpkg/systemd tools. Docker is queried
only if installed. macOS uses Homebrew/Cellar metadata, launchctl and application
bundle plists; launchctl is scoped to the invoking user's bootstrap context.

Application policy requires a non-empty, unique stable `id`. Optional probes use a
fixed service `unit`, package names with a `primary_package`, registered absolute
Git `path` or Python `venv`, or the dedicated `navidrome` version probe.
Package probes with missing host package evidence or an unresolved primary package
report coverage gaps, which fail the pilot applications category. The navidrome probe trusts only
its fixed root-owned non-writable binary and pins its inode during execution.
No arbitrary executable/command field is supported. Applications with different
layouts need explicit adapters rather than executing untrusted discovered code.

The collector returns no Docker environment or service command lines. Unit names
can still contain runtime instance identifiers, paths and addresses; observations
belong in a private inventory. Git dirty
state exposes no changed filenames. Installed package metadata does not establish
optional dependency activation or a complete dependency graph. Categories that
cannot be read return errors; callers must not turn those into healthy empty lists.

Category status is `ok`, `unsupported` (tool unavailable), or `error`; an empty
unsupported category never proves software absence. `application_bundles` contains
macOS bundles; top-level `applications` contains registered application probes.
`kernel_release` is separate from `os_release` (Linux release fields) and nullable
`os_version` (distro version or macOS version). Missing Linux release metadata adds
a gap without discarding other observations. Collector schema 2 rejects cached
schema-1 observations at the controller; refresh after upgrading.

Syft scans must explicitly select local images/directories and constrain scan roots.
Python scan roots must resolve to a named environment at least two path segments
below root and contain `pyvenv.cfg`; top-level directories are rejected.
This role installs the scanner but does not scan automatically. Use the controller
policy to define and verify exact scan targets and persist SBOM provenance.

## Validation and removal

Run `just test-software-estate`, required repository checks and live observation
verification. `software_estate_remove` removes only this role's program directory
and bundled scanner. Caller-owned evidence is retained; existing software health
collectors and applications are not affected.

## Local push pilot helpers (source-run, not installed automatically)

`files/emit.py --policy HOST.json --spool /private/path/outbox` runs one local scan
and writes an immutable schema-1 JSON report for the Graphyard inventory pilot.
It performs no network transfer. The directory must be owned by the caller and
mode 0700; files are mode 0600. Reports are limited to 8 MiB and the pilot stops
at 32 outbox entries rather than deleting unconfirmed data. This deliberately
requires manual delivery reconciliation; it is not an unattended lifecycle.

`files/vector_inventory_config.py --spool /absolute/outbox --data-dir /absolute/data
--endpoint https://receiver.example/v1/inventory --output /private/vector.json`
generates a separate pipeline. Its directory secret backend reads the credential
from `<data-dir>-secrets/writer`, computed after resolving the data directory
(including symlinks), stripping trailing whitespace. Create the secrets
directory with mode 0700 and store the issued host credential in `writer` with
mode 0600. The rendered config contains only `SECRET[inventory_writer.writer]`;
missing/empty secrets prevent Vector startup. This works with Vector 0.58 without
enabling environment interpolation (disabled by default since 0.57). See the
[Vector secrets reference](https://vector.dev/docs/reference/configuration/secrets/).
To migrate an existing pilot, stop its separate Vector process, move the old config
to a private backup filename, provision the secret directory/file above, and generate
a new config at the original output path. Retain the existing outbox and buffer data.
For an isolated diagnostic run use `vector --config /private/vector.json`.
Vector 0.58 on macOS intermittently stalls low-traffic reports; one worker also
failed a later repetition and is not a reliable workaround. The real Graphyard
probe detects this unresolved transport blocker. Do not enable unattended inventory
shipping until it is resolved. Exporting the old environment variable no longer
supplies authentication. The generator
refuses to overwrite an existing config or use non-TLS remote endpoints. Local
loopback HTTP is allowed only for tests. Parsing failures route to a private
`invalid.ndjson` file. Monitor Vector's own errors for permanent HTTP rejection.

Secrets live next to the Vector data directory, so copying/resetting buffer state
does not include/remove credentials. Existing secret paths must be caller-owned,
owner-only and not symlinks; the generator rejects violations. If credentials are
provisioned after generation, the operator must enforce those permissions then.
Generation does not certify later changes to the filesystem. `vector validate
--no-environment` does not check secret availability; actual startup does.

Create the data directory with mode 0700 and run this pipeline as the same
unprivileged user that owns the outbox. The installed system Vector service is
not modified. The existing deployment role still installs only the original
observation/SBOM tools. These pilot helpers are invoked from the source checkout.
No scheduler, SSH credentials, or receiving service is provisioned.

Application probe failure currently marks the entire applications category as
failed, preserving the receiver's last successful category. This includes nested
Git/Python probe failures and version-probe coverage gaps. macOS application
bundle observations are included in that category. Host OS metadata is not part
of this pilot envelope and is explicitly listed as a coverage gap. Installed
Python dependency metadata remains within application observations.

Before rollout, verify real HTTP retry and disk-buffer recovery, credential
revocation, source retention, service lifecycle and private receiving endpoint.
Spool and Vector data directories must not overlap, preventing failed-record
output from being ingested as new inventory. File-only tests are not evidence of HTTP delivery. The target Python floor for
both helpers is 3.10. Run `just test-software-estate` for offline regression tests.
