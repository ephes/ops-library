# Infrastructure Roles

Reusable host identity, access-control, networking, and storage building blocks.

```{toctree}
:maxdepth: 1

echoport_remote_command_guard
chrome_ca_distrust
container_ca_remediate
macos_python_ca_remediate
linuxserver_ca_remediate
macos_ca_remediate
java_ca_refresh
macos_ssh_tunnel
macos_java_trust
ssh_forwarding_identity
ssh_restricted_forwarding_account
```

The forwarding roles deliberately separate client identity lifecycle from server-side
least-privilege policy. Follow their documented stop, revoke, validate, reload, and
key-removal order during rotation or removal.
