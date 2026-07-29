# Infrastructure Roles

Reusable host identity, access-control, networking, and storage building blocks.

```{toctree}
:maxdepth: 1

ssh_forwarding_identity
ssh_restricted_forwarding_account
```

The forwarding roles deliberately separate client identity lifecycle from server-side
least-privilege policy. Follow their documented stop, revoke, validate, reload, and
key-removal order during rotation or removal.
