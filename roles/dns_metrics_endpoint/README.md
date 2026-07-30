# dns_metrics_endpoint

Expose authoritative-DNS health signals as an authenticated HTTP endpoint for Nyxmon `json-metrics` checks.

## What It Does

This role deploys two components:

1. `dns-metrics-collector.timer` runs every `dns_metrics_endpoint_timer_interval` seconds.
2. `dns-metrics-endpoint.service` serves the collected JSON at `/.well-known/dns` (configurable).

The collector timer schedules its first run relative to timer activation and
subsequent runs relative to the previous collector completion. This keeps the
collector moving after reboot or service restart even when the host comes up
after the boot-relative delay has already elapsed.

The collector probes the configured nameservers **by address**, never through
the delegation. That is deliberate: a check that resolves `ns2.example.com`
first would depend on the parent zone's glue, so it could not be made green
*before* the glue is changed — and it would go blind in exactly the case where
the glue is the thing that broke. Probing addresses directly means the check is
valid before, during and after a registrar change.

Nothing here needs zone-transfer access: no AXFR is attempted, and no TSIG key
is read, referenced or required. SOA queries are enough to answer every question
below, and keeping the collector unprivileged and keyless means the monitoring
host is not a new place a transfer key can leak from.

### 1. Every advertised endpoint, individually

Every combination of nameserver × address family × transport is probed and
reported on its own: with two dual-stack nameservers and both transports that
is eight endpoints, not one.

A single aggregate "DNS is up" boolean is worse than useless here, because it
goes green as soon as *any* server answers on *any* path. That hides a half-dead
nameserver — the exact failure mode a secondary exists to protect against — and
it hides partial-path failures completely:

- **A v6-only failure is invisible to a v4 probe.** Resolvers that prefer IPv6
  will try the `AAAA` first and stall on every lookup, while a v4/UDP check
  reports perfect health.
- **A TCP-only failure is invisible to a UDP probe.** TCP is *mandatory* for
  authoritative servers (RFC 7766), not an optimisation: it carries every
  response too large for the client's advertised UDP buffer, and every
  `TC`-flagged retry. A server reachable only over UDP/53 serves small answers
  and silently fails large ones — DNSSEC, long `TXT`/`MX` sets, `ANY`. A
  firewall that forgot TCP/53, or an `ip6tables` ruleset that diverges from its
  v4 twin, is a common and completely silent way to get there.

Per endpoint the result is `ok`, `failed` or `skipped`, with the errors observed
and the worst round-trip time, so a failure can be attributed to one address and
one transport instead of "DNS".

### 2. Recursion disabled, and an authoritative answer required

Every SOA query is sent with `+norecurse`, and the response must carry the `aa`
(authoritative answer) flag. `NOERROR` without `aa` is recorded as
`not_authoritative` — a failure, not a pass.

This is the single most important assertion in the role. A bare serial
comparison can pass against a server that is not authoritative for the zone at
all: a misconfigured or accidentally recursive `named` will happily go *fetch*
the SOA from the real nameservers and hand it back, so the serial matches
perfectly while the server holds no copy of the zone and answers nothing else in
it. The monitoring is then green precisely because the server is broken in the
way that is hardest to notice. Requiring `aa` — and refusing to let the server
recurse on our behalf while we ask — is what makes a matching serial mean "this
server serves this zone" rather than "this server can look this up".

The related smell gets its own flag: if an answer comes back with `ra`
(recursion available) set, `nameservers.<id>.recursion_advertised` and
`summary.no_recursion_advertised` record it. An authoritative-only server should
not be advertising recursion even when it is refusing to perform it.

### 3. Per-zone SOA serial agreement

For each configured zone the serial seen at every endpoint is collected, then
compared across nameservers: `zones[].serials_agree`, the distinct serials
observed, per-nameserver `lag` against the highest serial seen, and which
nameservers failed to report a serial at all
(`zones[].missing_from`, reason `missing_serial_from:<ids>`).

Divergence means replication has stalled — a lost `NOTIFY`, a refused transfer,
a serial that was reverted below the secondary's high-water mark — and the
secondary will keep serving its stale copy until the SOA expire timer runs out,
which is measured in days. Serial comparison is the only cheap way to see that
long before expiry does it for you.

Only list zones that *every* configured nameserver is expected to be
authoritative for. A zone served by the primary alone will report permanently
out of sync, which is correct but useless.

### 4. Open-resolver regression

For each nameserver address, one recursion-**desired** query for a foreign name
(`dns_metrics_endpoint_foreign_name`, a name none of the configured servers is
authoritative for) must be answered `REFUSED`.

An authoritative server that starts recursing for strangers is both a security
regression — it can be conscripted into DNS amplification attacks, and its cache
becomes a poisoning target — and a sign that the configuration is not what the
operator thinks it is. Recursion tends to arrive by accident: a package upgrade
restoring a distribution default, a hand-edited `named.conf` during an incident,
an `allow-recursion` clause that was meant to be temporary. Asserting `REFUSED`
on every address turns that into an alert instead of a discovery.

An endpoint that does not answer at all yields an `unknown` open-resolver probe,
not a failed one: an unreachable server has not been *observed* recursing, and
its unreachability is already reported by the endpoint checks. This keeps a
plain outage from also raising a bogus security alert.

### Honest handling of collector-side IPv6 loss

If the *collector host* loses IPv6, naive code reports every v6 endpoint as DOWN
and produces confident alarms about the wrong end of the connection. Chasing a
"nameserver v6 outage" that is really a home router that dropped its prefix
delegation is how monitoring loses its credibility.

So the collector first establishes its own capability: it opens an unconnected
UDP socket and `connect()`s it towards `dns_metrics_endpoint_ipv6_probe_address`
to make the kernel perform route and source-address selection. **No packets are
sent** — `connect()` on a UDP socket transmits nothing — so this measures the
collector, not the remote host, and cannot itself fail because of someone else's
outage. The selected source address must be global unicast (`2000::/3`).
Link-local and ULA addresses are rejected on purpose: a Tailscale address
(`fd7a:115c:a1e0::/48`, inside the ULA range `fc00::/7`) proves the collector can
reach the tailnet, and nothing at all about reaching a nameserver on the
internet.

When `meta.collector_ipv6_capable` is `false`:

- v6 endpoint results are reported `skipped` with
  `skip_reason: collector_no_ipv6`, never `failed`;
- they are excluded from `summary.overall_ok`, so the master gate does not go
  red for something the nameservers are not doing;
- `summary.ipv6_tested` goes `false` and `summary.ipv6_endpoints_skipped`
  counts the lost cells, so untested IPv6 cannot quietly rot into "we have not
  actually checked v6 since March".

"ns2 v6 is broken" and "I could not test v6" are therefore two distinguishable
states, and the second one is still visible — a warning rule on
`$.summary.ipv6_tested` is what keeps `skipped` from becoming a silent hole.

## Design

- Collection runs as root, only to own/refresh the data directory and the JSON
  file modes; the DNS probes themselves need no privilege, so the collector unit
  sets `NoNewPrivileges=true` and bounds capabilities to the ones its
  `chown`/`chmod` steps use.
- The collector writes to `<json>.tmp` and `mv`s it into place, so a reader
  never sees a half-written document.
- HTTP server runs as the unprivileged `metrics` user and only ever reads that
  file. Privilege separation means the internet-adjacent component never runs
  the probes and never needs root.
- Basic auth via htpasswd.
- Tailscale-only access by default (`IPAddressAllow=100.64.0.0/10` + explicit
  bind IP).
- `dig` (from `bind9-dnsutils`) is driven via subprocess rather than a Python
  DNS library: it adds no pip dependency to a monitoring host, and it makes the
  check byte-identical to what a human types while debugging it. The exact
  invocation is documented under [Validation](#validation) — reproducing a red
  check is a copy-paste, not a translation exercise.
- Queries run concurrently (`dns_metrics_endpoint_max_workers`). The matrix is
  `nameservers × families × transports × zones` plus one open-resolver probe per
  nameserver address, so two dual-stack nameservers with four zones are 32 SOA
  queries + 4 foreign-name queries.
- Failure is always contained. Every probe catches its own errors, `dig` runs
  under a hard subprocess timeout, and the collector wraps the whole run: on an
  internal error it still prints a complete, valid document with
  `meta.collector_error` set and `summary.collector_ok`/`overall_ok` false. It
  never crashes out and leaves the previous file in place to be served as if it
  were current — a fresh "not ok" alerts now, whereas a stale success only
  surfaces later, and only if someone is watching `age_seconds`.

## Variables

### Core

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_metrics_endpoint_enabled` | `false` | Enable/disable role |
| `dns_metrics_endpoint_bind` | `{{ tailscale_ip \| default('127.0.0.1') }}` | Bind address |
| `dns_metrics_endpoint_port` | `9107` | Listen port |
| `dns_metrics_endpoint_path` | `/.well-known/dns` | Endpoint path |
| `dns_metrics_endpoint_auth_user` | `CHANGE_ME` | Basic auth user (rejected as-is) |
| `dns_metrics_endpoint_auth_password` | `CHANGE_ME` | Basic auth password (rejected as-is) |
| `dns_metrics_endpoint_packages` | `[python3, apache2-utils, bind9-dnsutils]` | Packages installed; use `dnsutils` instead of `bind9-dnsutils` on older Debian/Ubuntu |
| `dns_metrics_endpoint_timer_interval` | `300` | Collector interval in seconds; also the collector's `TimeoutStartSec` |
| `dns_metrics_endpoint_timer_on_boot_sec` | `30` | Initial delay after timer activation |
| `dns_metrics_endpoint_timer_accuracy_sec` | `10` | systemd timer accuracy |
| `dns_metrics_endpoint_timer_randomized_delay_sec` | `15` | Jitter added to each timer run |
| `dns_metrics_endpoint_user` / `_group` | `metrics` | Unprivileged user/group owning the HTTP service |
| `dns_metrics_endpoint_data_dir` | `/var/lib/dns-metrics` | Directory holding the JSON (`0750 root:metrics`) |
| `dns_metrics_endpoint_json_path` | `{{ data_dir }}/dns.json` | Collected document (`0640 root:metrics`) |

### DNS Probe Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_metrics_endpoint_nameservers` | two RFC 5737/RFC 3849 placeholders | Nameservers to probe (see below) |
| `dns_metrics_endpoint_zones` | `["example.com"]` | Zones whose SOA serial must agree across **all** configured nameservers |
| `dns_metrics_endpoint_families` | `[ipv4, ipv6]` | Address families to exercise |
| `dns_metrics_endpoint_transports` | `[udp, tcp]` | Transports to exercise |
| `dns_metrics_endpoint_vantage_point_limitations` | `[]` | Matrix cells this collector provably cannot reach although the nameserver is healthy elsewhere. See below. |
| `dns_metrics_endpoint_foreign_name` | `example.net` | Name no configured nameserver is authoritative for; asserted not to be one of the monitored zones |
| `dns_metrics_endpoint_foreign_qtype` | `A` | Query type for the open-resolver probe |
| `dns_metrics_endpoint_open_resolver_transport` | `udp` | Transport for the open-resolver probe |
| `dns_metrics_endpoint_dig_timeout` | `3` | `dig +time=` per try |
| `dns_metrics_endpoint_dig_tries` | `2` | `dig +tries=` |
| `dns_metrics_endpoint_dig_subprocess_timeout` | `15` | Hard subprocess guard; asserted to exceed `dig_timeout × dig_tries` so it cannot fire before `dig` has used its own retries |
| `dns_metrics_endpoint_max_workers` | `8` | Concurrent `dig` processes |
| `dns_metrics_endpoint_ipv6_probe_address` | `2001:4860:4860::8888` | Route-lookup target for collector IPv6 detection (no packets are sent) |

`dns_metrics_endpoint_nameservers` entries:

| Key | Required | Description |
|-----|----------|-------------|
| `id` | yes | Unique, dot-free, lowercase (`^[a-z][a-z0-9_]*$`). Appears verbatim in JSON paths |
| `label` | no | Human/DNS name, debugging output only |
| `role` | no | Free-form, e.g. `primary`/`secondary` |
| `ipv4` | one of | IPv4 address; omit or leave empty to skip the IPv4 endpoints |
| `ipv6` | `ipv4`/`ipv6` | IPv6 address; omit or leave empty to skip the IPv6 endpoints |
| `families` | no | Subset of `dns_metrics_endpoint_families`, for this nameserver only |
| `transports` | no | Subset of `dns_metrics_endpoint_transports`, for this nameserver only |

## Vantage-point limitations

Sometimes a single cell of the matrix is unreachable from *this* collector while the
nameserver answers perfectly from everywhere else — a broken TCP path between the
collector's ISP and one nameserver's IPv6 prefix, for instance. Reported as a failure
that check goes permanently red, and a permanently red check gets ignored, which costs
more than the blind spot does.

Declare such a cell explicitly:

```yaml
dns_metrics_endpoint_vantage_point_limitations:
  - id: "ns2-ipv6-tcp"          # "<nameserver-id>-<family>-<transport>"
    reason: "collector ISP cannot complete TCP to this prefix; healthy from elsewhere"
```

The cell is then reported `skipped` with a `vantage_point:` reason and excluded from
`overall_ok`, but it is **counted and named** in
`summary.vantage_point_limitations` / `summary.vantage_point_limited_endpoints`, so the
gap stays greppable instead of silently rotting into an outage nobody notices.

Only the ids you name are exempted — every other unreachable cell still fails.

Two rules for using this honestly:

1. **Prove it is a path problem first.** Verify the endpoint from an independent host
   before adding it here. The default is empty on purpose: never hide a failure you have
   not shown is local to the collector.
2. **Re-verify periodically.** A declared limitation is an untested endpoint. Whatever
   runbook consumes this endpoint should say how to spot-check it from elsewhere.

The `id` must be dot-free because Nyxmon's JSON path resolver splits on dots
with no escaping, and ids appear in `$.nameservers.<id>.*` rule paths. The role
asserts the pattern and uniqueness rather than letting a dotted id produce a
rule that silently never matches.

Per-nameserver `families`/`transports` narrow the matrix for one nameserver (the
global lists narrow it for all); the role asserts an override can only be a
non-empty subset, never a widening. Use them only for a known limitation of the
**collector's own vantage point** — for example a home ISP that cannot reach one
provider's prefix over TCP/IPv6 — and never to quiet a real fault. Excluded
cells are reported `skipped` with a `skip_reason`, counted in
`summary.endpoints_skipped`, and flip the matching `summary.*_tested` flag to
`false`, so narrowing costs visible coverage instead of hiding a problem.

## Example

```yaml
- hosts: monitoring_collector
  roles:
    - role: local.ops_library.dns_metrics_endpoint
      vars:
        dns_metrics_endpoint_enabled: true
        dns_metrics_endpoint_auth_user: "nyxmon"
        dns_metrics_endpoint_auth_password: "{{ vault_dns_metrics_password }}"
        dns_metrics_endpoint_nameservers:
          - id: ns1
            label: ns1.example.com
            role: primary
            ipv4: "192.0.2.53"
            ipv6: "2001:db8:1::53"
          - id: ns2
            label: ns2.example.com
            role: secondary
            ipv4: "198.51.100.53"
            ipv6: "2001:db8:2::53"
        dns_metrics_endpoint_zones:
          - example.com
          - example.org
        dns_metrics_endpoint_foreign_name: "example.net"
```

### Choosing the collector host

- It must be genuinely **off-network** from the nameservers. A probe from inside
  the same datacentre, or worse from one of the nameservers, proves that the
  daemon is running — not that resolvers on the internet can reach it. Local
  probes cannot see a provider firewall, a routing leak, or a missing v6 route.
- It should have working public IPv4 **and** IPv6, or the v6 half of the matrix
  is permanently `skipped`. Skipped is honest, but it is not coverage.
- A home connection is a good vantage point for the first reason and a
  fragile one for the second: consumer ISPs lose or renumber prefixes, and some
  paths work for UDP but not TCP. Expect to see the collector's own
  limitations, and read `meta.collector_ipv6_*` before blaming a nameserver.

## Response Shape (abridged)

```json
{
  "generated_at": "2026-07-29T21:40:59+00:00",
  "duration_seconds": 6.265,
  "meta": {
    "collector_ipv6_capable": true,
    "collector_ipv6_source": "2001:db8:cafe::1",
    "collector_ipv6_probe_address": "2001:4860:4860::8888",
    "collector_ipv6_detect_error": null,
    "collector_hostname": "collector",
    "collector_error": null,
    "generated_at_epoch": 1785361259,
    "served_at_epoch": 1785361301,
    "age_seconds": 42
  },
  "config": {
    "zones": ["example.com", "example.org"], "families": ["ipv4", "ipv6"],
    "transports": ["udp", "tcp"], "foreign_name": "example.net",
    "foreign_qtype": "A", "open_resolver_transport": "udp",
    "dig_timeout": 3, "dig_tries": 2
  },
  "summary": {
    "all_endpoints_ok": false,
    "all_zones_in_sync": true,
    "no_open_resolver": true,
    "overall_ok": false,
    "endpoints_total": 8, "endpoints_tested": 8, "endpoints_ok": 7,
    "endpoints_failed": 1, "endpoints_skipped": 0,
    "failed_endpoints": "ns2-ipv6-tcp",
    "ipv4_tested": true, "ipv4_endpoints_ok": true,
    "ipv6_tested": true, "ipv6_endpoints_ok": false, "ipv6_endpoints_skipped": 0,
    "udp_tested": true, "udp_endpoints_ok": true,
    "tcp_tested": true, "tcp_endpoints_ok": false,
    "authoritative_ok": true,
    "no_recursion_advertised": true,
    "nameservers_total": 2, "nameservers_ok": 1, "nameservers_failed": 1,
    "zones_total": 2, "zones_in_sync": 2, "zones_out_of_sync": 0,
    "out_of_sync_zones": "", "max_serial_lag": 0,
    "open_resolver_tested": 4, "open_resolver_failed": 0,
    "open_resolver_unknown": 0, "open_resolver_skipped": 0,
    "collector_ok": true, "collector_ipv6_capable": true
  },
  "nameservers": {
    "ns2": {
      "id": "ns2", "label": "ns2.example.com", "role": "secondary",
      "ipv4": "198.51.100.53", "ipv6": "2001:db8:2::53",
      "ok": false, "endpoints_total": 4, "endpoints_ok": 3,
      "endpoints_failed": 1, "endpoints_skipped": 0,
      "failed_endpoints": "ns2-ipv6-tcp",
      "ipv4_tested": true, "ipv4_ok": true,
      "ipv6_tested": true, "ipv6_ok": false,
      "udp_tested": true, "udp_ok": true,
      "tcp_tested": true, "tcp_ok": false,
      "recursion_advertised": false, "open_resolver": false,
      "foreign_probes_tested": 2, "foreign_probes_failed": 0,
      "zones_out_of_sync": 0, "max_serial_lag": 0
    }
  },
  "zones": [
    {
      "zone": "example.com",
      "in_sync": true, "serials_agree": true, "all_nameservers_reported": true,
      "serial": 2026072902, "max_serial": 2026072902,
      "distinct_serials": [2026072902],
      "max_serial_lag": 0, "missing_from": [], "reasons": [],
      "nameservers": [
        {"nameserver": "ns1", "serial": 2026072902, "serials": [2026072902],
         "lag": 0, "probes_ok": 4, "probes_failed": 0},
        {"nameserver": "ns2", "serial": 2026072902, "serials": [2026072902],
         "lag": 0, "probes_ok": 3, "probes_failed": 1}
      ]
    }
  ],
  "endpoints": [
    {
      "id": "ns2-ipv6-tcp", "nameserver": "ns2", "label": "ns2.example.com",
      "role": "secondary", "family": "ipv6", "transport": "tcp",
      "address": "2001:db8:2::53", "state": "failed", "ok": false,
      "skip_reason": null, "zones_ok": 0, "zones_failed": 2,
      "errors": ["no_response"], "rtt_ms_max": 6050,
      "recursion_available_flag": false,
      "zones": [
        {"zone": "example.com", "ok": false, "error": "no_response",
         "serial": null, "owner": null, "status": null, "flags": [],
         "aa": false, "ra": false, "responded": false, "rtt_ms": 6050,
         "dig_rc": 9, "stderr": null}
      ]
    }
  ],
  "open_resolver": {
    "qname": "example.net", "qtype": "A", "transport": "udp",
    "probes": [
      {"nameserver": "ns1", "family": "ipv4", "address": "192.0.2.53",
       "state": "ok", "ok": true, "refused": true, "status": "REFUSED",
       "flags": ["qr", "rd"], "ra": false, "answer_count": 0,
       "rtt_ms": 38, "error": null, "skip_reason": null}
    ]
  }
}
```

A healthy per-zone probe looks like this — note `aa` in the flags, which is what
makes the serial meaningful:

```json
{"zone": "example.com", "ok": true, "error": null, "serial": 2026072902,
 "owner": "example.com.", "status": "NOERROR", "flags": ["qr", "aa"],
 "aa": true, "ra": false, "responded": true, "rtt_ms": 48,
 "dig_rc": 0, "stderr": null}
```

Per-zone probe errors are stable strings, so a red endpoint says *why*:
`no_response`, `status_<RCODE>` (e.g. `status_SERVFAIL`, `status_REFUSED`),
`not_authoritative` (answered `NOERROR` without `aa`),
`no_soa_serial_in_answer`, `owner_mismatch:<name>`. The open-resolver probe adds
`not_refused:<RCODE>`. `skip_reason` is one of `collector_no_ipv6`,
`address_not_configured`, `family_excluded_for_nameserver`,
`transport_excluded_for_nameserver`.

`meta.age_seconds` (and `generated_at`/`generated_at_epoch`/`served_at_epoch`)
are added by the HTTP endpoint at request time from the JSON file's mtime, and
are **merged into** the collector's `meta` object rather than replacing it, so
`meta.collector_ipv6_capable` and friends survive alongside the staleness
fields.

### Reading the booleans

Every `*_ok` field means **"nothing that was tested failed"**, so it is
vacuously `true` when nothing was tested — that is a deliberate, documented
convention rather than an oversight, because the alternative (false when
untested) would make every legitimately skipped cell look like an outage. The
price is that `*_ok` alone cannot distinguish healthy from unmeasured, so always
pair it with the matching `*_tested` field. That pairing is why
`$.summary.ipv6_tested` gets its own warning rule below.

`summary.overall_ok` is the one field that is safe on its own: besides requiring
endpoints, serials and the open-resolver assertion to be clean, it requires that
at least one endpoint was actually tested and at least one zone was evaluated,
and that `meta.collector_error` is null. An all-skipped or crashed run can
therefore never look healthy.

`summary.authoritative_ok` is `false` if **any** tested probe got a response
without `aa` — including a `REFUSED` or `SERVFAIL` for a zone the server is
supposed to serve. It is a separate flat boolean from `all_endpoints_ok` so an
alert can say "a server answered but not authoritatively" instead of just "an
endpoint is down".

`zones` is a **list**, not a dict keyed by zone name: zone names contain dots
and Nyxmon's path resolver splits on dots with no escaping, so a zone-keyed dict
would be unaddressable by a rule. Rules use the `summary` counters
(`zones_out_of_sync`, `max_serial_lag`) and the comma-joined
`out_of_sync_zones`/`failed_endpoints` strings for context; the list is for
humans debugging. `nameservers` *is* keyed by id, because ids are asserted
dot-free, so `$.nameservers.ns2.ok` is a valid fixed path.

`summary.no_open_resolver` means "no nameserver was *observed* recursing".
`summary.open_resolver_tested` / `_unknown` / `_skipped` show how much of that
claim was actually measured, since an unreachable server yields `unknown`.

## Nyxmon `json-metrics` Rules

Nyxmon's path resolver supports `$.field.subfield` and list indices
(`$.items.0.value`) only — no wildcards, no escaped dots. Every value a rule
needs therefore sits at a fixed path under `summary`, `meta` or
`nameservers.<id>`.

| Path | Op | Value | Severity | Why |
|------|----|-------|----------|-----|
| `$.summary.overall_ok` | `==` | `true` | critical | Master gate: endpoints + serial agreement + no open resolver + collector healthy, and something was actually tested |
| `$.meta.age_seconds` | `<` | `900` | warning | A dead collector otherwise reads as silence; every other field is a snapshot of the last run |
| `$.summary.all_endpoints_ok` | `==` | `true` | critical | Says which of the three legs failed |
| `$.summary.all_zones_in_sync` | `==` | `true` | critical | Replication stalled (lost `NOTIFY`, refused transfer, reverted serial) |
| `$.summary.no_open_resolver` | `==` | `true` | critical | Security regression: a server started recursing for strangers |
| `$.summary.authoritative_ok` | `==` | `true` | critical | A server answered without `aa` — the silent "not really authoritative" failure |
| `$.summary.max_serial_lag` | `<=` | `0` | warning | Fires on drift, slightly earlier and more legibly than `all_zones_in_sync` |
| `$.summary.ipv6_tested` | `==` | `true` | warning | v6 went untested; keeps `skipped` from rotting into permanent blindness |
| `$.summary.collector_ok` | `==` | `true` | warning | Collector hit an internal error; see `meta.collector_error` |
| `$.nameservers.ns1.ok` | `==` | `true` | warning | Attributes a half-dead nameserver to one host |
| `$.nameservers.ns2.ok` | `==` | `true` | warning | Attributes a half-dead nameserver to one host |

The minimum viable pair is `$.summary.overall_ok` and `$.meta.age_seconds`.
Everything else narrows down *which* thing broke; without `age_seconds` a
collector that stopped running keeps serving its last green document and the
absence of alerts is indistinguishable from health.

`$.nameservers.<id>.ok` rules must use the ids configured in
`dns_metrics_endpoint_nameservers` (`ns1`/`ns2` above). Renaming an id renames
the JSON path, so the corresponding rule stops matching — treat ids as part of
the monitoring contract.

## Validation

```bash
# 401 without auth (expected)
curl -sS -o /dev/null -w '%{http_code}\n' "http://<TAILSCALE_IP>:9107/.well-known/dns"

# 200 with auth
curl -sS -u "nyxmon:<password>" "http://<TAILSCALE_IP>:9107/.well-known/dns" | jq .

# What is failing, at a glance
curl -sS -u "nyxmon:<password>" "http://<TAILSCALE_IP>:9107/.well-known/dns" \
  | jq '.summary, .meta, [.endpoints[] | select(.ok != true) | {id, state, errors, skip_reason}]'

systemctl status dns-metrics-collector.timer
systemctl status dns-metrics-endpoint
journalctl -u dns-metrics-collector.service --since "1 hour ago"

# Force a collection now
systemctl start dns-metrics-collector.service
```

### Reproducing a probe by hand

The collector runs exactly these commands, one per matrix cell — use `+notcp`
for the UDP endpoints and `+tcp` for the TCP ones:

```bash
# SOA probe (per zone, per address, per transport)
dig +norecurse +notcp +time=3 +tries=2 +noall +comments +answer SOA <zone> @<address>
dig +norecurse +tcp   +time=3 +tries=2 +noall +comments +answer SOA <zone> @<address>

# Open-resolver probe (per address)
dig +recurse +notcp +time=3 +tries=2 +noall +comments +answer A <foreign-name> @<address>
```

Expected results:

- The SOA answer must contain `aa` in its flags. `NOERROR` **without** `aa` is a
  failure (`not_authoritative`), not a pass — see check 2 above.
- The SOA owner name must match the zone queried, and the serial must be
  present.
- The foreign-name query must return `status: REFUSED`.

If a probe fails from the collector but succeeds from elsewhere, the fault may
be the collector's vantage point rather than the nameserver. Check the same
address and transport from a second off-network host before touching `named`; a
transport-specific failure to a single prefix (v6/TCP in particular) is often a
consumer router or ISP path problem.

### HTTP status codes

| Status | Meaning |
|--------|---------|
| `200` | JSON document (possibly reporting failures — check `summary.overall_ok`) |
| `401` | Missing or wrong basic auth |
| `404` | Wrong path; must match `dns_metrics_endpoint_path` exactly |
| `502` | Metrics file exists but is not valid JSON |
| `503` | Metrics file missing (timer has not run yet) or unreadable |

## Deliberate limitations

Two things this role knowingly does not do, recorded so nobody has to rediscover
whether they were oversights.

**SOA serials are compared with plain integer arithmetic, not RFC 1982.** DNS serial
numbers are formally a 32-bit circular space, so the correct comparison is
sequence-space arithmetic; near the wrap point plain `max()` calls the newer serial
older and attributes lag to the wrong server. That is accepted here because the zones
this monitors use date-based serials (`YYYYMMDDNN`), which increase monotonically and
do not reach the 32-bit boundary until the year 4294. If you point this at zones using
counter-based serials that could realistically wrap, replace the comparison in
`_summarise_zones` with RFC 1982 arithmetic first.

**A declared vantage-point limitation is validated against the global matrix**, not
against the effective per-nameserver matrix. Naming a cell that some other exclusion
already removed is accepted and simply never reported as a limitation. That is
over-permissive rather than unsafe — it cannot hide a real failure, because the cell
was not being probed anyway — but it does mean a redundant entry sits in your config
looking meaningful. Prefer to keep the limitation list minimal and re-check it whenever
you change `families` or `transports`.
