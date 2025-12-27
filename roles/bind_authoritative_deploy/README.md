# BIND Authoritative Deploy Role

Deploy an authoritative BIND 9 DNS server with managed config files and raw zone files.

## Features

- Installs BIND packages on Debian/Ubuntu.
- Manages `named.conf`, `named.conf.options`, and `named.conf.local`.
- Copies zone files from the controller to `/etc/bind/`.
- Validates zones with `named-checkzone` and config with `named-checkconf` before reload.

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
bind_verify_enabled: true
bind_verify_server: 127.0.0.1
bind_firewall_check_enabled: true
```

Zone definition format:

```yaml
bind_zones:
  - name: "example.com"
    file: "db.example.com"
    type: master
  - name: "10.in-addr.arpa"
    file: "db.10"
    type: master
```

For a complete list, see `defaults/main.yml`.

## Example Playbook

```yaml
- name: Deploy authoritative BIND
  hosts: bind
  become: true
  roles:
    - role: local.ops_library.bind_authoritative_deploy
```

## Notes

- Zone serials must be incremented manually when zone contents change.
- `bind_allow_transfer` defaults to `none` to prevent unintended AXFR. Set it explicitly if you have secondaries.
- Keep zone files under `/etc/bind/` to stay within the default AppArmor profile.
- Set `bind_verify_enabled: false` to skip post-deploy `dig` checks (or change `bind_verify_server` if BIND only listens on a specific address).
