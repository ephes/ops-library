# ssh_forwarding_identity

Create an unattended Ed25519 identity for a dedicated SSH forwarding client without
implicitly rotating an existing private key.

## Behavior

- Traverses every ancestor from `/` through the identity parent with directory
  descriptors and component-relative opens using `O_NOFOLLOW|O_DIRECTORY`. This rejects
  symlinks above the configured home as well as below it, non-directories, traversal, and
  escape without relying on full-path `lstat(2)`.
- Creates missing components only at/below the configured home through the pinned parent
  descriptor, attests ownership/mode there, and keeps all key install/reconcile/removal
  operations descriptor-relative. Renaming the parent and substituting a symlink during
  generation therefore cannot redirect writes, chmod, chown, or rename to its target.
- Generates an Ed25519 key with an empty passphrase only when the private key is absent.
  First creation writes through an exclusive random name beneath the pinned parent, using
  an EINTR-aware write-all loop. It fsyncs and read-verifies the complete bytes, re-derives
  the Ed25519 public material, durably binds that staging inode in an owner-only intent,
  then descriptor-relatively renames the canonical private name without replacement and
  fsyncs the parent. The intent itself uses the same exclusive-rename publication, so no
  crash window leaves either canonical state with link count two.
- Reconciles a crash-stranded bound staging inode on restart only after exact
  identity/content/key validation. Present-state check mode performs the same recovery
  inspection and derives the prospective public key, but never publishes staging, updates or
  clears intent, quarantines a name, or fsyncs a state transition. An unbound or replaced
  staging entry and a partial or unrelated canonical key are preserved fail closed; cleanup
  never relies on owner/mode, filename shape, or partial content alone.
- Opens every canonical private/public key, creation intent, and recovery staging entry with
  `O_NONBLOCK|O_CLOEXEC|O_NOFOLLOW`; immediately requires a regular single-link inode with
  the exact owner and expected `0600`/`0644` mode, pins descriptor/path identity before and
  after bounded reading, and therefore rejects FIFOs, sockets, devices, directories,
  symlinks, hard links, and replacements without blocking. A creation intent whose
  `identity` is still null authorizes only the snapshot where both its named staging entry
  and the canonical private-key entry are absent. Either entry—or both, regardless of
  whether their bytes match—is ambiguous evidence: check and real mode preserve the full
  snapshot, derive or publish no key, and fail closed. When both are absent, a real restart
  keeps that exact null-intent binding as its authority instead of clearing it: the helper
  reattests intent plus both companion names before staging allocation, after allocation
  durability, after binding, after canonical publication, and after every retirement fsync.
  Check mode reattests the same snapshot immediately before returning its plan.
- Refuses wrong ownership, an orphan `.pub` file, and a passphrase-protected or non-Ed25519
  existing key.
- Enforces private key mode `0600`, derives/reconciles the public key, and exposes only
  the public material as `ssh_forwarding_identity_public_key` for later plays. Public-key
  and creation-intent writes keep the prepared descriptor and exact bytes authoritative
  through publication and old-name retirement. New canonical names use exclusive rename;
  updates require the exact previously returned inode/byte binding, atomically exchange
  names, and return the replacement binding. Creation reconciliation carries that original
  binding through every update and clear rather than fresh-reading another valid intent.
  A restarted creation updates from that original exact binding only after pinning its new
  staging inode, so no clear-and-recreate interval leaves creation unowned. Intent retirement
  keeps the canonical private descriptor identity and staging absence authoritative at every
  fsync. After cleanup's final directory fsync, the helper again verifies the publication
  descriptor, canonical identity, and exact bytes, preserving substitution at update,
  clear, or retirement instead of accepting or overwriting it.
- Runs key inspection in an empty environment, without Keychain or `SSH_AUTH_SOCK`.
- Marks key-handling tasks `no_log`; the private key remains outside the repository.

The role never rotates or removes a private key implicitly. Cleanup records include
nanosecond change time and keep a no-follow descriptor pinned while the exact validated
source is moved exclusively to a fresh private quarantine, fsynced, and reattested. The
original canonical name must remain absent immediately after rename and after every parent
fsync; any recreation is preserved and fails the operation. A precreated target or
post-verification swap is likewise preserved and rejected. Because neither
supported platform provides a portable pathname-free unlink for that open inode,
authenticated quarantines are retained rather than risking verify-then-pathname deletion.
Controlled zero-progress, partial-write, or `ENOSPC` failures before publication leave no
canonical key. A failure after exclusive canonical publication remains
recoverable from the durable intent and cannot replace an existing key. Rotation is an
explicit operator action: provision a new path/key, authorize it server-side, and move
clients. Explicit confirmed `state: absent` removes the old public and private canonical names into
authenticated private quarantines. Cleanup authority is the exact full inode identity returned
with the validated bytes by the original canonical read; absent-state cleanup never takes a
fresh pathname `stat` that could authorize a substitute. Operators may later remove retained
quarantines only after equivalent inode-bound reauthentication.

## Variables

| Variable | Default | Description |
| --- | --- | --- |
| `ssh_forwarding_identity_enabled` | `true` | Enable identity management. |
| `ssh_forwarding_identity_state` | `present` | Provision or explicitly remove (`absent`) the identity. |
| `ssh_forwarding_identity_removal_confirm` | `false` | Must be `true` before `state: absent` can remove key files. |
| `ssh_forwarding_identity_become` | `false` | Become the identity user for key commands; enable from a privileged remote play. |
| `ssh_forwarding_identity_user` | `CHANGEME` | Existing local owner. |
| `ssh_forwarding_identity_group` | same as user | Local group owner. |
| `ssh_forwarding_identity_home` | `/home/<user>` | Owner home directory. |
| `ssh_forwarding_identity_path` | `~/.ssh/forwarding_ed25519` | Private identity path. |
| `ssh_forwarding_identity_comment` | `restricted-forwarding@<inventory-host>` | Public key comment. |
| `ssh_forwarding_identity_keygen` | `/usr/bin/ssh-keygen` | Absolute key generator path. |

## Example

```yaml
- name: Provision a forwarding identity on macOS
  hosts: localhost
  connection: local
  roles:
    - role: local.ops_library.ssh_forwarding_identity
      vars:
        ssh_forwarding_identity_user: operator
        ssh_forwarding_identity_group: staff
        ssh_forwarding_identity_home: /Users/operator
        ssh_forwarding_identity_path: /Users/operator/.ssh/service-forwarding
```

Run the role twice when validating deployment; the second run preserves the exact private
key and should report no identity change. In check mode an existing private key is copied
from its no-follow descriptor into owner-only temporary storage for derivation. If absent,
the role generates temporary Ed25519 material and publishes only its public key for
downstream candidate validation. It never creates the configured parent or persists the
real identity in check mode.

## Rotation and removal ordering

1. Stop every client LaunchAgent that references the old key.
2. Provision and authorize a versioned replacement key, then verify actual forwarding.
3. Revoke the old server authorization and validate/reload complete sshd configuration.
4. Only then set this role to `state: absent` with
   `ssh_forwarding_identity_removal_confirm: true` to remove local public and private
   canonical names into authenticated quarantine.

Never remove the local private key before server revocation has succeeded. The confirmation
gate makes accidental key deletion fail closed.
