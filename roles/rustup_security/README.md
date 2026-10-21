# Rustup security patch

Patch an **existing** inspected Linux or macOS Rustup manager to 1.29.2, which
fixes its eMudhra bundled trust issue. This role does not deploy applications,
SDKs, components, shell profiles or toolchains.

## Explicit inputs

All identity/path/checksum inputs default empty and must be inventoried:

| Variable | Meaning |
| --- | --- |
| `rustup_security_owner` | Existing account name |
| `rustup_security_home` | Exact account home reported by the OS |
| `rustup_security_cargo_home` | Existing owner-controlled `CARGO_HOME` |
| `rustup_security_rustup_home` | Existing owner-controlled `RUSTUP_HOME` |
| `rustup_security_triple` | Exact supported host triple |
| `rustup_security_old_sha256` | Independently captured original manager hash |
| `rustup_security_ca_file` | Already patched OS PEM used for HTTPS download |
| `rustup_security_python` | Target stdlib Python (`/usr/bin/python3` default) |
| `rustup_security_become` | Become the owner (`true` default); set `false` for an explicit local current-owner connection |

The version is pinned to **1.29.2**, with exact official checksums for Linux
x86_64/aarch64 GNU and macOS x86_64/aarch64. The helper independently checks this
allowlist and the actual platform; changing role variables cannot execute an
arbitrary updater. A new upstream version requires code/provenance review.

```yaml
- hosts: selected_host
  gather_facts: false
  tasks:
    - name: Patch the existing Rustup manager
      ansible.builtin.include_role:
        name: local.ops_library.rustup_security
      vars:
        rustup_security_owner: coding
        rustup_security_home: /home/coding
        rustup_security_cargo_home: /home/coding/.cargo
        rustup_security_rustup_home: /home/coding/.rustup
        rustup_security_triple: x86_64-unknown-linux-gnu
        rustup_security_old_sha256: "<observed-sha256>"
        rustup_security_ca_file: /etc/ssl/certs/ca-certificates.crt
```

Run `--check` first, then apply in an idle coding window. Use a target-module
interpreter supported by Ansible and a stdlib helper Python **3.11 or later**. On macOS, use an explicit local connection as
the current owner, `rustup_security_become: false`, an already patched native PEM,
and `aarch64-apple-darwin` or `x86_64-apple-darwin`. No sudo or SSH authentication
changes are part of this role.

## Trust and preservation

The role requires patched OS roots excluding both incident certificates, then
fetches the official pinned archive through that CA file with TLS verification
and its official SHA-256. It never uses the old manager's network downloader.
It invokes the **new verified** binary's `--self-replace` stage, the exact
[upstream Unix self-update replacement stage](https://github.com/rust-lang/rustup/blob/1.29.2/src/cli/self_update/unix.rs).
This internal contract is pinned to 1.29.2 and must be re-reviewed before release
changes. It copies the manager and refreshes upstream proxies without entering
the normal installer/profile/environment/toolchain stages.

Use this role only for independently verified upstream self-managed installs.
Package-managed or chezmoi-managed binaries require their own manager/source
workflow instead. Inspect that ownership before supplying the original hash.

Owner/account/path drift, active Rust tools/updaters, or unknown/custom proxy identities
abort. No existing installation is created. Private manager/proxy rollback
material and receipts remain under `CARGO_HOME/.managed-rustup-security/`;
temporary installers are cleaned. An updater failure attempts every manager and
proxy restoration and records partial recovery honestly.

Settings bytes, environment-file hashes, and bounded toolchain directory and
manifest metadata are compared before and after. This does not hash every SDK
file. Existing SDKs are never deliberately executed. Restored old manager bytes
remain vulnerable and need a later successful patch. Keep receipts until verified.

Use `rustup --help` for the manager version header. `rustup --version` can invoke
active toolchain discovery/compiler reporting, so it is not a pure manager
inventory command. A fixed manager checksum plus proxy checks establishes this
patch; it does not audit every Rust application's embedded root store.

See the [official security release](https://blog.rust-lang.org/2026/10/20/Rustup-1.29.2/)
and [archive/checksum documentation](https://rust-lang.github.io/rustup/installation/other.html).

The vendor process receives no inherited `RUSTUP_*` or `RUST_*` variables; the
role supplies only the explicit Rustup/Cargo homes after removing these variables.
This prevents upstream `RUSTUP_FORCE_ARG0` dispatch and trace settings from
redirecting the manager-only replacement stage.
