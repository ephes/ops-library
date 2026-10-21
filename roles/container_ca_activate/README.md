# container_ca_activate

Performs one coordinated trust-only transaction across an explicitly inventoried running Docker fleet. It preserves application image IDs and existing Compose files, adds prepared replacement trust bindings in a private override, and restarts Docker exactly once to reload its cached system roots. Run only after the host CA update and all preparation roles have passed verification.

`container_ca_activate_projects` is a nonempty list. Each project supplies `project`, absolute `directory`, original `files`, and `containers`. Each container supplies `name` and either `store` (prepared `container_ca_remediate` directory) or `linuxserver_hook` (prepared hook directory). Optional `node: true` selects replacement OpenSSL trust while retaining existing Node options. Optional `chrome_policy` binds the separately prepared Chrome policy. Every container requires explicit trust protection.

```yaml
container_ca_activate_projects:
  - project: example
    directory: /opt/example
    files: [/opt/example/compose.yml]
    containers:
      - name: example-server
        store: /var/lib/managed-container-ca/example-server
```

Run as root on Linux. Check mode reads Docker metadata and validates every project/service's current Compose configuration hash, running/healthy state, and prepared paths without stopping or recreating anything. Configuration drift fails closed before the transaction. The explicit inventory must cover every running container because Docker restart affects the entire daemon.

During activation all inventoried containers stop, are recreated without builds/pulls using their exact current image IDs and CA-only overlays, then Docker restarts and the projects start. Existing data volumes, network definitions and restart policies remain in the original Compose configuration. Root-only receipts under `/var/lib/managed-container-ca/activation/<timestamp>` contain sensitive original inspect/Compose/environment backups, active and rollback override files, and the outcome. Do not copy these receipts into public logs. The helper prints only the receipt path.

On an activation error, recovery recreates the original configuration and image IDs, starts it, and checks health. Docker restart is attempted at most once, including recovery. If recovery itself fails, retain the receipt and investigate before further changes. Successful rollback restores the original known trust exposure, so it is a recovery state rather than incident closure. A failed Docker daemon restart can require operator recovery.

This is a one-time transaction, not routine deployment. Persist the equivalent optional trust settings in the service's normal deployment configuration before activation; later deployments must retain them. Recheck actual application negative-chain rejection and positive TLS after activation: running/health status alone cannot prove effective TLS protection. Future trust file changes require appropriate application reload/recreation; single-file Chrome/hook bindings require recreation to see replacement inodes.

The incident-specific prepared store contract is `bundle.pem`, an actually empty `empty/` directory, and `manifest.json` with an `image` field equal to the exact Docker image ID. `container_ca_remediate` produces it. Native hooks come from `linuxserver_ca_remediate` and contain `repair_ca.py` plus executable `10-emudhra-ca.sh`; `chrome_ca_distrust` produces the Chrome JSON policy. These producer roles are released with the associated incident collection bundle. The activation helper explicitly refuses AAA Certificate Services and emSign ECC Root CA G3 by their incident SHA256 fingerprints. Fixed hook/policy filenames match those producer roles.

Complex existing NODE_OPTIONS values (quotes, dollar interpolation, or other non-simple option characters) fail preflight for separate review; current simple options are preserved and replacement trust mode appended. Recovery recreates the original configuration with an image-ID overlay to guarantee application bits. Consequently its Compose config hash differs from the original tag/digest spelling: a retry deliberately fails the original-hash guard and requires review of the private rollback receipt, not an unreviewed normal deploy. An interrupted/recovery-failed transaction preserves the last step and Docker restart-attempt marker in `result.json`; do not blindly retry it.

Set `container_ca_activate_livekit_config` to the existing local server YAML when the fleet contains LiveKit. A bounded read-only Twirp ListRooms/ListEgress preflight uses the configured credentials in memory, prints only aggregate active room/job counts, and defers activation unless both are zero. It never starts/stops a recording or emits room/user/media details. Requires existing Python PyYAML on the target. The preflight uses short-lived HS256 grants documented in [LiveKit access tokens](https://docs.livekit.io/frontends/reference/tokens-grants/) and the official [RoomService](https://github.com/livekit/python-sdks/blob/main/livekit-api/livekit/api/room_service.py)/[Egress service](https://github.com/livekit/python-sdks/blob/main/livekit-api/livekit/api/egress_service.py) readonly list calls. Recheck immediately before the coordinated window; new work must be avoided during that window.

Compose records a service network namespace after resolving `service:<dependency>` to `container:<ID>`. If raw config hashes differ, preflight only normalizes that spelling when the original file declares the service dependency, both containers belong to the same explicitly inventoried project, and the actual namespace equals that dependency's exact current ID. The official Compose CLI then recomputes all hashes from a stdin-only override; unrelated changes still fail. No Compose file or environment placeholder is rewritten by this check.
