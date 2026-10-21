# macos_ca_remediate

Remove the two roots implicated in the October 2026 eMudhra incident from
Apple’s `/etc/ssl/cert.pem`, following the incident response tracker’s macOS
curl workaround. Apple keychain revocation does not cover this PEM consumer.

Run as root on macOS only. The role backs up the original bundle through
a timestamped `.emudhra-<timestamp>.bak` sibling before atomic replacement, preserves unrelated certificate sections and
permissions, and verifies both affected roots are absent. Reapply after OS
updates until Apple replaces the bundle. Removing AAA Certificate Services
can affect unrelated certificates chaining to that root. Restore the backup
only after assessing that security tradeoff. This does not update application
bundles, Node, Electron, Java, Python certifi, or container images.

```yaml
- hosts: macos
  become: true
  roles:
    - local.ops_library.macos_ca_remediate
```

No configurable variables. Target path is deliberately fixed. See
https://emudhra.we-have-a-problem.com/#macos-curl for incident guidance.

Platform validation uses a native read-only uname command and does not require gathered facts. On ansible-core 2.20, use the Python 3.14 module interpreter and disable broad fact gathering when Homebrew Python is 3.15.
