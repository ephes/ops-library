# macos_python_ca_remediate

Patch already-installed certifi in an explicit nonempty list of macOS virtual
environments. Each `macos_python_ca_environments` item supplies `path`, `owner`,
and optionally a deployed `lockfile`. Run through Ansible privilege escalation
as that environment’s owner. Requires Homebrew Python>=3.11 and uv>=0.13.4.

The fixed certifi 2026.10.19 wheel uses the upstream PyPI SHA-256, no dependency
resolution, no tool/application upgrades and no package insertion when certifi
is absent. Newer versions remain. Installed pip/sigstore are boundedly checked
against 26.2.2 / 4.5.1; an old copy fails for explicit remediation rather than
silently adding/upgrading other packages. The observed target Mac environments
have neither pip nor sigstore installed.

For a service whose uv launch syncs its deployed lock, `lockfile` replaces only
the existing public-registry certifi package record, preserving all other parsed
lock data and source bytes outside that record. The owner must be able to write
that lock. Original-version receipts and optional lock backup are 0600 under
`~/.local/state/managed-python-ca`. No secrets/environment dumps are recorded.
The installed own certifi bundle must contain neither affected root. Check mode
only inspects and reports proposed changes. Existing long-running consumers
need separate idle-safe restarts and health/TLS checks; this role does not restart.

Source locks still need the same update in their owning repository. Rollback
from receipts/lock backups restores vulnerable trust and requires assessment.

The role probes only native platform and effective account metadata; it does not require gathered Ansible facts. With ansible-core 2.20 on macOS, use Python 3.14 as the module interpreter and disable broad fact gathering. The native helper may use Homebrew Python 3.15 because it uses only the standard library.

Environment helpers run from `/` so changing from a root SSH session to the explicit environment owner does not inherit an unreadable root home directory. All target paths remain explicit and absolute.
