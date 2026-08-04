# Changelog

All notable changes to the ops-library collection will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- `takahe_deploy` lets an operator turn Django error mail off. The role used to
  assert that `takahe_error_emails` was non-empty, so "no error mail" was not a
  configuration you could express; the only way to stop the mail was to point it
  at an address you did not read.

  An empty list is now an explicitly supported value meaning *do not send error
  mail*, and the rendered `.env` says so. Takahe assigns `ADMINS` only when
  `TAKAHE_ERROR_EMAILS` parses to a non-empty list, and Django's `mail_admins()`
  is a no-op with empty `ADMINS`, so nothing is sent and nothing is queued.

  The template keeps writing the key as `TAKAHE_ERROR_EMAILS=[]` instead of
  omitting it, because the two candidate "off" spellings are not equivalent.
  Takahe declares `ERROR_EMAILS: list[EmailStr] | None` in a pydantic v1
  settings model, and pydantic parses a complex field's environment value as
  JSON: an absent variable and `[]` both leave error mail off, but an empty
  string raises `SettingsError` and the service never starts. This was verified
  against the pydantic 1.10.17 install on the production host rather than
  inferred. Validation was tightened to match — a bare string, including
  `CHANGEME` and the empty string, is now rejected with a message that names the
  supported forms, so a wrong value fails during the play instead of after the
  restart.

  This matters for `fedi.python-podcast.de`, a two-user instance whose entire
  outbound mail volume is `502 Bad Gateway` reports from
  `/proxy/post_attachment/...`. Takahe returns 502 there whenever the remote
  instance holding an attachment is unreachable, which on the fediverse is
  routine rather than a defect, so the reports carried no signal while consuming
  a metered mail quota.

- `mailgun_relay_deploy` pins where the relay's log output goes and labels it.
  The unit now sets `StandardOutput=journal`, `StandardError=journal` and
  `SyslogIdentifier=mailgun-relay` instead of inheriting the system defaults and
  showing up in the journal as an anonymous `python[<pid>]` alongside every
  other python unit on the host. `journalctl -t mailgun-relay` now works.

  This came out of an investigation that concluded the relay "logs nothing to
  journald" and blamed a block-buffered stdout pipe with no `PYTHONUNBUFFERED`.
  That diagnosis is wrong: `logging.StreamHandler.emit` flushes the stream after
  every record, so the relay's lines reach the journal as they are emitted. The
  observed silence on macmini was journald retention (the unit started before
  the oldest retained entry) plus no mail traffic in the retained window; a
  probe request produced its access-log line in the journal immediately. The
  unit carries a comment saying so, and the role README now documents how to
  tell an idle relay from a broken one, so the placebo does not get added later.

- Paperless-ngx 2.20.15 -> 3.0.4 and PostfixAdmin 3.3.13 -> 4.0.5, the two major
  upgrades deferred from the previous pass. Neither is a version bump alone.

  Paperless v3 requires 2.20.15 exactly as the upgrade source, which is what was
  pinned, so the direct jump is supported. Three v3 migration items applied to
  this deployment. `PAPERLESS_OCR_MODE=skip` no longer exists — v3 decoupled OCR
  from archive-file generation and the upstream mapping table sends the old
  `skip` to `auto`, so `paperless_ocr_mode` now defaults to `auto`. The
  individual advanced database variables were replaced by a single
  `PAPERLESS_DB_OPTIONS`, so the template emits that instead of
  `PAPERLESS_DBSSLMODE`, fed by the new `paperless_db_options`. And v3 needs to
  be told which proxy to trust or logins can fail with 403, so the template now
  emits `PAPERLESS_TRUSTED_PROXIES`, defaulting to loopback because Traefik
  fronts it there.

  The rest of the v3 breaking changes were checked against the live
  configuration and do not apply: no encryption passphrase (v3 removed document
  encryption and would have required decrypting first), no pre/post-consume
  scripts, no consumer polling or barcode-scanner settings, and
  `PAPERLESS_SECRET_KEY` was already set — v3 makes it mandatory. Note that v3
  drops task history, rebuilds the search index from Whoosh to Tantivy on first
  start, and no longer rejects duplicate documents by default.

  PostfixAdmin 4.0 changed how the software has to be fetched, not just its
  version. Tags went from `postfixadmin-3.3.13` to `v4.0.5`, so the old URL would
  404, and 4.0 needs composer dependencies the GitHub source archive does not
  ship — it aborts on a missing `vendor/autoload.php`. The download now points at
  upstream's self-contained release asset. Of the two builds published per
  release, `php84` carries the updated spomky-labs/otphp with the two CVEs fixed
  in 4.0.4 while `php74` does not, and nothing in the php84 vendor tree requires
  more than PHP 8.1, so `postfixadmin_release_build` defaults to `php84`. The
  download is now checksum-verified, which it was not before. 4.0 drops PHP 7.4
  through 8.1 and removes the MySQL ENCRYPT hashing backend; neither bites here
  (PHP 8.3, PostgreSQL). Schema changes are handled by the existing idempotent
  `upgrade.php` step.

### Fixed

- `openclaw_deploy`: the `/homeassistant` command skill could act on the wrong device
  and report success under the name the user asked for. Asked to switch a device
  outside the write allowlist, the agent discovered the writable domain instead,
  switched the closest-sounding entity there, and confirmed using the original name.
  Observed in production: *"Mach bitte das Amaran-Licht an."* → `turn_on
  light.strahler_tripod` → *"Das Amaran-Licht ist an."*, while the actual target
  (`switch.wintergarten_amaran_60x_s_power`) stayed off.

  The handler's allowlist was working as designed — it blocks the wrong *write*, not
  the wrong *target*. `homeassistant-skill.md.j2` now forbids entity substitution,
  requires naming the entity actually acted on, requires reporting `access denied`
  verbatim instead of retrying against another entity, and forbids treating
  `Changed states reported: 0` as a confirmation. Candidate discovery is no longer
  hardcoded to `--domain light`, which is what steered the agent toward the writable
  domain in the first place.

  A second rule was added after the first fix was verified in production: the agent had
  stopped substituting, but still answered *"das Amaran-Licht ist in Home Assistant
  nicht vorhanden"* after searching only `--domain light`. The device exists as
  `switch.wintergarten_amaran_60x_s_power`; German names a smart plug driving a lamp a
  *Licht* regardless of its HA domain, so words in the request are not domain hints.
  Claiming absence now requires an unfiltered `list` in the same turn.

### Changed

- Bumped pinned upstream versions across the collection: Traefik 3.5.3 -> 3.7.9,
  Navidrome 0.58.5 -> 0.63.2, sops 3.8.1 -> 3.13.3, age 1.1.1 -> 1.3.1, Neovim
  0.11.6 -> 0.12.4, lazygit 0.59.0 -> 0.63.1, nvm v0.39.7 -> v0.40.6, and the
  Python interpreter pins for `homeassistant_deploy`, `wagtail_deploy`,
  `voxhelm_deploy`, and `voxhelm_remote_worker_deploy` to 3.14.6.

  `navidrome_checksums` was updated in the same change as `navidrome_version` —
  the map is keyed by architecture but not by version, so a version bump alone
  would fail the download against the previous release's SHA256. The comment
  above it now says so. Traefik's own `traefik_checksum` default is empty, but
  ops-control pins a bare checksum for `heis` that rides on this role's
  `traefik_version`; that is updated alongside.

  Traefik 3.6/3.7 breaking changes were reviewed: the Kubernetes Gateway API and
  CRD changes do not apply here (file provider only). Of the rest, HTTP/1 CONNECT
  now returns 501, `basicAuth` with an empty users list makes the router 404
  rather than 401, and StripPrefix rejects requests whose normalized path differs
  from the stripped path. Every `basicAuth` middleware in this collection is
  rendered inside an `enabled` guard, so none can produce an empty users list.

- `navidrome_deploy` now renders `EnableSharing` explicitly, defaulting to
  `false` via the new `navidrome_enable_sharing` variable. Navidrome 0.63.0
  flipped the upstream default to `true`, so upgrading without this would have
  silently started handing out public share links on a service that is otherwise
  reachable only behind basic auth. Note that 0.60.0 also made `go-taglib` the
  default metadata extractor, which triggers a full library rescan on first
  start; `Scanner.Extractor` can be set back to `legacy-taglib` if that misreads
  tags.

### Fixed

- `mastodon_deploy` now actually applies `mastodon_nvm_version`. The nvm checkout
  used `ansible.builtin.git` with `update: false`, which pins the requested
  version only on the initial clone — on a host that already had nvm, changing
  the variable reported no change and silently kept the old tag. Bumping the pin
  to v0.40.6 and deploying left staging on v0.39.7, with the play reporting
  `failed=0`. The checkout now runs with `update: true`, so the pinned tag is
  what is on disk after every run. A version pin that quietly does nothing is
  worse than no pin, because the inventory reports a version the host is not
  running.

### Removed

- `nyxmon_deploy` no longer declares `nyxmon_node_version`. It was set to `20`
  and described as "if frontend build is needed", but nothing in the collection
  or in ops-control ever read it — the role does not install Node at all. It
  surfaced as an end-of-life finding (Node 20 went EOL 2026-04-30) for a runtime
  that is never provisioned, so the fix is deletion rather than a bump.

### Added

- New `systemd_unit_masks` role: masks systemd units that can never succeed on a
  host (a driver init script with no matching hardware, a service for an absent
  device) and clears any `failed` state they left behind. Masking a unit that has
  already failed does **not** reset it, so without the reset a permanently
  non-empty `systemctl --failed` hides genuinely new failures. Units are stopped
  before masking, because masking a running unit leaves it running and systemd
  then refuses to act on it. Unit names must include the type suffix — a bare
  name silently resolves to `<name>.service`, which makes it easy to mask
  something other than intended — and a unit listed for both masking and
  unmasking is rejected rather than resolved by ordering. The failed-state reset
  is conditional on `systemctl is-failed`, so repeat runs report no change.

### Fixed

- `ssh_forwarding_identity` now keeps the exact original null-identity creation intent
  authoritative when restarting an absent-companion creation. It reattests that binding and
  both canonical/staging names before allocation, after allocation durability, after binding,
  after canonical publication, and through every intent-retirement fsync. Check mode repeats
  the same absent-companion attestation immediately before returning its snapshot-only plan;
  canonical or staging creation/substitution at any boundary is preserved and fails closed.
- `ssh_forwarding_identity` creation reconciliation now treats a null-identity intent as
  authority only when both its canonical and named staging private-key entries are absent.
  Canonical-only, staging-only, and same- or different-content dual-entry snapshots are
  preserved unchanged and fail closed in check and real mode without key derivation or
  public-key publication.
- `ssh_forwarding_identity` now separates crash-recovery inspection from mutation so
  present-state check mode can validate a recoverable creation intent/staging key and derive
  its prospective public key without any rename, exchange, quarantine, intent persistence,
  or directory fsync. Authenticated cleanup keeps descriptor authority for the quarantined
  inode and requires the original private, public, or creation-intent canonical name to stay
  absent immediately after exclusive rename and after every retirement fsync; concurrent
  recreations are preserved and fail closed.
- `ssh_forwarding_identity` now retains public-key and creation-intent publication
  descriptors and exact bytes through old-name retirement, then reattests the canonical
  inode, descriptor identity, and bytes after cleanup's final directory fsync. Creation
  reconciliation carries the original exact `RegularBinding` through every update and
  clear; updates return the replacement binding, and no transition fresh-reads a different
  valid intent as authority. Canonical substitution immediately before update or clear,
  and public-key/intent substitution during retirement cleanup, are preserved fail closed.
- `ssh_forwarding_identity` absent-state cleanup now carries the full inode identity returned
  with each exact validated private/public byte sequence into quarantine cleanup. It never
  authorizes removal from a fresh pathname stat, so substitution between read and cleanup is
  preserved and rejected.
- `ssh_forwarding_identity` cleanup/removal now pins the exact validated inode across a
  descriptor-relative exclusive source-to-quarantine transition, fsyncs, and reattests the
  moved descriptor/path identity including durable `st_ctime_ns` records. A precreated
  target or post-verification source swap fails closed; because no portable exact-handle
  unlink is available, authenticated quarantines are retained instead of risking
  verify-then-pathname-unlink.
- `ssh_forwarding_identity` now inspects canonical private/public keys, creation intent,
  and recovery staging state only through nonblocking, close-on-exec, no-follow descriptors,
  with immediate regular/single-link/owner/mode and stable descriptor/path identity checks.
  FIFOs, sockets, devices, directories, hard links, and replacements fail promptly. Private
  key and creation-intent publication now use descriptor-relative exclusive rename rather
  than hard links, eliminating link-count-two crash states while preserving exclusive,
  non-rotating restart recovery.
- `ssh_forwarding_identity` now creates a first private key through a random
  descriptor-relative staging name and durable owner-only creation intent. It uses an
  EINTR-aware write-all loop, rejects zero progress, fsyncs and read-verifies the complete
  key, re-derives Ed25519 public material, binds the exact staging inode, and installs the
  canonical name exclusively before parent-directory fsync. Restart completes only a
  bound, content-verified staging inode; an unbound or replaced temporary and any partial
  canonical key are preserved fail closed. Controlled partial/zero/`ENOSPC` failures clean
  only the exact attested temporary, while existing canonical keys remain non-rotating.
- `ssh_restricted_forwarding_account` now records a root-only UID/GID identity
  contract and attests exact passwd, primary-group, shell, canonical home, ownership,
  and no-follow hierarchy state before absent-state policy or account mutation. Partial
  removal resumes reject recycled UID/GID names, always scan the contracted UID, and fail
  closed on unreadable process state until home and contract are gone. Linux `statx` mount
  IDs now pin `/home` before accepting the managed home, so bind/tmpfs filesystems mounted
  directly at the canonical home are refused and preserved alongside same-device bind mounts,
  tmpfs, and other nested filesystems. The IDs now preflight the complete tree under the
  stable absent transaction lock before sshd policy, authorization, passwd, contract, home,
  or content mutation, and are rechecked during traversal. Actual absent-transaction
  Molecule cases prove direct and nested mounts preserve every managed remnant. Real absent
  runs retain mandatory contracted-UID process scanning; read-only check mode reports
  active restricted sshd processes as a deferred post-shutdown gate because it intentionally
  does not boot out the healthy client. The role removes accounts without recursive
  `userdel` and descriptor-removes only the pinned canonical managed home, preserving
  drifted or repurposed accounts and unrelated data.
- `vaultwarden_deploy` no longer renders a separate Traefik WebSocket router and
  service pointing at `WEBSOCKET_PORT`. Upstream Vaultwarden removed the
  standalone WebSocket listener and serves live sync at `/notifications/hub` on
  the main Rocket port, so that router pointed at a port nothing listened on —
  and because its rule was longer than the main router's, it won on priority and
  answered `502` for every live-sync request. `WEBSOCKET_ADDRESS` and
  `WEBSOCKET_PORT` are gone from the env template and
  `vaultwarden_websocket_port` from the defaults; `vaultwarden_websocket_enabled`
  remains and still gates `WEBSOCKET_ENABLED`.

### Added

- Added `ssh_forwarding_identity` and `ssh_restricted_forwarding_account` for
  unattended, non-rotating Ed25519 forwarding identities and dedicated Linux
  accounts constrained to one local-forward destination. The server role uses
  restricted authorized-key options plus a validated sshd `Match User` block,
  validates candidate policy before mutation, accepts only canonical managed-file
  pre-state, and restores managed bytes, absence state, and canonical metadata after
  failed validation or reload. Rollback activation now requires a successful restored
  reload plus matching effective-policy attestation; timestamps, ACLs, and xattrs are
  explicitly outside rollback semantics. Present and absent account operations now
  share a non-expiring, explicitly authenticated server transaction holder, a durable
  unreleased marker that survives holder death, and monotonic fencing state that rejects
  obsolete workflows before mutation/finalization. The account-derived root-only recovery
  credential is now file- and directory-fsynced before marker publication, survives `/tmp`
  loss/reboot, remains recoverable across every takeover power-loss boundary, and is removed
  durably with the marker after authenticated release. Stale recovery authenticates that
  stable credential, attests holder death, and advances fencing. Candidate sshd
  construction rejects source symlinks and mutates only descriptor-attested temporary-tree
  targets. Identity
  management traverses every component from `/` through pinned `O_NOFOLLOW|O_DIRECTORY`
  descriptors and keeps parent creation plus key writes descriptor-relative, preventing
  ancestor/parent symlink substitution from redirecting mutation. It never manages root
  authorized keys.
- New `vaultwarden_maintenance` role: an ingress deny switch for a maintenance
  window. `vaultwarden_maintenance_state: present` writes a high-priority
  Traefik router fronted by an `ipAllowList` middleware, so sources outside the
  allow list get `403` while allowed sources still reach Vaultwarden — which is
  what gives an operator a verification path during a freeze. `absent` removes
  the file; Traefik watches the dynamic directory, so no restart is needed. One
  router covers live sync too, since Vaultwarden serves it on the main port.
  The role owns **only** the file named by `vaultwarden_maintenance_filename`
  and refuses to run if that name equals
  `vaultwarden_maintenance_archived_router_filename`. Both are plain filenames,
  never paths, so no caller value can normalise into the archived router file.
  That guard is load-bearing: the Echoport Vaultwarden backup archives the deploy role's
  router file and its restore writes it back without reloading Traefik while
  gating only on a loopback health check, so a deny state stored there would be
  silently reinstated by any restore from a backup taken during a freeze. Every
  run verifies the result — no non-loopback listener on the Vaultwarden ports,
  plus an external probe expecting `403` while frozen and a reachable status once
  restored. The role deliberately contains no package, repository, or service
  tasks and defines no handlers.
- `vaultwarden_deploy` can now pin and hold its packages:
  `vaultwarden_package_version`, `vaultwarden_web_vault_package_version`, and
  `vaultwarden_packages_hold`. Versions default to empty and the hold defaults
  to unmanaged (`~`), so existing behaviour is unchanged and an externally
  applied hold survives an ordinary deploy run untouched. Both versions must be pinned
  together or not at all, because the apt flag that permits moving a held
  package applies to the whole invocation. When pinned, apt is permitted to move
  the held packages directly rather than the
  role unholding and re-holding around the install: there is no window for a
  concurrent apt process, no spurious change report when the pinned version is
  already installed, and no check-mode failure from simulating an install
  against a still-held package. Because the hold itself can only be applied
  after the install, the role then reads the installed versions back and fails
  if they are not the requested pins. The role also reports the
  installed deb versions, which is the value a compatibility or migration gate
  has to record per host.

- `voxhelm_deploy` gained an optional Kokoro ONNX TTS backend and automatic
  de/en language routing, both disabled by default and independently toggleable
  (`voxhelm_tts_kokoro_enabled`, `voxhelm_tts_language_routing_enabled`, both
  `false`). Enabling Kokoro installs `espeak-ng` via Homebrew and downloads the
  checksum-pinned model artifacts (`voxhelm_kokoro_artifacts`: official Kokoro
  v1.0 full + int8, `voices-v1.0.bin`, and the German "Martin" fine-tune) into
  `voxhelm_kokoro_model_dir` with idempotent, `sha256`-verified `get_url`
  downloads. The single enable flag gates BOTH the `kokoro` uv extra and Kokoro
  model registration: when `false`, the env template renders no `VOXHELM_KOKORO_*`
  variables, so Kokoro voices are neither advertised nor dispatchable.
  `voxhelm_kokoro_models` (voice-key → `model_file`/`voicepack_file`/
  `voicepack_key`/`phoneme_language`) renders into `VOXHELM_KOKORO_MODELS`, with
  optional `voxhelm_kokoro_default_voice` and `voxhelm_espeak_library`
  (default `/opt/homebrew/lib/libespeak-ng.dylib`). Routing gates the `routing`
  uv extra and renders `VOXHELM_TTS_LANGUAGE_ROUTING` /
  `VOXHELM_TTS_LANGUAGE_VOICES` (`voxhelm_tts_language_voices`). `validate.yml`
  asserts models are configured and complete when Kokoro is enabled, referenced
  files are provisioned as artifacts, a set default voice is a configured key,
  and a language mapped to a `kokoro-*` voice cannot diverge from Kokoro
  enablement.

- Added `daybook_photos_offload_deploy`, a quiesce-first macOS Aqua user
  LaunchAgent for the pinned, clean-checkout Daybook Photos discovery
  reconciler. It owns private runtime state and owner-only private logs, emits
  aggregate-only scheduled output, uses a root-owned exact checkout plus a
  checkout-local sanitized uv environment, rejects unsafe Git state and path
  substitutions, supports an exact-pin isolated controller Git bundle for
  private source, installs locked dependencies without editable source writes,
  uses a login-style macOS service-user transition, fails closed during
  activation, and runs at 08:10 and 20:10
  without mounting Fractal or mutating Photos.

- `homeassistant_deploy` gained an optional Custom Conversation bridge
  (`homeassistant_custom_conversation_enabled`, default `false`). It installs the
  pinned, checksum-verified `michelle-avery/custom-conversation` component
  (v1.6.1) into `custom_components/`, restarts Home Assistant before running the
  config flow, and provisions the `custom_conversation` config entry idempotently
  against an OpenAI-compatible Chat Completions endpoint (new vars:
  `_version`, `_sha256`, `_provider`, `_base_url`, `_api_key`, `_model`,
  `_instructions`, `_request_timeout`, `_canary_text`). The role owns the domain:
  zero entries → create, one → update data/options in place (base-URL and token
  changes included), more than one → hard fail; disabling removes the entry and
  its stored token. Every token-carrying task runs with `no_log: true`. The
  resolved `conversation.*` entity is gated on registry presence, a
  non-`unavailable` state, and a `conversation/process` canary, and Assist
  pipelines can reference it through the new
  `conversation_engine: "auto:custom_conversation"` token (falling back to
  `conversation.home_assistant` with a warning when the bridge is disabled).
  Provisioning is fully desired-state: clearing
  `homeassistant_custom_conversation_instructions` back to `""` restores the
  component's default prompt (and stays idempotent afterwards), and create,
  update, and remove of the config entry are reflected in the task's Ansible
  changed status. The component validates credentials with a best-effort
  `GET <base_url>/models`, so a Chat-Completions-only endpoint that does not
  serve `/models` (e.g. the OpenClaw gateway) works without a compatibility
  proxy.

- `openclaw_deploy` gained `openclaw_gateway_http_chat_completions_enabled`
  (default `false`) to toggle the gateway's OpenAI-compatible Chat Completions
  endpoint (`gateway.http.endpoints.chatCompletions.enabled`). The flag is
  written explicitly on both config paths — the individual-variables build and
  the runtime patch applied to an existing/supplied config — so an explicit
  `false` overrides a stale `true` already present in a supplied config instead
  of leaving the endpoint enabled.

- New `dns_metrics_endpoint` role: exposes authoritative-DNS health as an authenticated
  JSON endpoint (`/.well-known/dns`, port 9107 by default) for Nyxmon `json-metrics`
  checks, following the `backup_metrics_endpoint` pattern — a root systemd timer
  (`dns-metrics-collector`) writes JSON to `/var/lib/dns-metrics/dns.json` and an
  unprivileged `dns-metrics-endpoint` service serves it with basic auth and staleness
  metadata. It probes nameservers **by address** (so it works before and independently
  of registrar glue) and exercises the full matrix of nameserver × address family ×
  transport × zone: one aggregate "DNS is up" boolean hides a half-dead nameserver, and
  a v6-only or TCP-only failure is invisible to a v4/UDP probe while still breaking real
  resolvers (TCP is mandatory for authoritative servers per RFC 7766). SOA queries use
  `+norecurse` and **require the `aa` flag** — a bare serial comparison can pass against
  a server that is not authoritative at all, because a misconfigured or recursive `named`
  can fetch the SOA from elsewhere and report a matching serial while serving nothing of
  its own. The role also compares SOA serials per zone across all nameservers and asserts
  that a recursion-desired query for a foreign name is `REFUSED`, catching an
  open-resolver regression. An unreachable endpoint is reported `unknown` rather than
  `failed` for the open-resolver probe, so one outage cannot also raise a bogus security
  alert.

  Collector-side IPv6 loss is handled honestly: the collector asks the kernel for a route
  and a global-unicast (`2000::/3`) source address via `connect()` on an unconnected UDP
  socket — no packets are sent, and Tailscale's ULA addresses are rejected because they
  prove nothing about internet reachability. When `meta.collector_ipv6_capable` is false
  the v6 results are `skipped` rather than `failed` and excluded from
  `summary.overall_ok`, while `summary.ipv6_tested` goes false so untested v6 cannot
  silently rot: "ns2 v6 is broken" and "I could not test v6" stay distinguishable.
  Optional per-nameserver `families`/`transports` overrides narrow the matrix for a known
  limitation of the collector's own vantage point; excluded cells stay visible as
  `skipped` with a `skip_reason`.

  All values a check rule needs sit at fixed, wildcard-free paths (`summary.*`, `meta.*`,
  `nameservers.<id>.*`) because Nyxmon's path resolver supports only `$.field.subfield`
  and list indices; `zones` is a list rather than a dict keyed by zone name, since zone
  names contain dots and the resolver splits on dots with no escaping. Every `*_ok`
  boolean means "nothing tested failed" and is paired with a `*_tested` flag, and
  `overall_ok` additionally requires that something was actually tested so an all-skipped
  run cannot look healthy. Probing uses `dig` from `bind9-dnsutils` (installed by the
  role) rather than a new Python dependency, so the check and its manual reproduction are
  identical; queries run concurrently and a single unreachable endpoint degrades only its
  own result. Defaults are RFC 5737/RFC 3849 documentation placeholders — real
  nameservers, addresses and zones come from the control repository.

  Documented in `roles/dns_metrics_endpoint/README.md` (why each check exists, the
  suggested Nyxmon rule paths, the exact `dig` commands to reproduce a red check by
  hand, and the HTTP status codes), rendered in the role catalog under deployment roles.

- `bind_authoritative_deploy` supports transfer-backed (secondary) zones. Zone types
  listed in the new `bind_zone_transfer_backed_types` variable (default
  `[slave, secondary]`, BIND's two names for the same thing) get a `primaries { ... };`
  block rendered from a required non-empty per-zone `primaries` value (a list, or a single
  address as a bare string; a mapping is rejected), resolve a relative
  `file` against `bind_working_dir` (`/var/cache/bind`, where named may write and the
  Debian AppArmor profile permits it), and are neither required nor copied from the
  controller. The exemption is an explicit allow-list rather than a `!= master` test, so
  `primary` and `hint` zones keep their controller-managed zone files; rendering the
  existing all-`master` zone lists is byte-identical to before.

- `bind_authoritative_deploy` renders TSIG keys. `bind_tsig_keys` (list of
  `{name, algorithm, secret}`, `algorithm` defaulting to `hmac-sha256`) is written as
  `key { ... };` stanzas to `bind_tsig_keys_file`
  (`/etc/bind/named.conf.keys`) at `bind_tsig_keys_mode` (`0640`, root:bind) — stricter
  than the `0644` used for the rest of the config, because a TSIG secret must not be
  world-readable. The rendering task is `no_log: true`, so the secret reaches neither
  Ansible output, nor the check-mode diff, nor the FastDeploy UI, and validation rejects
  an empty or `CHANGEME` secret. `named.conf` includes the file ahead of every other
  include so keys are defined before they are referenced; the include and the file are
  omitted entirely while `bind_tsig_keys` is empty, keeping `named.conf` byte-identical
  for existing callers. Key *names* are referenced from the already-verbatim
  `primaries` / `allow_transfer` / `extra_config` entries, so no new role code is
  needed for that side of it. Note when writing those entries that a BIND
  address-match list is a first-match-wins list of *alternatives*:
  `allow-transfer { 198.51.100.20; key "xfer"; };` permits a keyless transfer from
  that address **and** permits any key holder from anywhere. Requiring address *and*
  key needs the nested-negation idiom
  `allow-transfer { !{ !{ 198.51.100.20; }; any; }; key "xfer"; };`, written inline —
  a named `acl` cannot be supplied through `bind_extra_options`, whose lines render
  inside the `options { }` block where a top-level `acl` is illegal. The role README
  documents both, plus a worked primary/secondary example and the matching
  `also-notify { <addr> key "xfer"; };` without which `NOTIFY` is silently dropped
  and the secondary degrades to its SOA refresh timer. The keys file is checked with
  `named-checkconf` in its own right — rotating a secret leaves `named.conf`
  byte-identical, so that file's own validation never re-runs — which also means
  `secret` must be valid base64, as `tsig-keygen` emits. Emptying `bind_tsig_keys`
  deletes the keys file rather than leaving retired key material readable on disk.

- `bind_authoritative_deploy`'s post-deploy SOA check now uses `dig +norecurse` and
  requires the `aa` flag in addition to `status: NOERROR`, so a host running with
  recursion enabled cannot resolve the SOA from the public internet and mask a zone that
  failed to load. It retries `bind_verify_retries` times (default 12) with
  `bind_verify_delay` seconds (default 5) in between so a secondary's first zone transfer
  being in flight does not fail the run.

### Fixed

- `bind_authoritative_deploy` now flushes handlers before verification. Previously the
  `reload bind` handler ran at the end of the play, i.e. after `verify.yml`, so the SOA
  check inspected a named still serving its previous configuration. On an established
  server this was invisible; on a first install it failed hard, with named answering a
  root referral because none of the configured zones had been loaded yet.

### Added

- `mastodon_deploy` now installs `libvips-dev` and `libvips-tools`. Mastodon 4.6
  dropped ImageMagick support and requires libvips for media processing.
  `imagemagick` is retained so refs older than 4.6 stay deployable.

- `daybook_sessions_deploy` now manages a strict private-control supplied public
  repository policy and a content-free identity-migration operator rail. The
  rail prepares an owner-only crash-durable no-replace plan from exact draft GETs, preserves
  that plan across partial reruns, runs Daybook's separate dry-run/apply paths,
  and verifies the resulting attestation without exposing post content,
  credentials, or policy in argv/logs.

### Fixed

- `echoport_backup` restore runners for `homepage` and `python_podcast` (both the
  production-DB and staging variants) now stop the Django Tasks `db_worker` unit
  alongside the web service before dropping the database, and start it again
  afterwards. Previously only `SERVICE_NAME` was stopped, so the worker kept
  polling its task table every 5 seconds straight through `dropdb`/`createdb`,
  crashed with `relation "django_tasks_database_dbtaskresult" does not exist`,
  and needed a systemd restart to recover. The crash surfaced in Sentry as the
  misleading `InternalError: current transaction is aborted, commands ignored
  until end of transaction block`, because `django_tasks_db`'s `@retry()` re-runs
  `get_locked()` inside the same already-aborted transaction. Auxiliary units are
  configurable via `<prefix>_aux_service_names` and default to
  `<service>-db-worker`; units that do not exist on the restore host are skipped,
  so sites without a worker are unaffected. A trailing `.service` is stripped
  from the configured service name first, because the production-DB register
  playbooks pass `homepage.service` while the staging ones pass `homepage`.
  A failed probe raises instead of reporting the unit absent, so a transient SSH
  error cannot silently skip the guard.

- `wagtail_restore` gained the same protection: `wagtail_restore_extra_systemd_units`
  (default: the `wagtail_deploy` db_worker unit when `wagtail_db_worker_enabled`
  is true, otherwise empty) is stopped before the drop and started after
  migrations complete.

- `wagtail_deploy` now renders `DJANGO_SENTRY_ENVIRONMENT` / `SENTRY_ENVIRONMENT`
  from the new `wagtail_django_sentry_environment` variable (default
  `production`). Staging deployments share `config.settings.production`, and the
  Sentry SDK labels everything `production` when no environment is given, so
  staging incidents were indistinguishable from real production ones.

- `homeassistant_deploy` Custom Conversation provisioning: the config-flow
  helper no longer rewrites a loopback `homeassistant_api_url` to the default
  route IP before driving the flow. That rewrite discarded a configured scheme,
  port, or path and broke Home Assistant instances bound only to loopback or
  fronted by a localhost TLS/reverse proxy; the validated `homeassistant_api_url`
  is now used verbatim (matching the Wyoming integration). A helper failure now
  surfaces the sanitized diagnostic it wrote to its result file via a block
  `rescue`, instead of aborting on the `no_log` command task and leaving the
  operator with a censored failure. The reconfigure flow request drops the inert
  top-level `source` field and starts the flow the way Home Assistant's own
  Reconfigure button does (integration domain as handler plus the existing
  `entry_id`, which the config REST view promotes to a reconfigure context).

- `mastodon_deploy` no longer aborts when the Node version changes between
  deploys. `nvm version` exits 3 and prints `N/A` for a version that is not
  installed yet, which failed the resolve task before the install task's `N/A`
  gate could run, making the gate unreachable. Both resolve tasks now use
  `failed_when: false`, and the follow-up check reports rc/stdout/stderr instead
  of passing an empty result through to the runtime path facts.

### Security

- The Monday-after weeknote identity epoch now defaults absent and can render
  only when a clean pinned checkout verifies the exact private seed, mode-0600
  plan/attestation, and root-owned activation proof. Deploy and operator paths
  disable/unload before mutation and verify the exact installed rail; the
  scheduled launcher rechecks exact HEAD/root/cleanliness and uses an isolated
  frozen environment; both launchers verify the environment against a
  root-controlled checksum before sourcing it. Ordinary role deployment rejects activation; only a
  same-play fresh apply plus dedicated activation task can enable. All system
  deployments require managed launchd state and quiesce the exact unit before
  shared mutation; ordinary
  installs remain disabled/unloaded and cannot PATCH
  django-cast. Identity recovery requires django-cast commit `80b80928` and its
  content-free `previous_revision_id` contract.

### Added

- `logyard_deploy` can report systemd unit state for log producers through the
  health endpoint via the new `logyard_health_units` variable (default `[]`), so a
  dead producer is detected directly instead of being inferred from ingest going
  quiet. Each `{id, unit}` entry is published as `units.<id>` with `exists`,
  `load_state`, `active_state`, `sub_state` and `result`. `exists` is derived from
  `LoadState` rather than the exit code, because `systemctl show` exits 0 for units
  that do not exist. Unit state does not feed into the top-level `status` field.

### Fixed

- `logyard_vector_deploy` now renders a Loki sink that is valid under Vector 0.57's
  template confinement rules. Vector 0.57 rejects templated sink values without a
  literal static prefix, which made `vector.service` fail `ExecStartPre` with
  `exit 78/CONFIG` after an unattended upgrade from 0.56, silently stopping both
  journald log ingest and host-metric delivery from the same Vector instance. The
  constant `host`, `source_type`, and `environment` labels are now emitted as static
  literals, and the new `logyard_vector_allow_unconfined_label_templates` variable
  (default `true`) sets `dangerously_allow_unconfined_template_resolution` for the
  remaining per-event `service` and `level` labels. Label values are unchanged, so
  existing Loki selectors and dashboards keep working.
- `daybook_sessions_deploy` now accepts both the legacy boolean and current
  word-form `launchctl print-disabled` output when converging the dedicated
  weeknotes reconciler, preserving the disabled-by-default install gate on
  newer macOS releases.

### Security
- `weeknotes_home_deploy` now protects public-source HTTPS requests with shared
  Traefik Basic Auth while a higher-priority, validated RFC1918/Tailnet router
  preserves Studio's independent bearer-auth API calls. The role strips Basic
  credentials before proxying, redirects plain HTTP without reaching Django,
  and fails closed when the front-door credential is absent or malformed.
- `weeknotes_home_deploy` now requires and renders a dedicated bearer token for
  the private steering read/fold API, allowing Macmini and the Studio reconciler
  to share one managed secret instead of exposing those endpoints anonymously.

### Added
- `daybook_sessions_deploy` can install a dedicated Mac Studio draft-only
  weeknotes reconcile LaunchDaemon at 07:40 and 19:40 local time. The distinct
  unit, logs, mode-0600 environment, local state, and auth-only pi directory are
  managed independently from session shipping and quote classification; launchd
  activation defaults to disabled/unloaded and deployment never runs reconcile.
  OAuth is seeded once, preserves Pi refreshes on normal reapplication, and can
  be replaced only through explicit unloaded-unit rotation.

### Fixed
- `openclaw_deploy` now accepts bounded weeknotes write payloads up to 4,000
  characters by default, so normal long-form voice-note transcriptions are not
  rejected by the journal handler's previous 500-character ceiling.
- `openclaw_deploy` now installs version-pinned Codex plugins over host
  networking, avoiding npm resolution failures on hosts where Docker's
  transient default-bridge DNS cannot reach the configured resolver.
- `daybook_sessions_deploy` now configures Daybook's external quote lifecycle
  JSON state alongside the unused/used Markdown locations, exposes all three to
  classifier and handoff environments, and validates distinct safe locations on
  one compatible local or S3 backend without contacting storage; browser
  executable/profile validation remains local and strict.
- `openclaw_deploy` now writes managed `SOUL.md` and optional `USER.md` content
  into the active agent workspace instead of the OpenClaw state-directory
  root, can explicitly manage Telegram preview/tool-progress visibility, and
  manages DM session scope so shared bot deployments can isolate each sender's
  conversation history.
- `openclaw_deploy` now preserves the required `gateway.mode: "local"` setting
  in seeded and patched gateway configurations, preventing forced config
  renders from leaving current OpenClaw gateways in a restart loop.
- The Heis production Echoport runner now quotes compound remote SSH commands
  as a single argument, preventing operators such as `&&` from executing on
  the macmini backup runner instead of the production host.
- `paperless_deploy` now rejects missing or malformed release checksums and
  extracts new releases into a staging directory before switching the stable
  application symlink, preserving the working release if extraction fails.
- `marina_deploy` now excludes SQLite database and WAL/SHM runtime files from
  source rsync, preventing staging deploys from overwriting live Wagtail content
  with a controller-local `db.sqlite3`.
- `heis_deploy` now installs its host-side prerequisites and excludes SQLite
  database/WAL/SHM files from source rsync so code deploys preserve production
  content alongside the already-persistent media directory; page setup and
  content seeding can now be disabled independently for production, and
  optional canonical-host redirects support production alias domains.
  HTTP and TLS routers can now use separate host rules so an alias with pending
  DNS does not block ACME certificates for otherwise valid production names.

### Breaking Changes
- **Python 3.14+ required** - Dropped support for Python 3.8–3.13
  - Supports Python 3.14 (N-2 policy currently aligns with the latest stable release)
  - All roles and testing infrastructure now require Python 3.14+
  - Update your systems before upgrading to this version
- **ansible-core 2.20+ required** - Dropped support for Ansible 2.9-2.14
  - ansible-core 2.20 is the minimum version compatible with Python 3.14+
  - Update your Ansible installation before upgrading

### Added
- `openclaw_deploy` can now restore source-controlled workspace skills from
  controller-local files, including executable support scripts, while
  preserving interactive unmanaged skills and refreshing cached session skill
  snapshots whenever managed skill content changes.
- `daybook_sessions_deploy` now wires the browser-backed Archive quote
  classifier with validated Obsidian lifecycle files, a Helium executable,
  headless browser timing controls, a guarded dedicated profile, locked
  Playwright installation without bundled Chromium, redacted environment
  shipping, no-fetch pinned-checkout validation, real path/ownership checks,
  and a background/throttled launchd schedule. Headed mode is restricted to an
  Aqua user LaunchAgent.
- `heis_production_backup.py.j2`, a locked service-owned Echoport/FastDeploy
  runner for remote SQLite plus media backup and restore of a dedicated Heis
  production host. It uses exact immutable remote targets, bounded subprocesses,
  systemd restart watchdogs, short host-local backup snapshots, and automatic
  DB/media safety rollback for restores. Watchdogs remain armed until every
  service is proven active; restore runs migrations and requires an exact local
  HTTP 200 through Django's HTTPS proxy path before accepting the new data.
- `weeknotes_home_deploy` role to deploy daybook's `weeknotes.home` Django
  steering-comments service with PostgreSQL provisioning, uv-managed
  dependencies, systemd/gunicorn, Traefik routing, and a `/healthz` check.
- `weeknotes_home_deploy` can render a `WEEKNOTES_HOME_CAST_BASE_URL`
  environment setting so the service can link delivered drafts back to
  django-cast edit and preview pages.
- `daybook_sessions_deploy` role to validate a macOS `uv` runtime, install a
  pinned Daybook checkout, sync it with `uv`, install `trufflehog`, and run
  `daybook sessions ship` as a periodic launchd job using
  private-control-repo supplied MinIO credentials.
- `daybook_sessions_deploy` can skip git remote fetches for private,
  pre-staged Daybook checkouts while still checking out a pinned ref.
- `daybook_sessions_deploy` now supports user LaunchAgent installs for
  laptop-style macOS hosts that do not expose passwordless sudo or root SSH.
- `zfs_usb_replication` now persists drive-present success/failure separately
  from clean missing-drive skips, and `backup_metrics_endpoint` exposes stable
  policy-aware USB attempt, capacity, and protection-freshness health for alerting.
- `zfs_usb_replication` can now apply guarded pre-sync age retention to managed
  target-only snapshots while preserving every source-present common anchor and
  waiting for asynchronous ZFS frees before receiving new data.
- `delve_deploy` now installs an optional service-owned Discovery reviewed RSS
  collector oneshot/timer, passes bounded non-secret collector defaults including
  a 100-source run cap and 2-8 concurrency range, and documents the rollout
  boundary (no feed-pack seeding in the public role).
- `mail_relay_deploy` now supports
  `mail_relay_postgrey_whitelist_clients_extra` for managed postgrey whitelist
  entries in addition to the role defaults.
- `voxhelm_deploy` can now put transcription jobs into `remote_pull` mode with
  validated worker-token and shared S3 artifact settings, while
  `voxhelm_remote_worker_deploy` installs a pinned public-PyPI
  `voxhelm[diarization]` worker on macOS and runs it under launchd.
- `voxhelm_ingress_deploy` now blocks `/v1/internal` by default at the Traefik
  edge, with an explicit separate allowlist for deliberately private worker
  routes.
- `tailscale_metrics_endpoint` role to expose authenticated Tailscale login
  state and node-key expiry JSON for Nyxmon monitoring.
- `voxhelm_deploy` now supports production pyannote speaker diarization wiring,
  including optional `uv sync --extra diarization` installation, protected
  Hugging Face token env rendering, and validation when the backend is enabled.
- `nyxmon_storage_exporter` now caches successful ZFS pool samples and reuses them during quiet-hours pool skips, keeping capacity JSON paths stable for monitoring while marking cached values explicitly.
- `os_apt_maintenance` endpoint responses now expose `$.meta.state_reboot_required` so operators can inspect the reboot-required value from the durable state file separately from the live marker.
- `os_apt_maintenance` role for host-local apt update/dist-upgrade/autoremove/autoclean timers with durable JSON state and an optional authenticated Nyxmon endpoint.
- `wagtail_deploy` now supports a stable `wagtail_db_worker_id` and passes it to Django Tasks `db_worker --worker-id`, allowing each deployed site to run a distinct database-backed task worker
- `wagtail_deploy` now includes a `redirect-www` Traefik middleware that strips the `www.` prefix via regex redirect (302), applied unconditionally to the HTTPS router
- `headless_mode` role to persist hosts on a non-graphical systemd target and disable running display-manager services without requiring a reboot
- `paperless_deploy` can now promote existing Paperless users to active staff superusers during deploy via `paperless_existing_superusers`
- Takahe lifecycle roles: `takahe_shared`, `takahe_deploy`, `takahe_backup`, `takahe_restore`, and `takahe_remove` with systemd services, nginx caching/accel proxy, Traefik routing, and PostgreSQL provisioning
- Mastodon lifecycle roles: `mastodon_shared`, `mastodon_deploy`, `mastodon_backup`, `mastodon_restore`, `mastodon_maintenance`, and `mastodon_remove` with rbenv+nvm runtimes, systemd services, Traefik routing, and backup/restore tooling
- `open_webui_deploy` and `open_webui_remove` roles to run Open WebUI via Docker Compose with Traefik routing, persistent storage, and optional basic auth
- `open_webui_venv_deploy` and `open_webui_venv_remove` roles for a uv-managed venv deployment with systemd, Traefik routing, and persistent data
- `zfs_syncoid_replication` role for scheduled syncoid replication with alert hooks and optional spindown script
- `zfs_usb_replication` role for USB-attached ZFS replication with device detection and optional alerts
- `minio_offsite_replication` role to pull MinIO archives from a remote host into offsite storage via systemd timer, rsync/SSH, and alert hooks
- `mail_offsite_replication` role to pull maildir + staged DB/config artifacts from a remote host into offsite ZFS storage with post-sync snapshots, status markers, and alert hooks
- `encrypted_volume_prepare` role to verify, unlock, and mount LUKS data volumes with keyfile support, UUID validation, crypttab/fstab wiring, and a validate-only dry run
- `nyxmon_backup` role for SQLite-safe snapshots with metadata, manifests, and automatic archive fetches
- `nyxmon_restore` role with staging validation, safety snapshots, rollback support, and service verification
- `ollama_install` role to install and run Ollama on macOS via Homebrew with launchd management
- `ollama_remove` role to unload launchd, remove the plist, and optionally remove data/logs, service user, and Homebrew package
- `docker_install` role to install Docker Engine + Docker Compose v2 (plugin) on Ubuntu via the official Docker apt repository
- `shell_basics_deploy` role to install fish, modern CLI tools (btop, bmon, sysstat/iotop, tealdeer, eza), set shell/editor defaults, and keep chezmoi current via upstream installer
- `snappymail_deploy` role to install SnappyMail from upstream archives (PHP-FPM + nginx), wire IMAP/SMTP defaults, persist data under `/mnt/cryptdata/snappymail`, and expose via Traefik
- ReadTheDocs integration with Sphinx and MyST parser
  - Browsable documentation at https://ops-library.readthedocs.io/
  - Furo theme for modern, clean appearance
  - Automated role documentation from individual READMEs
  - Just commands for documentation workflow (docs-build, docs-watch, etc.)
  - Documentation validation script (validate_docs.py)
- Migrated to uv for Python dependency management
  - Faster dependency resolution and installation
  - Simplified justfile commands using `uv run`
  - Removed manual venv activation requirements
- `homeassistant_deploy`, `homeassistant_backup`, and `homeassistant_remove` roles to cover the full lifecycle alongside the existing restore workflow
- `homeassistant_restore` role to validate archives, create safety snapshots, restore files, and roll back on failure
- FastDeploy backup & restore workflow:
  - `fastdeploy_backup` role with metadata-rich snapshots, disk-space validation, and archive support
  - `fastdeploy_restore` role with safety snapshots, permission fixes, health-check retries, and rollback automation
- Paperless-ngx suite: `paperless_deploy`, `paperless_backup`, `paperless_restore`, `paperless_postgres`, and `paperless_remove` roles for deployment, disaster recovery, and safe removal
- `redis_install` role to provision standalone Redis instances with optional authentication, persistence, and memory tuning
- `postgres_install` role to install PostgreSQL with manageable config, databases, users, and extensions
- `minio_deploy` role to provision MinIO with dual-router Traefik exposure, security hardening, and optional client bootstrapping
- `minio_remove` role to destructively remove MinIO with confirmation, optional data preservation, and Traefik cleanup
- Dynamic DNS support in `dns_deploy`, adding an opt-in LiveDNS updater with dedicated service accounts, timers, and IPv4/IPv6 support
- UniFi lifecycle roles: `unifi_deploy`, `unifi_backup`, `unifi_restore`, and `unifi_remove` (Mongo-auth aware, Traefik/HA integration, Justfile wiring, docs)
- Navidrome lifecycle roles: `navidrome_deploy`, `navidrome_backup`, `navidrome_restore`, and `navidrome_remove` (systemd binary install, Traefik basic auth, rescan timer, backup/restore tooling)

### Changed
- `openclaw_deploy` now installs the official Codex app-server plugin at the
  OpenClaw-matching release and supports an
  explicit canonical `auth.order.openai` profile list so deployments can require
  ChatGPT/Codex subscription OAuth for OpenAI agent turns without silently
  falling back to API-key billing. Documentation examples now use upstream
  stable `v2026.6.11`.
- `mail_relay_deploy` now documents IPv4-only relay mode and exposes
  `mail_relay_smtp_address_preference` so deployments can avoid or de-prioritize
  IPv6 while PTR/forward DNS is not aligned for outbound delivery.
- `voxhelm_remote_worker_deploy` now defaults to `caffeinate -ims` so macOS
  remote workers stay awake during long jobs while allowing display sleep.
- `tailscale_metrics_endpoint` now defaults node-key expiry alerts to warning
  inside 3 days and critical inside 1 day.
- `zed` role scrub timers can optionally wait for completion and run a post-scrub spindown hook
- Unit tests for OpenClaw metrics collector canary behavior and schema invariants (`tests/unit/test_openclaw_metrics_collector.py`)

### Fixed
- `daybook_sessions_deploy` now uses an explicit boolean assertion for the S3
  session path check, keeping the role compatible with stricter Ansible
  conditional validation during real macOS deploys.
- `daybook_sessions_deploy` now runs the Daybook checkout update under a login
  shell for the service user, avoiding macOS sudo current-directory failures.
- `openclaw_deploy` synthetic canaries now use fresh per-attempt session ids
  derived from the configured canary prefix and clean up generated canary
  session files after a bounded retention window, preventing reused canary
  history from causing context overflow, malformed markers, and retry lock
  contention.
- `openclaw_deploy` metrics collector now treats parseable nonzero
  `health --json` output as collected health data, so transient Telegram probe
  failures do not set `collector_ok=false`.
- `nyxmon_storage_exporter` now parses in-progress and paused ZFS scrub
  timestamps without confusing the weekday `Mon` for a completed-scrub `on`
  marker, avoiding false scrub-age warnings while a pool is actively scrubbing.
- Deploy roles now build stat assertion labels and error messages from the
  original loop item instead of registered result invocation metadata,
  restoring compatibility with newer ansible-core controllers.
- Collection metadata now declares the documented ansible-core 2.20+ runtime
  requirement.
- `wagtail_deploy` rsync deployments now exclude the managed `.env` file and collected `/staticfiles` directory, preventing failed deploys from clobbering runtime secrets or deleting WhiteNoise assets before `collectstatic` runs.

### Changed
- `homeassistant_deploy` now performs its read-only Python, Home Assistant, and
  Matter Server inspection commands during Ansible check mode, preventing
  upgrade preflights from failing on missing skipped-command output, and its
  temporary API helper cleanup no longer produces false idempotency changes.
  Virtualenv inspection and API helper commands now run as the Home Assistant
  service user, with ownership reconciliation to prevent root-owned bytecode
  caches from blocking runtime integration installs.
- `homeassistant_deploy` no longer renders the removed `system_monitor` and
  `discovery` YAML integrations and migrates the role-generated legacy blocks
  out of existing managed configurations.
- `os_apt_maintenance` endpoint responses now derive `$.reboot_required` from the live `/var/run/reboot-required` marker so monitoring clears immediately after a successful reboot.
- `mastodon_backup` now excludes Mastodon's refetchable `public/system/cache` subtree from local media backups by default and records the media exclude list in backup manifests.
- `mastodon_backup` now runs `pg_dump` as the backup owner by default so password-authenticated dumps can write into root-owned backup directories.
- `openclaw_deploy` now uses a shallow single-tag/branch source checkout so upstream branch namespace conflicts do not block tag-pinned deployments.
- `openclaw_deploy` now renders the managed slash-skill session manifest without invalid inline Jinja comments.
- `openclaw_deploy` now normalizes legacy Telegram streaming aliases in persisted gateway configs before restarting newer OpenClaw releases.
- `openclaw_deploy` metrics collector now recognizes the current OpenClaw Telegram health shape (`running`/`connected`) when deriving `telegram_probe_ok`.
- `openclaw_deploy` documentation now uses upstream stable `v2026.6.10` in examples and validation hints.
- `paperless_deploy` now defaults to Paperless-ngx 2.20.15 and supports checksum verification for known upstream release archives.
- `paperless_deploy` now restarts Paperless services before health checks when a release symlink or package install changes, preventing upgraded deployments from leaving old worker processes serving the previous release.
- `homeassistant_deploy` now supports Home Assistant 2026.5 on Python 3.14, installs host-specific integration requirements before startup, removes legacy MET weather YAML when requested, and isolates the Matter Server in its own virtualenv to avoid Matter package namespace collisions.
- `unifi_deploy` now reconciles the Home Assistant UniFi admin when it already exists, including password hash drift and missing readonly site privileges.
- `dns_deploy` now supports Unbound cache prefetch, stale-TTL reset, optional RFC 8767 timeout tuning, recursion queue sizing, and disables Ubuntu's legacy resolvconf helper when the role manages `/etc/resolv.conf`
- `dns_deploy` blocklist refreshes now tolerate individual download failures, understand both hosts-style and AdGuard-style lists, and document the limits of `serve-expired` during WAN reconnects
- `netplan_config` now rejects interfaces that combine `dhcp4: true` with a manual IPv4 default route, documents DHCP-backed hosts to use DHCP-managed default routes, and offers an optional post-apply `networkctl reconfigure` recovery pass for `networkd` hosts stuck in a failed link state
- Closed out the refactor documentation pass so top-level docs and role READMEs
  describe the landed deploy/restore helper boundaries as complete work and
  frame remaining items as normal follow-up maintenance instead of pending
  refactor waves
- `dns_deploy` now exposes optional Unbound `serve-expired` controls and documents `forward_first` guidance for the root zone so resolver failover behavior is explicit
- `nyxmon_restore` now mirrors the Home Assistant structure (validate/prepare/restore/verify/cleanup), keeps cleanup in a top-level block/always flow, adds restore-phase block/rescue rollback, conditional restores, handler flush, and health checks
- `nyxmon_deploy` systemd service now launches Granian instead of Gunicorn to match the upstream project
- `ollama_install` stops any Homebrew-managed Ollama service by default, stops conflicting user-level `ollama serve` processes, and ensures the launchd service is running
- Updated README.md with prominent link to ReadTheDocs
- Updated repository URLs to https://github.com/ephes/ops-library
- Modernized Python tooling: uv replaces traditional pip/venv workflow
- Removed `docs-setup` command (auto-handled by uv)
- `fastdeploy_deploy` now depends on `postgres_install` for database provisioning (removing the legacy inline PostgreSQL tasks)
- `uv_install` detects alternate uv installations, relinks to newer binaries automatically, and enables `uv_update_existing` by default to keep hosts current
- `fastdeploy_deploy` implements Traefik's dual-router pattern with IP-based allow lists, bcrypt-hashed basic auth, security headers, and compression middleware
- Paperless roles now support Python 3.14 and include an optional ocrmypdf patch to keep OCR workflows unblocked
- `paperless_deploy` no longer installs `default-libmysqlclient-dev`, avoiding apt conflicts with MariaDB development packages on Ubuntu 24.04 when using the PostgreSQL backend
- `redis_install` enables config validation by default to catch syntax and runtime issues before service restarts
- `nyxmon_deploy` and `homelab_deploy` switch from Granian to Gunicorn and gained configurable Python version management (defaulting to 3.13)
- `nyxmon_deploy` now enforces the same dual-router authentication policy as other public services, including validation and hashed credentials
- `nyxmon_deploy` now flushes handlers and smoke-validates the live monitoring worker's OpsGate submit and approval URLs so stale approval-link wiring fails during deploy
- DNS deployment/removal flows hardened with improved resolver management, legacy `unbound_only` port detection, and safer variable validation
- `snappymail_deploy` now writes managed domain configs as `.json`, removes conflicting legacy `.ini` files, and supports `snappymail_remove_domains` cleanup for stale domain overrides
- `open_webui_deploy` documentation now calls out the `studio.tailde2ec.ts.net` hostname, Traefik config path/basic auth wiring, and ops-control preflight bypass flag
- `open_webui_remove` now defaults to non-destructive options and supports removing compose/env files separately from the site directory
- `zfs_usb_replication` gained optional syncoid identifiers, force-export, and spindown hooks to prevent snapshot collisions and park disks after USB runs
- `openclaw_deploy` synthetic canary collection now sets explicit collector `TimeoutStartSec=600`, keeps dedicated canary session-id routing, and preserves stable canary metadata keys (`agent`, `timeout_seconds`, `session_id`) in payload defaults

### Fixed
- `backup_metrics_endpoint` and `openclaw_deploy` collector timers now schedule from timer activation and collector completion, preventing post-reboot or post-restart `active (elapsed)` timers with no next run.
- `mail_spam_deploy` now configures the Rspamd APT repository with a scoped `signed-by` keyring and removes the legacy global apt-key entry, avoiding apt-key deprecation warnings on Ubuntu 24.04.
- `mastodon_backup` now restarts Mastodon services after failed backup payload capture, preventing `pg_dump` or media-copy failures from leaving services stopped.
- `mastodon_restore` now makes the staged database dump path traversable by the restore OS user before running `pg_restore`, while keeping the default peer-auth restore user.
- `wagtail_deploy` now protects the top-level `/cache` directory from rsync deletion and recreates `wagtail_cache_dir` after source deployment, preventing Django file-based cache failures like the python-podcast feed incident
- `mastodon_deploy` now resolves the concrete Node version path from `nvm version` instead of guessing an `nvm` directory name from `.nvmrc`, fixing deploys where values like `24.10` install under `v24.10.0` and otherwise break `yarn` during asset precompile
- `mastodon_deploy` now clears Rails cache after source, runtime, dependency, migration, or asset-build changes so stale cached instance metadata does not survive Mastodon upgrades in Redis after the services restart
- `mastodon_deploy` now restarts the web, Sidekiq, and streaming services when source, runtime, dependency, migration, or asset-build tasks change, so upgrades and recovery reruns do not leave long-running processes serving the previous release until a manual restart
- `logyard_vector_deploy` now disables the Vector Loki sink startup health check by default and validates staged config with `--skip-healthchecks`, preventing transient Logyard/Loki 5xx responses from blocking Vector service startup after package upgrades or restarts.
- `dns_deploy` now points its default AdGuard DNS filter source at the maintained upstream URL, avoiding daily blocklist refresh failures from the retired GitHub raw path
- `sanoid` now renders dataset `use_template` values using the bare template name expected by Sanoid instead of the literal section header, restoring per-dataset retention and pruning behavior for roles like Fractal Time Machine backups
- Home Assistant presence automations now include the default file to prevent missing automation imports after deployment
- `dns_remove` cleans up DDNS units reliably and no longer crashes on undefined variables during selective removal
- `unifi_restore` now re-imports MongoDB dumps, honors host/port overrides, and ships with sane defaults so UniFi logins and controller state survive a remove/deploy/restore cycle
- `unifi_deploy` gracefully skips the Home Assistant integration on the very first bootstrap when the UniFi “default” site does not exist yet, avoiding infinite waits on greenfield installs
- `open_webui_deploy` now validates the bind host and host port range to catch invalid settings earlier
- `zfs_usb_replication` now creates `/etc/exports.d` before mount and auto-sets `canmount=off` on existing recursive+readonly targets to avoid mountpoint creation failures on subsequent runs

## [2.0.0] - 2025-10-09

### Breaking Changes
- **REMOVED**: `python_app_systemd` role - Legacy manifest-driven deployment (use dedicated `*_deploy` roles instead)
- **REMOVED**: `python_app_django` role - Legacy manifest-driven Django deployment (use dedicated `*_deploy` roles instead)

### Added
- `homelab_deploy` role - Django/Granian deployment with dual router Traefik authentication
- `homelab_remove` role - Safe removal with data preservation options
- `traefik_deploy` role - Install and harden Traefik with Let's Encrypt automation, architecture auto-detection, and smoke tests
- `traefik_remove` role - Safe Traefik uninstallation with confirmation gates and preservation toggles
- `dns_deploy` and `dns_remove` roles - Manage Pi-hole/Unbound (later Unbound-only) DNS stacks with split-DNS views and clean removal
- Dual router authentication pattern for Traefik (internal: no auth, external: basic auth)
- Comprehensive Traefik security documentation
- Broken venv detection and auto-removal in Python deployment tasks
- Build ignore patterns in galaxy.yml for faster collection builds
- Comprehensive documentation structure with README.md and ARCHITECTURE.md
- CLAUDE.md for AI assistant context
- Standardized role README template

### Changed
- Streamlined role documentation for consistency
- Fixed systemd service template to remove `ProtectHome` for services in /home
- Improved validation.yml to handle undefined variables gracefully in homelab_remove
- Removed legacy role documentation pages
- Updated role index to reflect removal
- Added migration guidance for users of removed roles
- Updated uv_install examples to use modern deployment pattern
- `nyxmon_deploy` gained rsync support for additional source directories and smarter uv-based dependency management (pyproject validation, lock cleanup, mode-aware sync commands)

### Fixed
- Template evaluation crashes in homelab_remove when home directory doesn't exist
- Undefined variable errors in removal validation when database/media checks are skipped
- Permission issues with Python virtual environments on redeployment

### Migration Guide
If you were using `python_app_systemd` or `python_app_django`:
1. Migrate to dedicated roles: `fastdeploy_deploy`, `nyxmon_deploy`, `homelab_deploy`, etc.
2. Follow the role development guide to create custom deployment roles if needed
3. The old `services.d/` manifest workflow is no longer supported

## [1.0.0] - 2024-09-22

### Added
- Initial release of ops-library collection
- Core service deployment roles:
  - `fastdeploy_deploy` - Deploy FastDeploy platform
  - `nyxmon_deploy` - Deploy Nyxmon monitoring service
  - `fastdeploy_remove` - Remove FastDeploy service
  - `nyxmon_remove` - Remove Nyxmon service
- Service registration roles:
  - `apt_upgrade_register` - Register apt upgrade tasks with FastDeploy
  - `fastdeploy_register_service` - Generic service registration helper
  - `fastdeploy_self_deploy` - FastDeploy self-deployment registration
- Bootstrap roles:
  - `ansible_install` - Install Ansible and dependencies
  - `uv_install` - Install uv for Python environment management
  - `sops_dependencies` - Install SOPS/age prerequisites
- Testing infrastructure:
  - `test_dummy` - Example service for testing deployment patterns
- Legacy compatibility roles:
  - `python_app_django` - Django application deployment (deprecated)
  - `python_app_systemd` - Systemd service management (deprecated)

### Security
- Strict validation of secrets to prevent "CHANGEME" placeholder values
- SOPS/age encryption support for secrets management
- Sudoers configuration for privilege separation

## Role Version History

### fastdeploy_deploy
- **1.0.0** (2024-09-22): Initial release with rsync/git deployment support

### nyxmon_deploy
- **1.0.0** (2024-09-22): Initial release with Telegram integration

### apt_upgrade_register
- **1.0.0** (2024-09-22): Initial release with SSH key management

[Unreleased]: https://github.com/ephes/ops-library/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/ephes/ops-library/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/ephes/ops-library/releases/tag/v1.0.0
