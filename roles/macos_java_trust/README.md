# macos_java_trust

The role reads only native platform, effective UID/user and passwd home; it does
not depend on broad Ansible facts. The Ansible module interpreter must support the
controller's ansible-core (currently use target Python3.14; system/Homebrew default
Python3.15 is not supported by the current Ansible payload). The helper's own
Python variable can remain the normal Homebrew Python because it uses only stdlib.
Do not change the global inventory interpreter for this role.

Maintain Java trust copies with the two affected trust anchors (emSign ECC G3 and Sectigo AAA) removed
by exact SHA256 fingerprints, preserving every other certificate. Vendor `cacerts`
and signed application binaries stay intact. Run as the owning macOS user.

The documented JSSE `jssecacerts` default can protect a Homebrew JDK without a
process environment override. PyCharm supports an external trust store through
custom VM options. This role installs the option without quitting the IDE;
already-running JVMs require restart to discard loaded trust and SSL contexts.
PyCharm's IDE option does not automatically configure separately launched build
or application JVMs. Existing custom trustStore flags fail closed for reconciliation.
AAA is not owned by eMudhra: it cross-signs the compromised intermediates.
Removing these roots also distrusts their legitimate descendants until vendor
updates provide a narrower blocklist; this mirrors the distribution mitigation.

User configuration managed by chezmoi must be changed in its source instead;
check that before configuring a target's `options` path.

## Variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `macos_java_trust_python` | `/opt/homebrew/bin/python3` | Controller-compatible Python on target |
| `macos_java_trust_directory` | User Library Application Support/ops-library/java-trust | Helper location |
| `macos_java_trust_pycharm_vm_options` | `""` | Optional external options path; a narrow GUI LaunchAgent sets only `PYCHARM_VM_OPTIONS` |
| `macos_java_trust_targets` | `[]` | Explicit objects with `jdk`, `output`, optional paired `options` and `default_options` |

## Example

```yaml
- hosts: mac_workstations
  become: false
  gather_facts: false
  vars:
    ansible_python_interpreter: /opt/homebrew/opt/python@3.14/libexec/bin/python3
  roles:
    - role: local.ops_library.macos_java_trust
      macos_java_trust_targets:
        - jdk: /opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home
          output: /opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home/lib/security/jssecacerts
```

When targeting PyCharm's current user configuration directory, it must already
exist: creating it before the first launch suppresses normal JetBrains settings
import. The helper refuses that case before changing any trust store or options.
Use external VM options under the managed helper directory instead, or initialize
the IDE normally before configuring a current-config target.

For PyCharm, choose an external `output` and `options` under the helper directory,
and the existing user custom options or vendor options as `default_options`.
Set `macos_java_trust_pycharm_vm_options` to the same managed `options` path.
An Aqua-only RunAtLoad LaunchAgent uses native `launchctl setenv` inside the
owning GUI domain, so ordinary future GUI launches receive JetBrains' documented
per-app variable. No global Java environment variable is used. The role refuses
to overwrite a different existing GUI value, validates the plist with `plutil`,
and verifies only the selected GUI-domain variable without exposing other
variables. The setter job exits immediately; it does not keep an IDE running.
The current IDE config directory stays absent, preserving first-launch import.
The default empty option skips this mechanism; it does not retire a previously
installed job. Retirement needs an explicit managed change to remove only
`org.ops-library.pycharm-trust-env` and unset only a matching managed GUI value. Existing custom options are retained byte-for-byte, with one
trustStore line appended. With no current custom file, the vendor options are
copied. Old-version config is never changed; selecting it explicitly as a template
retains its custom flags without migrating the rest of the IDE configuration.

The helper verifies its transformed store contains exactly the original unrelated
aliases/fingerprints before atomically installing it. Existing `jssecacerts` files
are adopted with all unrelated custom certificates retained. A manifest detects
manual drift and fails closed. Vendor CA changes regenerate a pristine managed
copy; adopted custom stores instead require explicit reconciliation. Rerun after
Homebrew/JBR upgrades: a new Homebrew keg has no `jssecacerts`, and a new IDE
version needs its new configuration directory. No background update hook is added.
Check mode previews Ansible helper installation and validates GUI preconditions; direct helper `--check`
inspects a configured target without changing stores/options. Readiness must be
verified using the same JDK and launch option that the application will use.

Sources: [Ubuntu incident mitigation](https://ubuntu.com/blog/emudhra-ca-compromise-fixes-available),
[Oracle JSSE trust-store selection](https://docs.oracle.com/en/java/javase/25/security/java-secure-socket-extension-jsse-reference-guide.html),
[Apple launchd user-agent configuration](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html),
[JetBrains custom VM options](https://www.jetbrains.com/help/pycharm/tuning-the-ide.html),
[incident root fingerprints](https://emudhra.we-have-a-problem.com/roots.json).

The managed GUI setter is re-enabled on each apply. To retire it, remove the
managed LaunchAgent and its GUI environment setting explicitly before disabling
this optional configuration; an empty variable alone does not retire it.
