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

LiveKit aggregate API requests always connect directly to loopback with ambient HTTP proxies disabled, so its short-lived API token is never forwarded to a configured proxy.

## Native systemd Compose owners

Use `tasks_from: persist_owners` for a fleet managed by existing systemd Compose
units. Restarting Docker also restarts dependent owners on some hosts; an
out-of-band Compose override alone can race those owners and be discarded. This
entrypoint never restarts Docker. Reload the daemon's trust separately in a
coordinated window, then let the native owners activate the trust settings.

Each project additionally supplies `owner`: its exact `unit`, `fragment_sha256`,
`working_directory`, and argv arrays `start`, `stop`, and `reload` (empty if no
reload exists). Only the inspected simple `/usr/bin/docker compose ... up -d
--remove-orphans` owner shape is accepted. Unknown commands, drop-ins, users,
pre/post hooks, or changed original fragments require explicit reconciliation;
the role never silently masks changed owner commands.

The managed drop-in retains the original unit and stop command. It adds a
CA-only override to start/reload, with a preflight before either operation.
Overrides contain no application image or configuration snapshot. Node options
are derived from the current base Compose/image environment on every start or
reload, retaining current non-trust options while selecting replacement trust.
A desired image must match its prepared trust manifest; LinuxServer hook records
also require an explicit reviewed image/hash proof. A changed image or missing
trust source fails before Compose changes any containers.

Activation stops the explicit native owners, installs the drop-ins, reloads
systemd, and starts those owners. Existing base Compose files and data binds are
preserved. Recovery attempts every owner even after an earlier owner fails,
restores previous managed files, and restarts the original owners. Root-only
receipts preserve the original state and private command-error output; public
errors report only phase and receipt location. The role accepts an unchanged
repeat only when its own managed files/drop-ins match exactly. Unknown overrides
fail closed. No second Docker restart is part of activation or recovery.

Example owner shape (values must come from the inspected existing unit):

```yaml
container_ca_activate_projects:
  - project: example
    directory: /opt/example
    files: [/opt/example/compose.yml]
    owner:
      unit: example.service
      fragment_sha256: "<reviewed SHA256 of /etc/systemd/system/example.service>"
      working_directory: /opt/example
      start: [/usr/bin/docker, compose, -p, example, -f, /opt/example/compose.yml, up, -d, --remove-orphans]
      stop: [/usr/bin/docker, compose, -p, example, -f, /opt/example/compose.yml, down]
      reload: []
    containers:
      - name: example-server
        service: server
        store: /var/lib/managed-container-ca/example-server
```

For a LinuxServer hook instead of a store, supply `linuxserver_hook` and
`linuxserver_proof: {image: "sha256:<reviewed image ID>", sha256: {repair_ca.py:
"<reviewed file SHA256>", 10-emudhra-ca.sh: "<reviewed file SHA256>"}}`.
These proof values are explicit operator evidence, not learned from an arbitrary
future image during startup. Prepare and validate a new proof before changing an
image. Reconcile an intentional original unit change by inspecting its new
commands and updating the reviewed owner specification; do not delete a guard
just to make a failed start succeed. Existing unrelated drop-ins require a
separate integration review.

The opt-in `just test-container-ca-owner-systemd` regression uses a uniquely named
privileged local container with actual systemd and an isolated nested Docker
engine (no host Docker socket). It requires existing local
`geerlingguy/docker-ubuntu2404-ansible:latest` and `python:3.14.8-slim` images,
network access for Ubuntu fixture packages, and Ansible with `community.docker`.
It exercises the actual collection entrypoint, unchanged repeat, owner restart,
reload with changed base Node options, a real nested daemon/dependency cycle,
missing-store fail-before-recreation, and fault-injected owner recovery. Image
IDs, phase logs, and cleanup outcome are recorded in its unique scratch result.
Only the disposable nested daemon is restarted by this regression.

### Explicit managed reconciliation

Ordinary runs accept only the exact installed managed artifacts. A reviewed tool
upgrade, owner-command reconciliation, or changed trust proof requires an
explicit one-time approval of the existing files, not deletion of guards:

1. Inspect the changed desired owner specification and the installed role's
   `--managed-sha '<projects JSON>'` read-only output. Run it as root using
   `/var/lib/managed-container-ca/owners/persist_owners.py`; it emits only the
   SHA256 of every existing managed helper, owner config, CA override and
   drop-in. Independently review the existing contents before approving hashes.
2. Put that exact complete mapping in
   `container_ca_activate_owner_reconcile_sha256`. A stale hash, missing entry,
   extra entry or unrelated drop-in fails before any owner stops. The original
   fragment/argv, current Compose config/images and prepared trust checks remain
   mandatory. New unsupported owner shapes still require a role review.
3. Run the same entrypoint in check mode, then apply during a maintenance
   window. An explicit approval forces the bounded stop/update/start transaction
   even when repairing an unloaded but byte-identical managed drop-in. Recovery
   restores the previous complete managed state and attempts every owner.
4. Remove the approval mapping after **one successful run**, including a repair
   whose managed bytes were already identical. Every run with a nonempty approval
   requests the stop/update/start transaction and restarts all declared owners.
   A plain repeat without approval is unchanged. The old mapping becomes stale
   only when the managed bytes change; a byte-identical repair does not invalidate
   it automatically.

For later normal application-image updates, prepare the same per-container store
path from the approved candidate image first, then let the normal deployment
update the base Compose image. Startup reads that current base and requires the
candidate's matching manifest, so the durable override never pins an old image.
For LinuxServer, `linuxserver_proof.images` may explicitly list at most the
current and one tested candidate image, instead of the singular `image` field;
both are bound to the same exact reviewed hook hashes. Reconcile that proof
while the current image still runs, then deploy the candidate through the normal
application path. Remove the old image proof after verification in another
reviewed reconciliation. This role does not perform application upgrades.
