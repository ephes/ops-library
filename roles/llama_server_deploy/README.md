# llama_server_deploy

Run one pinned llama.cpp `llama-server` on macOS under launchd: the detector of
Delve's server ad analysis (podcast repo,
`docs/player/specs/server-ad-analysis-design.md`, "Detector Service", and
`docs/backend/specs/smart-skip-coordination.md`, "Detection stage").

The server is started through a wrapper copied from the control node
(`llama_server_wrapper_src`, Delve's
`apps/delve-backend/scripts/detector-server.sh`). The wrapper is the one place
the pins live:

- it refuses a GGUF whose SHA-256 is not the pinned one,
- it refuses another llama.cpp build than `DELVE_DETECTOR_BUILD`,
- it refuses any bind address but loopback or a Tailscale address,
- it refuses an API key file readable by others,
- it execs `llama-server` with exactly the research flags
  (`-c 16384 -np 1 -ngl 99 -b 512 -ub 512 --flash-attn auto --seed 42
  --cache-ram 0`) plus `--alias`, `--api-key-file`, `--no-ui` and `--no-slots`;
  no `--slot-save-path` and no `--verbose` (which logs prompts), so
  `llama-server` keeps and logs no transcript text.

## What the role does

1. Validates the settings, checks on the control node that the wrapper pins
   `llama_server_gguf_sha256` and carries `--api-key-file`, `--no-slots` and
   `--cache-ram 0` (so a mismatch fails the deploy instead of a launchd restart
   loop), and checks the API key without printing it.
2. Resolves the bind address: `llama_server_bind_host: tailnet` (the default)
   takes the host's single Tailscale IPv4 address from the gathered facts.
3. Installs the Homebrew `llama.cpp` formula when it is missing (never
   upgrades it) and fails unless `llama-server --version` is the pinned build
   (`llama_server_build`, e.g. `b11669-620d2225c`). A different build is a new
   detector profile in Delve, so changing it is a deliberate step.
4. Downloads the GGUF at a pinned Hugging Face commit into
   `llama_server_model_dir` and verifies its SHA-256 (`get_url` checksum).
5. Installs the wrapper, writes the API key to `llama_server_api_key_path`
   (owned by the service user, mode 0600, `no_log`), renders the LaunchDaemon
   (`de.wersdoerfer.llama-server`, `UserName` = the service user, `KeepAlive`)
   and (re)starts it when the plist, model, wrapper, key or llama.cpp install
   changed or the job is not running.
6. Health check: `/v1/models` must serve exactly `llama_server_alias`, and
   `/props` must report `llama_server_build` and one slot (what Delve checks
   before and after every detector call). `/v1/models` without the key must
   answer 401: llama-server leaves only `/health`, `/v1/health` and UI assets
   open once a key is loaded, and serves everything when none is.

`llama_server_enabled: false` unloads the job and removes its plist and the
API key file; the model, the wrapper and the Homebrew package stay.

## Required variables

- `llama_server_service_user` - the account the server runs as.
- `llama_server_wrapper_src` - the wrapper on the control node.
- `llama_server_api_key` - at least 32 characters of `A-Z a-z 0-9 . _ ~ + / = -`
  (`llama_server_api_key_pattern`; `openssl rand -hex 32` makes one); pass
  from SOPS. llama-server (b11669) reads `--api-key-file` line by line without
  trimming and skips empty lines and lines starting with `#`, so any other
  value could be ignored and leave the server without authentication. Delve
  needs the same value (`delve_detector_api_key` of `delve_deploy`, which
  checks the same pattern).
- `llama_server_brew_user` - when Ansible connects as root.

## Example

```yaml
- role: local.ops_library.llama_server_deploy
  vars:
    llama_server_service_user: jochen
    llama_server_brew_user: jochen
    llama_server_wrapper_src: "/path/to/podcast/apps/delve-backend/scripts/detector-server.sh"
    llama_server_api_key: "{{ delve_secrets.detector_api_key }}"
    llama_server_bind_host: tailnet
    llama_server_port: 8177
```

Delve then uses `DELVE_DETECTOR_URL=http://<host's tailnet name>:8177`.

## Operations

- Logs: `/var/log/llama-server/llama-server.err.log` (timings and token counts,
  no prompt text; the wrapper's refusals). The role does not rotate them.
- Status: `launchctl print system/de.wersdoerfer.llama-server`.
- Restart: `launchctl kickstart -k system/de.wersdoerfer.llama-server`.
- Memory: about 3.3 GB with `--cache-ram 0` (research measurement).
- The bind address is resolved at deploy time. If the host's Tailscale address
  changes, deploy again.
- If the macOS application firewall is on, it may ask to allow incoming
  connections for `llama-server`; allow them, or Delve cannot reach it.
