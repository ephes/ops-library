# ssh_restricted_forwarding_account

Provision a dedicated Linux account and OpenSSH policy that can make **local TCP
forwards to one destination only**. This role owns only that account's home,
`authorized_keys`, and one sshd drop-in; it never manages root's authorized keys.

## Defense in depth

The single authorized key uses `restrict`, explicitly re-enables only port forwarding,
sets one `permitopen`, and forces the configured no-login command. The sshd `Match User`
block independently enforces:

- public-key-only authentication;
- `AllowTcpForwarding local` with one `PermitOpen` destination;
- `PermitListen none`, `AllowStreamLocalForwarding no`, `PermitTunnel no`, and
  `GatewayPorts no` (no remote, Unix-socket, or tunnel-device forwarding);
- no agent or X11 forwarding, PTY, user rc, shell, exec, or subsystem session;
- `MaxSessions 0` plus `ForceCommand` as session-channel defense in depth.

Present and absent runs for one account acquire the same stable, canonical
`/run/lock` advisory transaction lock before reading transaction pre-state and retain it
through mutation, validation, reload, rollback, and cleanup. Acquisition timeout bounds
only waiting: it is not a lease. Before publishing the marker, the holder durably writes
and directory-fsyncs a canonical account-derived, root-only recovery credential under
`/var/lib`; it then writes the canonical durable **unreleased transaction marker** containing
its PID/start identity, generation, fencing token, and the credential hash. Only after both
are durable does it fsync the ephemeral `ready` entry. A holder crash or reboot can discard
`/tmp` without discarding recovery authority. Every ordinary new workflow still fails closed,
and the role's `always` path performs authenticated, directory-fsynced marker/credential
release for ordinary task failures.

Every mutation also requires a controller-provided monotonic generation and opaque fencing
token. Under the transaction lock, the holder claims the newest pair before readiness;
the role rejects lower generations or same-generation token conflicts and reattests holder
liveness, marker ownership, and fencing before and around provisioning/revocation mutations
and before successful finalization. A delayed obsolete controller therefore cannot mutate
or finalize after recovery takeover. Recovery requires the exact token matching the stable
mode-`0600` recovery credential, positive stale PID/start attestation, and a strictly higher
generation/new fencing token. Takeover durably retains old and new credentials across the
marker switch, then compacts to the new credential, so every power-loss boundary remains
recoverable. Neither elapsed time nor advisory-lock availability is enough.

The role rejects any symlink or non-file/non-directory entry in the `/etc/ssh` source tree.
It copies regular files through `O_NOFOLLOW` descriptors, rewrites `sshd_config`, and installs
the rendered drop-in through descriptor-relative, normalized candidate targets. Thus even
check mode cannot follow an absolute `sshd_config` or `sshd_config.d` symlink and mutate its
outside target. It then validates syntax and effective policy before account or key mutation.
Before mutation, the role accepts only a narrow managed pre-state: an existing home must
be account-owned mode `0700`, `.ssh` account-owned mode `0700`, `authorized_keys` an
ordinary single-link account-owned mode `0600` file, and the drop-in an ordinary
single-link `root:root` mode `0644` file. It snapshots prior passwd/shadow/group fields,
managed file bytes, and absence state. Account, key, and policy installation is one
transaction: a later write, validation, or reload failure restores managed bytes, absence
state, and canonical owner/group/modes, then validates and reloads the restored policy.
Rollback does **not** preserve or promise timestamps, ACLs, or xattrs. Snapshot and key
material is always hidden with `no_log` and disabled diffs.

A restored file is not sufficient daemon recovery. Rollback is positively attested only
when the restored reload succeeds and `sshd -T -C` output exactly matches the captured
pre-mutation effective policy. If reload or comparison fails, the role reports
`ROLLBACK INCOMPLETE`, preserves the account and managed on-disk recovery state, and does
not claim that the old key is usable. Keep clients stopped until an operator performs a
successful validated reload.

A successful present transaction also persists a canonical root-only mode-`0600` identity
contract containing the exact managed UID, GID, username/group, canonical home, and shell.
Before **any** absent-state revocation mutation, and while still holding the stable
transaction lock, the role first runs the complete direct/nested mount preflight. It then
compares live passwd and group records with the contract, requires an unambiguous primary
group, rejects processes still owned by the managed UID, and opens `/home`, the managed
home, `.ssh`, and `authorized_keys` without following links while checking canonical
ownership and modes. A mount refusal therefore precedes drop-in, authorization, passwd,
contract, home, or content mutation and preserves all of them.
Until both home and contract are durably absent, every resume also rejects a contracted UID
or GID that resolves to another name, scans the contracted UID even after username deletion,
and fails closed when any extant `/proc/<pid>/status` cannot be read. Drift, repurposing, a
missing contract for extant remnants, or a symlink fails closed with unrelated state intact.

Removal never invokes recursive `userdel`: it removes the attested account with
`remove: false`, then a descriptor-relative helper reattests and recursively unlinks only
entries beneath the pinned canonical `/home/<user>` descriptor without following symlinks.
Linux `statx` mount IDs pin `/home` first and require the canonical home itself to share that
mount before any traversal. They then preflight the complete tree before the first unlink,
distinguish same-device bind mounts from ordinary directories, and are rechecked around
traversal; a bind/tmpfs mount directly at the home and every nested mount fail closed. The group and durable
identity contract are removed last. This ordering is idempotent after partial completion and
can never select a recursive target from a drifted passwd home or recycled numeric identity.

Check mode performs candidate, mount, and absent-state identity checks without changing
account files or loading services. Because the local removal check intentionally leaves a
healthy tunnel running, contracted-UID sshd processes are reported as a deferred
post-shutdown gate rather than failing that read-only check alone. Every real absent
transaction rescans under the stable lock and still fails closed while any such process
exists. Existing deployments are idempotent. Accounts provisioned by an older role revision
must be converged once in `present` state to establish the durable identity contract before
removal is permitted.

The managed drop-in must be one immediate-child `.conf` file under exactly
`/etc/ssh/sshd_config.d`; nested paths, traversal, and dot components are rejected before
any root write or rollback read. Public key input is exactly two fields (Ed25519 type and
base64 material). Comment, optional source restriction, and shell inputs are conservative
single-line values; the shell must be one of the configured no-login executables.

The account receives a deliberately unusable but non-locked SHA-512 password hash. sshd
disables password and keyboard-interactive authentication, while the non-locked account
state keeps public-key authentication usable on PAM-disabled systems.

## Variables

| Variable | Default | Description |
| --- | --- | --- |
| `ssh_restricted_forwarding_account_enabled` | `true` | Enable account management. |
| `ssh_restricted_forwarding_account_state` | `present` | Provision or revoke/remove (`absent`) the account. |
| `ssh_restricted_forwarding_account_transaction_lock` | `/run/lock/ssh-restricted-forwarding-<user>.lock` | Stable account-derived lock shared by present and absent; overrides to another path are rejected. |
| `ssh_restricted_forwarding_account_lock_timeout` | `300` | Bounded seconds to acquire the server transaction lock; never a holder lifetime. |
| `ssh_restricted_forwarding_account_fence_generation` | `0` | Required positive monotonic workflow generation for real mutation. |
| `ssh_restricted_forwarding_account_fence_token` | `CHANGEME` | Required opaque 32–128 lowercase-hex token bound to the generation. |
| `ssh_restricted_forwarding_account_fence_path` | `/var/lib/ssh-restricted-forwarding/<user>.fence.json` | Canonical durable newest-generation state; overrides are rejected. |
| `ssh_restricted_forwarding_account_transaction_marker` | `/var/lib/ssh-restricted-forwarding/<user>.transaction.json` | Canonical durable unreleased holder marker; overrides are rejected. |
| `ssh_restricted_forwarding_account_recovery_credential_path` | `/var/lib/ssh-restricted-forwarding/<user>.recovery.json` | Canonical root-only durable recovery credential; overrides are rejected. |
| `ssh_restricted_forwarding_account_contract_path` | `/var/lib/ssh-restricted-forwarding/<user>.account.json` | Canonical root-only durable UID/GID and account-removal contract; overrides are rejected. |
| `ssh_restricted_forwarding_account_recover_stale_transaction` | `false` | Explicitly request authenticated takeover of a positively stale marker. |
| `ssh_restricted_forwarding_account_recovery_token` | empty | Required 64-hex token selected from the stable credential by matching the marker hash during recovery. |
| `ssh_restricted_forwarding_account_user` | `CHANGEME` | Dedicated system account. |
| `ssh_restricted_forwarding_account_group` | same as user | Dedicated system group. |
| `ssh_restricted_forwarding_account_home` | `/home/<user>` | Dedicated home. |
| `ssh_restricted_forwarding_account_shell` | `/usr/sbin/nologin` | Forced/no-login shell. |
| `ssh_restricted_forwarding_account_public_key` | `CHANGEME` | One Ed25519 public key. |
| `ssh_restricted_forwarding_account_key_comment` | `restricted-forwarding` | Authorized-key comment. |
| `ssh_restricted_forwarding_account_source` | empty | Optional authorized-key `from=` restriction. |
| `ssh_restricted_forwarding_account_permit_host` | `CHANGEME` | Sole permitted destination host. |
| `ssh_restricted_forwarding_account_permit_port` | `443` | Sole permitted destination port. |
| `ssh_restricted_forwarding_account_sshd_dropin` | account-specific file under `sshd_config.d` | Owned Match policy. |
| `ssh_restricted_forwarding_account_sshd_binary` | `/usr/sbin/sshd` | sshd used for validation. |
| `ssh_restricted_forwarding_account_ssh_service` | `ssh` | Service reloaded after validation. |
| `ssh_restricted_forwarding_account_reload_command` | `[]` | Optional explicit reload argv for controlled harnesses; production normally uses the service. |

## Example

```yaml
- name: Provision a one-destination forwarding account
  hosts: relay
  become: true
  roles:
    - role: local.ops_library.ssh_restricted_forwarding_account
      vars:
        ssh_restricted_forwarding_account_user: app_forward
        ssh_restricted_forwarding_account_public_key: "{{ hostvars['localhost'].ssh_forwarding_identity_public_key }}"
        ssh_restricted_forwarding_account_permit_host: private-git.example.net
        ssh_restricted_forwarding_account_permit_port: 443
        ssh_restricted_forwarding_account_fence_generation: 42
        ssh_restricted_forwarding_account_fence_token: "{{ lifecycle_fencing_token }}"
```

## Lifecycle

For rotation, add/provision the replacement client identity first, then update this role's
single key and prove key authentication plus permitted forwarding before removing the old
private key. If candidate validation fails, no account/key mutation occurs. If a later
validation or reload fails, managed prior bytes, absence state, and canonical metadata are
restored. Continue using the prior private key only when the error says rollback activation
was attested. `ROLLBACK INCOMPLETE` means old-key usability is unknown until a successful
validated recovery reload.

For removal, stop every client first and set
`ssh_restricted_forwarding_account_state: absent`. The role removes the drop-in, validates
the complete sshd configuration, reloads SSH, and only then deletes the account without
recursive home removal, descriptor-removes only the pre-attested canonical home, and removes
the group/contract last. Any account, group, shell, UID/GID, home, ownership, mode, symlink,
recycled numeric identity, live/unreadable process ownership, separately mounted canonical
home, or nested mount drift fails closed; all mounted data is preserved before recursive
deletion starts.
A validation or reload failure restores the prior policy and preserves the account.
Remove the local private key last with the identity role's explicit confirmation gate. Do
not repurpose or merge this account with operator/root access.

A hard controller kill may bypass Ansible's `always` tasks. From a separate root session,
inspect the durable marker and account-derived mode-`0600` recovery credential. If the exact
recorded holder PID/start identity is still alive and no account module remains, an existing
ephemeral `ready` file may be copied to `release`; the live holder authenticates the token,
removes marker and credential durably, and exits. Loss of that `/tmp` directory is not loss
of recovery authority, but a live holder must exit before stale recovery can proceed.

If the holder is dead, **do not** write `release`: privately select from the stable
credential the token whose SHA-256 equals the marker hash, supply it through the recovery
variable, set `ssh_restricted_forwarding_account_recover_stale_transaction: true`, and rerun
with a strictly higher generation/new fencing token. The new holder authenticates both
stable credential and marker, positively attests the old holder is stale, advances fencing,
and replaces credential/marker before readiness. Never delete or edit the lock, marker,
fence, credential, or ready file manually. If stale ownership cannot be attested, preserve
all state and investigate.
