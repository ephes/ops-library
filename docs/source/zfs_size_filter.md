# ZFS Size Filter

`local.ops_library.zfs_size_to_bytes` converts a non-negative ZFS size value
such as `6400G`, `6T`, or `1.1T` into the exact integer byte value ZFS stores.
ZFS scales decimal input by binary units and truncates fractional bytes; generic
human-size filters may round and introduce a one-byte difference in idempotency
comparisons.

Use the fully qualified filter name in collection roles:

```yaml
- name: Compare a configured ZFS quota with the numeric live property
  ansible.builtin.assert:
    that:
      - live_quota_bytes == (configured_quota | local.ops_library.zfs_size_to_bytes)
```

Accepted suffixes are `K`, `M`, `G`, `T`, `P`, `E`, and `Z`, optionally followed
by `B` or `iB`, and are interpreted as binary powers of 1024. Unitless values
are bytes. Invalid or negative values raise an Ansible filter error.
