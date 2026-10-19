# delve_deploy

Deploy the **Delve backend service** — a single static Go binary (`delved`) — as
a systemd unit behind Traefik on an Ubuntu/Debian host.

Delve is the player's shared backend (placeholder name; `apps/delve-backend` in
the podcast repo). It hosts the accounts, entitlements, StoreKit, and Discovery
modules behind one principal-resolution middleware (ADR 0012). State lives in
SQLite on disk; there is no object store or live path, so this role is a stripped
sibling of `recorder_deploy`: no frontend build, no MinIO, no LiveKit, no mail.

The role installs a **locally cross-compiled** `linux/amd64` binary copied from
the control node rather than an upstream release.

## What it does

1. Creates a system user/group (`delve`) and the install, config, and data dirs
   (`/opt/delve`, `/etc/delve`, `/var/lib/delve`).
2. Installs the cross-compiled `delved` binary to `/opt/delve/delved`.
3. Installs the bundled public Apple StoreKit root certificate PEM when StoreKit
   verification is enabled.
4. Renders `/etc/delve/delve.env` (mode 0640, `no_log`) from the passed config.
5. Installs a hardened systemd unit and (optionally) a Traefik dynamic route for
   the public host.
6. Installs an optional service-owned `delve discovery collect --due` oneshot
   and systemd timer for the reviewed RSS Discovery collector.
7. Enables/starts the service, restarts it right away when the binary, the env
   file, the StoreKit bundle or the unit changed, and only then runs a loopback
   `/health` check. The check therefore verifies the new process, and no
   restart is left pending for the end of the play, where it would hit the
   caller's own smoke test.

## Required variables

- `delve_binary_src` — path to the cross-compiled `delved` on the control node.
- `delve_session_secret` — HMAC session secret, **≥16 chars** (the binary refuses
  to boot otherwise). Pass from SOPS.

## Notable optional variables

- `delve_public_url` / `delve_traefik_host` — default to
  `delve.home.xn--wersdrfer-47a.de` (the IDNA/punycode form of
  `delve.home.wersdörfer.de`, so the Traefik router and TLS SNI match).
- `delve_port` — loopback port Traefik proxies to (default `10026`).
- `delve_dogfood_token` — enables the interim `dogfoodGrant` path.
- `delve_apple_client_id` — enables `POST /v1/accounts/apple` (the app bundle id).
- `delve_apple_server_notifications` — `DELVE_APPLE_SERVER_NOTIFICATIONS`:
  `true` enables the Sign in with Apple server-to-server notification webhook
  (`POST /v1/apple/notifications`). Requires `delve_apple_client_id`; the role
  refuses `true` without it because the binary would not boot.
- `delve_profile_legacy_reregister` / `delve_apple_signin_legacy_no_nonce` —
  `DELVE_PROFILE_LEGACY_REREGISTER` / `DELVE_APPLE_SIGNIN_LEGACY_NO_NONCE`,
  transition switches for iOS builds that send no registration secret or no
  Sign in with Apple nonce. See [Legacy iOS transition](#legacy-ios-transition).

These three flags default to empty, which leaves them out of `delve.env` (the
binary then treats them as `false`). When set, they must be a boolean or the
string `true`/`false` (any case), and are written as `"true"`/`"false"`. Any
other value (`yes`, `1`, a typo) fails validation instead of silently turning
the flag off.

- `delve_storekit_root_certs_path` + `delve_storekit_bundle_id` +
  `delve_storekit_product_ids` — enable StoreKit verification. When the certs
  path is set, the role copies its bundled public Apple Root CA - G3 PEM to that
  path; the bundle id and product ids are required (validated, and enforced by
  the binary at startup). Override `delve_storekit_root_certs_src` only if the
  control repo supplies a different PEM bundle.
- `delve_discovery_collector_timer_enabled` — installs but does not enable by
  default. When true, enables `{{ delve_service_name }}-discovery-collect.timer`.
  The timer runs as the `delve` service user, reads the same env file, uses the
  same SQLite DB, and invokes the binary's application-level collection lock so
  overlapping runs exit visibly instead of writing concurrently.
- `delve_discovery_collector_calendar` / `delve_discovery_collector_randomized_delay_sec`
  — default to a conservative twice-daily schedule with one hour of systemd
  randomization. The application also applies deterministic per-source jitter.
- `delve_discovery_collector_concurrency` — defaults to 2 and is validated in
  the 2-8 range so the 100-source/30s fetch envelope remains below the
  35-minute systemd timeout.
- `delve_discovery_poll_interval_seconds`, `delve_discovery_poll_jitter_seconds`,
  `delve_discovery_episode_ttl_seconds`, `delve_discovery_max_items_per_feed`, and
  `delve_discovery_max_sources_per_run` — passed as non-secret environment
  values. Defaults are 12h polling, 1h deterministic per-source jitter, 90-day
  active episode TTL, 100 items per feed/run, and 100 sources per run. The source
  cap plus collector concurrency floor keeps the app lock and 35-minute systemd
  timeout coherent.

## Server ad analysis

`delve_smart_skip_analysis: true` switches on Delve's server ad analysis
(`DELVE_SMART_SKIP_ANALYSIS`; podcast repo,
`docs/player/specs/server-ad-analysis-design.md` and
`docs/backend/specs/deployment-and-operations.md`). Off (the default), the
role renders none of the settings below, so the env file and the unit stay
byte-identical to a deployment without them, and it removes the two secret
files if an earlier deploy wrote them.

When on, the role

1. installs `delve_smart_skip_packages` (apt `ffmpeg`: Delve probes downloads
   with ffprobe and decodes edge windows with ffmpeg);
2. copies the analysis profile JSON from the control node
   (`delve_smart_skip_analysis_profile_src`, required, checked to be a JSON
   object) to `delve_smart_skip_analysis_profile_path` (default
   `/etc/delve/smart-skip-analysis-profile.json`, root:delve 0640) and renders
   `DELVE_SMART_SKIP_ANALYSIS_PROFILE`. `delved` refuses to start with a profile
   it does not implement, so a wrong profile fails the loopback health check;
3. creates `delve_analysis_media_dir` (delve:delve 0700) when it is set and
   renders `DELVE_ANALYSIS_MEDIA_DIR`; a directory outside `delve_data_dir` is
   added to the unit's `ReadWritePaths`. Empty keeps Delve's default
   (`<data dir>/smart-skip-media`). Keep it off the backup path: it holds
   publisher audio and transcripts. The role never deletes it;
4. writes `delve_voxhelm_token` to `delve_voxhelm_token_path` and
   `delve_detector_api_key` to `delve_detector_api_key_path` (root:delve 0640,
   `no_log`) when the matching URL is set, and renders `DELVE_VOXHELM_URL` +
   `DELVE_VOXHELM_TOKEN_FILE` and `DELVE_DETECTOR_URL` +
   `DELVE_DETECTOR_API_KEY_FILE`. A URL must be a bare origin
   (`http(s)://host[:port]`); its secret must be at least 32 characters and not
   `CHANGEME`, and the detector key must match
   `delve_detector_api_key_pattern` (the key llama-server reads whole, as
   `llama_server_deploy` checks it); both are checked without printing them;
5. renders the optional `DELVE_ANALYSIS_MEDIA_DISK_CAP_BYTES`,
   `DELVE_FFPROBE_PATH`, `DELVE_FFMPEG_PATH`, `DELVE_VOXHELM_TIMEOUT_SECONDS`,
   `DELVE_VOXHELM_UPLOAD_TIMEOUT_SECONDS`, `DELVE_VOXHELM_POLL_SECONDS` and
   `DELVE_DETECTOR_TIMEOUT_SECONDS` only when set (empty: Delve's defaults).

Changing the profile, a secret file, the env file or the unit restarts
`delved`. The detector is a `llama-server` started by the
[`llama_server_deploy`](../llama_server_deploy/README.md) role; pass it the same
API key.

```yaml
delve_smart_skip_analysis: true
delve_smart_skip_analysis_profile_src: "{{ playbook_dir }}/../../files/delve/smart-skip-analysis-profile.json"
delve_analysis_media_dir: /var/lib/delve-smart-skip-media
delve_analysis_media_disk_cap_bytes: 20000000000
delve_ffprobe_path: /usr/bin/ffprobe
delve_ffmpeg_path: /usr/bin/ffmpeg
delve_voxhelm_url: "http://voxhelm.example.ts.net:8787"
delve_voxhelm_token: "{{ delve_secrets.voxhelm_token }}"
delve_detector_url: "http://studio.example.ts.net:8177"
delve_detector_api_key: "{{ delve_secrets.detector_api_key }}"
```

Switching the analysis off again (`false`) removes the settings and the secret
files and restarts `delved`; the media directory, the profile file and the
analysis tables stay.

## Legacy iOS transition

The Delve backend now requires a registration proof when an anonymous profile
re-registers, and a server-issued nonce on Sign in with Apple. iOS builds
released before those client changes send neither, so without the switches
below they get `409 profile registration proof required` after losing their
session and `401 sign-in nonce required` on Apple sign-in.

1. **Deploy with both switches on.** In the ops-control delve vars (or as
   extra vars) set:

   ```yaml
   delve_profile_legacy_reregister: true
   delve_apple_signin_legacy_no_nonce: true
   ```

   Deploy, then confirm `/etc/delve/delve.env` on the host contains
   `DELVE_PROFILE_LEGACY_REREGISTER="true"` and
   `DELVE_APPLE_SIGNIN_LEGACY_NO_NONCE="true"`. Changing the env file restarts
   the service. Each legacy request is logged by `delved` as
   `legacy profile <prefix> resumed without proof` or
   `apple sign-in without nonce accepted`.
2. **Ship the new iOS build** (registration secret and Sign in with Apple
   nonce) and wait until it has been adopted. The two log lines above show
   how much legacy traffic is left.
3. **Switch both off.** Set both variables to `false` (or remove them, which
   leaves them out of the env file with the same effect) and redeploy. From
   then on, builds that predate the change get the `409`/`401` above.

The switches are independent, so one can be turned off before the other if the
client changes ship separately.

See `defaults/main.yml` for the full list. Secrets are passed by the playbook
(`ops-control/playbooks/delve/deploy.yml`), never defaulted here. This role does
not seed real feed packs; reviewed source import remains an operator task.
