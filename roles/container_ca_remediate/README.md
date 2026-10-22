# container_ca_remediate

Prepare a replacement CA bundle for explicitly named Linux Docker containers
from each container’s own `/etc/ssl/certs` directory. The script follows original
CA symlinks, deduplicates certificates, and removes only the SHA-256 fingerprints
of emSign ECC Root CA - G3 and AAA Certificate Services. Other existing CA
material is retained; the host’s unrelated CA store is never substituted.

`container_ca_remediate_containers` is the required nonempty list of existing
container names. Run as root. Preparation is read-only to the running container
and writes `/var/lib/managed-container-ca/<name>/{bundle.pem,manifest.json,empty}`
on the host. Check mode computes the proposed change without writing that path.
The manifest records the source image and retained/removed fingerprints.

Consumers must explicitly mount this directory read-only at `/run/managed-ca`
and use replacement trust configuration:
`SSL_CERT_FILE=/run/managed-ca/bundle.pem` and
`SSL_CERT_DIR=/run/managed-ca/empty`. For Node add `--use-openssl-ca` to existing
`NODE_OPTIONS`; extra/additive CA settings do not remove bundled roots.
The caller must verify that the specific runtime honors these settings and
restart/recreate it via its existing service deployment. This role does not
claim to remediate runtimes that ignore these variables (including some Qt
configurations), embedded certifi wheels or explicit application CA overrides.

When changing images, set `container_ca_remediate_images` to a mapping from
container name to the **target** image reference, which must already exist
locally. Preparation reads that image in an isolated, read-only, networkless
container without starting its application; the manifest records the target
image ID. This prevents a new image receiving the previous image’s CA set.
Omit the mapping when refreshing custom CA material from the current running
container. Re-run preparation before recreation whenever image/custom CA
material changes. Persist the mount and environment in the owning compose
configuration. Rollback is to remove those settings and recreate the exact
previous image; this reintroduces the vulnerable roots and needs risk assessment.

```yaml
- hosts: docker_hosts
  become: true
  roles:
    - role: local.ops_library.container_ca_remediate
      container_ca_remediate_containers: [example-client]
```
