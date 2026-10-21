# linuxserver_ca_remediate

Prepare a root-owned startup hook for pinned LinuxServer images whose Qt/native
TLS clients ignore replacement `SSL_CERT_FILE`/`SSL_CERT_DIR` settings. This
role writes only `/var/lib/managed-container-ca/linuxserver-init`; it does not
modify/restart a running container.

Mount that directory read-only at `/run/managed-ca-init` and its executable
`10-emudhra-ca.sh` file read-only at `/custom-cont-init.d/10-emudhra-ca.sh`.
LinuxServer runs custom init after built-in init and before application startup.
The Python helper uses the image’s existing `/usr/bin/python3`, removes only the
exact fingerprints of the two incident roots from image CA source directories,
runs the existing updater without downloading packages, and verifies all
unrelated source certificates survived and both blocked roots are absent from
Qt’s native trust directories. Other/local CAs remain. Unknown layouts fail.

The upstream custom init runner ignores nonzero script exits. On failure this
wrapper requests s6 halt and blocks indefinitely, so it cannot return control to
application startup. Check isolated success/failure startup before activation.
Restarts repeat the repair because container recreation restores the original
pinned image sources. Rollback removes both mounts and recreates the original
image; that restores vulnerable roots and needs explicit risk assessment.

No configurable variables. This requires a LinuxServer image with the stated
Python/updater/s6 layout; it is not a general-purpose container image hook.
See [LinuxServer custom scripts](https://docs.linuxserver.io/general/container-customization/).

Activation must verify the success log marker and effective native bad-chain
rejection; a missing/dropped init mount otherwise bypasses the hook entirely.
Hook updates require **container recreation**, because a single-file bind keeps
its original inode across an atomic host update and an ordinary restart.
