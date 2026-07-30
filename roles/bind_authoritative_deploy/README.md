# BIND Authoritative Deploy Role

Deploy an authoritative BIND 9 DNS server with managed config files and raw zone files.

## Features

- Installs BIND packages on Debian/Ubuntu.
- Manages `named.conf`, `named.conf.options`, and `named.conf.local`.
- Copies controller-managed zone files to `/etc/bind/`.
- Supports transfer-backed (secondary) zones that named populates via AXFR/IXFR.
- Renders TSIG `key { ... };` stanzas into a non-world-readable include for
  authenticated transfers and `NOTIFY`.
- Validates zones with `named-checkzone` and config with `named-checkconf` before reload.
- Post-deploy `dig` check that requires an authoritative answer, with retries so a
  secondary's first zone transfer can finish.

## Role Variables

```yaml
bind_zones: []                # Required: list of zone definitions (see below)
bind_zone_files_dir: "{{ (playbook_dir | realpath) | regex_replace('/playbooks.*$', '/files/bind') }}"

# Service + paths
bind_service_name: named
bind_config_dir: /etc/bind
bind_working_dir: /var/cache/bind

# Options
bind_recursion: true
bind_recursion_acl:
  - localhost
  - localnets
bind_allow_query:
  - any
bind_allow_query_cache: "{{ bind_recursion_acl }}"
bind_allow_transfer:
  - none
bind_dnssec_validation: auto
bind_listen_on: []
bind_listen_on_v6:
  - any
bind_extra_options: []

# TSIG
bind_tsig_keys: []            # list of {name, algorithm (optional), secret}
bind_tsig_keys_file: "{{ bind_config_dir }}/named.conf.keys"
bind_tsig_keys_mode: "0640"

# Verification
bind_verify_enabled: true
bind_verify_server: 127.0.0.1
bind_verify_retries: 12
bind_verify_delay: 5
bind_firewall_check_enabled: true

# Zone types
bind_zone_default_type: master
bind_zone_transfer_backed_types:
  - slave
  - secondary
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `bind_zone_default_type` | `master` | Type assumed for a zone entry that omits `type`. |
| `bind_zone_transfer_backed_types` | `[slave, secondary]` | Allow-list of zone types whose zone file is written by named from a zone transfer. Membership in this list is the single predicate that drives every secondary-specific behaviour (see below). |
| `bind_working_dir` | `/var/cache/bind` | BIND's `directory`; also where a transfer-backed zone's relative `file` is resolved. |
| `bind_config_dir` | `/etc/bind` | Where every other zone type's relative `file` is resolved, and where controller-managed zone files are installed. |
| `bind_verify_retries` / `bind_verify_delay` | `12` / `5` | Retry budget for the post-deploy authoritative SOA check (default: up to ~60s **per zone**; the loop runs every zone before failing, so a wholly broken server takes retries × delay × zone-count to report). |
| `bind_verify_zone_types` | `[master, primary, slave, secondary]` | Zone types the SOA check applies to. The check requires the `aa` flag, which non-authoritative types (`hint`, `forward`, `stub`) never set, so they are skipped rather than failed. |
| `bind_tsig_keys` | `[]` | TSIG keys to render as top-level `key { ... };` stanzas. Each entry is `{name, algorithm, secret}`; `algorithm` is optional and defaults to `hmac-sha256`. **`secret` must come from SOPS or `ansible-vault`, never from `defaults` or `group_vars`.** Empty by default, and nothing is rendered or included while it is empty. |
| `bind_tsig_keys_file` | `{{ bind_config_dir }}/named.conf.keys` | Where the key stanzas are written and included from. The include is emitted first in `named.conf`, and only when `bind_tsig_keys` is non-empty. |
| `bind_tsig_keys_mode` | `0640` | Mode of that file (owner `root`, group `bind_config_group`). Deliberately stricter than `bind_config_mode` (`0644`) — a TSIG secret must not be world-readable. The task that renders it is `no_log: true`. |
| `bind_extra_options` | `[]` | Raw lines emitted verbatim **inside** the `options { }` block. Consequently it cannot carry top-level statements such as `key` or `acl` — use `bind_tsig_keys` for keys, and an inline nested address-match list (see [Combining address and key correctly](#combining-address-and-key-correctly)) instead of a named `acl`. |
| `bind_service_user` | `bind` | Account named(8) runs as. Used to own `bind_working_dir` so the daemon can store transferred zones. Deliberately separate from `bind_config_group` — a group name is not usable as a file owner. |

For a complete list, see `defaults/main.yml`.

## Zone definitions

```yaml
bind_zones:
  - name: "example.com"
    file: "db.example.com"
    type: master
  - name: "2.0.192.in-addr.arpa"
    file: "db.192.0.2"
    type: master
```

| Key | Required | Description |
| --- | --- | --- |
| `name` | yes | Zone name as it appears in `zone "<name>" { ... };`. |
| `file` | yes | Zone file name. A relative value is resolved against `bind_config_dir`, or against `bind_working_dir` for transfer-backed zones. An absolute path is used verbatim. |
| `type` | no | BIND zone type. Defaults to `bind_zone_default_type` (`master`). |
| `primaries` | transfer-backed zones only | Primary servers to transfer from, rendered as `primaries { ... };`. Required and non-empty for transfer-backed zones. Normally a list; a single address may be given as a bare string, which renders verbatim (`bind_macros.acl_list` has an explicit string branch, exactly as for `bind_allow_transfer` and `bind_recursion_acl`). A mapping is rejected by validation. |
| `allow_transfer` | no | Per-zone `allow-transfer` address-match list, overriding the global `bind_allow_transfer`. |
| `extra_config` | no | List of raw lines emitted verbatim inside the zone block, e.g. `also-notify { ...; };`. |

`primaries`, `allow_transfer` and `extra_config` list entries are joined with `; `
and rendered verbatim — the role does not parse or rewrite them, so any valid BIND
address-match-list syntax can be used.

## Secondary (transfer-backed) zones

A zone whose type appears in `bind_zone_transfer_backed_types` is *transfer-backed*:
its content is pulled from a primary by AXFR/IXFR and written to disk by named,
not by Ansible. The default list is `[slave, secondary]`, which are BIND's two
names for the same thing (`secondary` is the modern spelling accepted since BIND
9.16; `slave` is the historical one). Both are accepted everywhere, so a zone can
be written either way with identical results.

For a transfer-backed zone the role:

- **requires a non-empty `primaries` list** (or a single address string) — validation fails with an explicit
  message otherwise, rather than letting `named-checkconf` reject the rendered file;
- **renders a `primaries { ... };` block** from that list;
- **resolves a relative `file` against `bind_working_dir`** (`/var/cache/bind`)
  instead of `bind_config_dir`, because named itself has to write the file there;
  `/var/cache/bind` is writable by the `bind` user and is the location the Debian
  AppArmor profile permits for zone writes;
- **skips the controller-side zone file entirely** — no file has to exist under
  `bind_zone_files_dir`, and nothing is copied to the server. The `bind_zone_files_dir`
  *directory* itself is still checked, so a host serving only transfer-backed zones
  needs that directory to exist even though it will be empty.

Every other zone type keeps today's behaviour unchanged and still gets its
controller-managed zone file installed. That explicitly includes `primary` (the
modern synonym for `master`) and `hint` — the exemption is an allow-list of
transfer-backed types, never a "not `master`" test, so those types are not
accidentally swept up.

### Worked example: a secondary nameserver

An authoritative-only secondary that mirrors two zones from a primary at
`192.0.2.10` / `2001:db8:1::10`:

```yaml
- name: Deploy secondary nameserver
  hosts: ns2
  become: true
  roles:
    - role: local.ops_library.bind_authoritative_deploy
      vars:
        bind_recursion: false        # a public secondary must not be an open resolver
        bind_allow_query: [any]
        bind_allow_transfer: [none]  # do not re-serve transfers onward
        bind_zones:
          - name: "example.com"
            file: "db.example.com"   # -> /var/cache/bind/db.example.com, written by named
            type: slave
            primaries:
              - "192.0.2.10"
              - "2001:db8:1::10"
          - name: "example.net"
            file: "db.example.net"
            type: secondary          # same behaviour as `slave`
            primaries:
              - "192.0.2.10"
```

This renders:

```
zone "example.com" {
    type slave;
    file "/var/cache/bind/db.example.com";
    primaries { 192.0.2.10; 2001:db8:1::10; };
};
```

Note that `bind_recursion: false` is set explicitly rather than inherited: the role
defaults to `bind_recursion: true` with `bind_recursion_acl: [localhost, localnets]`,
and on a hosted server `localnets` covers the whole provider subnet.

### The matching primary

The primary side needs no special support from this role — per-zone
`allow_transfer` and `extra_config` are enough:

```yaml
bind_zones:
  - name: "example.com"
    file: "db.example.com"
    type: master
    allow_transfer:
      - "198.51.100.20"
      - "2001:db8:2::20"
    extra_config:
      - 'also-notify { 198.51.100.20; 2001:db8:2::20; };'
```

Keep the global `bind_allow_transfer: [none]` as the deny-by-default and open
transfers per zone.

This pair authenticates the secondary by source address alone, which is spoofable
for `NOTIFY` and only as good as the network path for transfers. See
[TSIG-authenticated transfers](#tsig-authenticated-transfers) for the same setup
with a shared key, and note that adding a key changes these two clauses — it is not
purely additive.

## TSIG-authenticated transfers

TSIG signs `AXFR`/`IXFR` and `NOTIFY` with a shared secret, so a peer is
authenticated by something stronger than its source address. Three pieces are
needed, and the role covers all of them: the `key { ... };` stanza itself
(`bind_tsig_keys`), a reference to the key name from the peer clauses, and the
*same* key defined on **both** hosts.

### Defining the key

```yaml
bind_tsig_keys:
  - name: "xfer"
    # algorithm is optional and defaults to hmac-sha256
    secret: "{{ dns_secrets.tsig_xfer_secret }}"   # from SOPS or ansible-vault
```

renders `bind_tsig_keys_file` (`/etc/bind/named.conf.keys`, `root:bind 0640`):

```
key "xfer" {
    algorithm hmac-sha256;
    secret "EXAMPLEPLACEHOLDERNOTAREALKEYAAAAAAAAAAAAAA=";
};
```

and prepends `include "/etc/bind/named.conf.keys";` to `named.conf`, ahead of every
other include, so a key is defined before anything that references it. While
`bind_tsig_keys` is empty nothing is rendered and no include is emitted — the
config of a host that does not use TSIG is byte-identical to before the feature
existed. (The include has to stay conditional: `named-checkconf` fails outright with
`parsing failed: file not found` on an `include` of a file that is not there, so an
unconditional one would break every keyless host.)

Generate a key with `tsig-keygen -a hmac-sha256 xfer` and copy `name`, `algorithm`
and `secret` into your encrypted store.

### Secret handling

- **Never put real key material into `defaults`, `group_vars`, or any unencrypted
  file.** Pass it in from SOPS or `ansible-vault`. Validation rejects an empty secret
  and the literal `CHANGEME`, but it cannot tell a leaked key from a good one.
- `bind_tsig_keys_file` is written `0640 root:bind`, not the `0644` used for the rest
  of the config, so only `named` and `root` can read it. That mode difference is the
  whole reason the keys live in their own file rather than in `named.conf.options`,
  which is world-readable.
- The rendering task is `no_log: true`, so the secret reaches neither Ansible output,
  nor the check-mode diff, nor the FastDeploy UI. Worth knowing while debugging: a
  failure in that task reports as `censored`. The validation task is `no_log` for the
  same reason, so a rejected entry is identified by its position in the list, not by
  the message.
- `secret` must be valid base64 (what `tsig-keygen` emits). The keys file is checked
  with `named-checkconf` in its own right, because rotating a secret leaves
  `named.conf` byte-identical and so never re-runs *its* validation. A malformed
  secret fails the deploy with `bad secret 'bad base64 encoding'` — but since the task
  is `no_log`, that appears as a censored failure on the render task, which is the
  first place to look when a key change will not apply.

### Worked example: primary and secondary

One key, `xfer`, shared by a primary at `192.0.2.10` / `2001:db8:1::10` and a
secondary at `198.51.100.20` / `2001:db8:2::20`.

```yaml
- name: Deploy primary nameserver
  hosts: ns1
  become: true
  roles:
    - role: local.ops_library.bind_authoritative_deploy
      vars:
        bind_recursion: false              # authoritative only, not an open resolver
        bind_allow_query: [any]
        bind_allow_transfer: [none]        # deny by default; open per zone
        bind_tsig_keys:
          - name: "xfer"
            secret: "{{ dns_secrets.tsig_xfer_secret }}"
        bind_zones:
          - name: "example.com"
            file: "db.example.com"
            type: master
            # address AND key, not address OR key -- see below
            allow_transfer:
              - '!{ !{ 198.51.100.20; 2001:db8:2::20; }; any; }'
              - 'key "xfer"'
            extra_config:
              - 'also-notify { 198.51.100.20 key "xfer"; 2001:db8:2::20 key "xfer"; };'
```

```yaml
- name: Deploy secondary nameserver
  hosts: ns2
  become: true
  roles:
    - role: local.ops_library.bind_authoritative_deploy
      vars:
        bind_recursion: false
        bind_allow_query: [any]
        bind_allow_transfer: [none]        # do not re-serve transfers onward
        bind_tsig_keys:
          - name: "xfer"
            secret: "{{ dns_secrets.tsig_xfer_secret }}"
        bind_zones:
          - name: "example.com"
            file: "db.example.com"         # -> /var/cache/bind, written by named
            type: slave
            primaries:
              - '192.0.2.10 key "xfer"'
              - '2001:db8:1::10 key "xfer"'
```

Those render (`named.conf.local` on each side):

```
zone "example.com" {
    type master;
    file "/etc/bind/db.example.com";
    allow-transfer { !{ !{ 198.51.100.20; 2001:db8:2::20; }; any; }; key "xfer"; };
    also-notify { 198.51.100.20 key "xfer"; 2001:db8:2::20 key "xfer"; };
};
```

```
zone "example.com" {
    type slave;
    file "/var/cache/bind/db.example.com";
    primaries { 192.0.2.10 key "xfer"; 2001:db8:1::10 key "xfer"; };
};
```

The role needs no special support for the key *references*: `primaries`,
`allow_transfer` and `extra_config` entries are rendered verbatim, so `key "..."`
is written straight into them.

**`also-notify` must carry the key too.** Once the secondary's `primaries` names a
key, it expects that peer relationship to be signed and rejects unsigned `NOTIFY`.
A primary left with a bare `also-notify { 198.51.100.20; };` therefore has its
notifications dropped, and the secondary silently falls back to the SOA refresh
timer — changes arrive hours late instead of in seconds. Transfers keep working the
whole time, which is what makes this easy to miss. Update both sides together.

### Combining address and key correctly

**A BIND address-match list is a first-match-wins list of *alternatives*, not a set
of conditions that must all hold.** This is the single easiest thing to get wrong
here:

```
allow-transfer { 198.51.100.20; key "xfer"; };   // WRONG -- either one suffices
```

That accepts a **keyless** transfer from `198.51.100.20`, *and* accepts anyone
holding the key from **anywhere**. It is valid config — `named-checkconf` is happy
with it — it just does not mean what it looks like.

Requiring both needs the nested-negation idiom:

```
allow-transfer { !{ !{ 198.51.100.20; 2001:db8:2::20; }; any; }; key "xfer"; };
```

Read it inside out. The inner list `{ 198.51.100.20; 2001:db8:2::20; }` matches the
secondary's addresses; negated as `!{ ... }` inside a list whose next element is
`any`, the middle list `{ !{...}; any; }` matches exactly the addresses that are
*not* the secondary's. The leading `!` turns that into an explicit deny, so every
other source is rejected at the first element and never reaches the rest of the
list. The secondary's addresses do not match the first element at all, fall through,
and are then required to present the key. Net effect:

| Source | Key | Result |
| --- | --- | --- |
| secondary's address | correct key | allowed |
| secondary's address | no key / wrong key | refused |
| anywhere else | correct key | refused |

The middle case is the one that silently degrades to "allowed" if the flat form is
used, so it is worth testing explicitly rather than assuming.

**The nested form has to be written inline like this**, not as a named `acl`. BIND
does accept the more readable

```
acl "ns2-addrs" { 198.51.100.20; 2001:db8:2::20; };   // top level only
...
    allow-transfer { !{ !ns2-addrs; any; }; key "xfer"; };
```

but an `acl` statement is only legal at the top level of `named.conf`, and this role
has no variable that emits top-level statements: `bind_extra_options` lines are
rendered *inside* the `options { }` block, where `named-checkconf` rejects them with
`unknown option 'acl'`. So either write the nested list inline per zone, or `include`
a file of your own that you manage separately.

### Checking it

`named-checkconf` validates the syntax of all of the above, but it does **not**
resolve key names: a reference to a key that was never defined — a typo, or a
forgotten `bind_tsig_keys` on one of the two hosts — passes the config check
cleanly and only surfaces at runtime as a refused transfer or a dropped `NOTIFY`.
Verify the behaviour, not just the parse, with all three rows of the table above:

```bash
dig @192.0.2.10 axfr example.com -y 'hmac-sha256:xfer:<secret>'   # from ns2: succeeds
dig @192.0.2.10 axfr example.com                                  # from ns2: REFUSED
dig @192.0.2.10 axfr example.com -y 'hmac-sha256:xfer:<secret>'   # elsewhere: REFUSED
```

Then bump a serial on the primary and confirm the secondary picks it up within
seconds (`dig +norec SOA example.com @198.51.100.20`). If it only catches up hours
later, signed `NOTIFY` is not working and `also-notify` is missing its key.

## Example Playbook

```yaml
- name: Deploy authoritative BIND
  hosts: bind
  become: true
  roles:
    - role: local.ops_library.bind_authoritative_deploy
```

## Notes

- Zone serials must be incremented manually when zone contents change. A serial that
  does not advance is not transferred by a secondary — a silent no-op that looks like
  success. Never revert a serial; roll content back under a *higher* serial.
- `bind_allow_transfer` defaults to `none` to prevent unintended AXFR. Set it
  explicitly (globally or per zone) if you have secondaries.
- Keep controller-managed zone files under `/etc/bind/` to stay within the default
  AppArmor profile; transfer-backed zones live under `/var/cache/bind/` instead,
  which is where the profile allows named to write.
- Emptying `bind_tsig_keys` again drops the `include` from `named.conf` *and* deletes
  `bind_tsig_keys_file`, so a retired secret does not linger on disk. Retiring a key is
  therefore a config change on both peers, not a file to clean up by hand.
- Set `bind_verify_enabled: false` to skip post-deploy `dig` checks (or change
  `bind_verify_server` if BIND only listens on a specific address).
- The post-deploy check uses `dig +norecurse` and requires the `aa` flag as well as
  `status: NOERROR`. Without both, a server running with `bind_recursion: true` can
  resolve the SOA from the public internet and answer `NOERROR` while its own copy of
  the zone is empty or failed to load — a false pass that retries would only make more
  likely. It retries `bind_verify_retries` times with `bind_verify_delay` seconds in
  between so a secondary's first transfer being in flight does not fail the run.
