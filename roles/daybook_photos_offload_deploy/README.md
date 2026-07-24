# daybook_photos_offload_deploy

Install Daybook's read-only Apple Photos offload reconciler as a macOS user
LaunchAgent. The role materializes a separate clean Daybook checkout pinned to
an exact 40-character commit, synchronizes a checkout-local frozen runtime in
an empty environment, and schedules aggregate discovery reconciliation at
08:10 and 20:10 local time.

The controller must provide
`daybook_photos_offload_repo_bundle_src`. The role installs that bundle as an
ACL-free root-owned mode-0600 file inside the protected checkout parent and
uses its fixed remote path as `daybook_photos_offload_repo_url`. Whitespace-safe
sanitized Git commands clone or fetch that bundle directly and preserve its raw
path as the exact admitted origin; check mode never probes the bundle. Bundle
preparation may use an isolated synthetic `main` ref for the exact reviewed
commit, so deployment does not depend on the controller's moving branch head.
replacement happens only after quiescence and full ancestor/path validation.

The default is deliberately disabled:

```yaml
daybook_photos_offload_launchd_enabled: false
```

Every role run first probes the user's GUI domain, then disables and unloads
the exact service before changing the checkout, environment, launcher, or
plist. The initial probe is nonfatal so both quiescence operations are
still attempted; the role then requires a healthy GUI domain, a successful
persistent-state query, the exact label's disabled state (supporting macOS's
`disabled` spelling and the legacy boolean spelling), and launchd's exact
absent-service result. It remains quiesced on a failed install. A separate reviewed
control-repository action must set
`daybook_photos_offload_launchd_enabled: true`; only after every deployment
check succeeds does that action enable and bootstrap the agent. The role never
kicks the job, writes to Apple Photos, mounts or writes Fractal, renders
replacements, or removes media.

## Managed paths

- `~/.config/daybook-photos-offload/reconcile.sh` (mode 0700)
- `/Library/Application Support/Daybook/photos-offload/daybook` (a separate
  exact, root-owned clean checkout under a root-owned parent so the service
  user cannot replace source, Git metadata, or the `.venv` pathname; only
  `.venv` contents are service-user writable; every ancestor is protected,
  and no privileged operation traverses `.venv` contents)
- `~/.daybook/photos-offload/` and `ledger.json` (directory 0700; Daybook
  creates ledger/lock files at 0600; the role removes inherited directory ACLs
  and Daybook rejects extended ACLs on all private state files)
- `~/.daybook/photos-offload/logs/` (directory 0700 and log files 0600,
  created, ACL-cleaned, and owned entirely by the service user so deployment
  never uses root authority on user-writable log paths)
- `~/Library/LaunchAgents/de.wersdoerfer.daybook.photos-offload.plist`

The private directories, LaunchAgents directory, launcher, plist, and log
files are all ACL-cleaned and verified before activation. Home-directory
paths are created and rendered only as the service user.

The launcher verifies the exact clean commit and real checkout-local
environment on every run, then invokes
`daybook photos offload-reconcile --summary-only` with uv configuration and
environment inheritance disabled. `uv run --frozen` verifies/synchronizes the
dedicated environment against the pinned lock before execution. All launcher,
Git, uv, and Daybook diagnostics are suppressed; a failed run emits one stable
generic error. Scheduled output therefore contains only status,
`state_changed`, and aggregate counts, or that generic failure—no Photos UUIDs,
proposal ids, filenames, or paths. The owner-only ledger retains the detailed
identities required by later reviewed slices.

The role requires `daybook_photos_offload_launchd_manage_state: true`; this
safety-critical deployment cannot bypass quiescence. It rejects traversal,
existing symlink path components, and substituted managed files before writing.
It also verifies canonical directories, exact file ownership/modes, and
single-link regular files before launchd can load the agent. Existing checkouts
must have a protected root-owned in-tree `.git` directory, exact canonical
root, the role's root-only trust attestation, protected ACL-free descendants,
clean status, safe index flags, an allowlisted local Git configuration,
independently matching tracked content, no hard-linked protected files, no
ignored content outside `.venv`, and the intended origin before Git may update
them. Unattested pre-existing checkouts fail closed rather than being hardened
with privileged recursion. Git hooks, includes, fsmonitor, global/system
configuration, external diff/text conversion, and prompting are disabled.
The root trust attestation is admitted before writing and reverified afterward
for exact content, ownership, mode, link count, and absence of ACLs.
Checkout and `.venv` paths are checked again after Git and before uv can mutate
the environment. Read-only
identity, git, and launchctl probes
execute in Ansible check mode when their targets exist; managed file and
directory writes remain skipped, so a first-run check does not depend on
simulated parent creation.

Activation is guarded by a fail-closed Ansible block. If enable, bootstrap, or
the final state checks fail, its rescue disables and boots out the exact
service independently even if either command fails, verifies that it is
quiesced, and then reports the failed activation. Initial quiescence uses the
same attempt-both-then-verify ordering.

Because Photos access and later PhotoKit/TCC work belong to the logged-in user,
this is an Aqua user LaunchAgent, not a system LaunchDaemon. Deployment requires
that user's GUI launchd domain to exist.

## Example

```yaml
- name: Install disabled Photos offload discovery on Studio
  hosts: macstudio
  become: true
  roles:
    - role: local.ops_library.daybook_photos_offload_deploy
      vars:
        daybook_photos_offload_service_user: jochen
        daybook_photos_offload_repo_ref: "0123456789abcdef0123456789abcdef01234567"
        daybook_photos_offload_launchd_enabled: false
```
