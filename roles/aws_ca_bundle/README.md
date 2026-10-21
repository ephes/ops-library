# aws_ca_bundle

Persist botocore's supported `AWS_CA_BUNDLE` override for explicitly allowlisted
Debian/Ubuntu systemd services using SDK fallback trust without certifi. No Python
packages are inserted, no application code is deployed, and no AWS credentials
are inspected or logged.

`aws_ca_bundle_path` is restricted to `/etc/ssl/certs/ca-certificates.crt`; the
role verifies the actual bundle excludes the affected emSign G3 and AAA roots
before changing a unit. `aws_ca_bundle_services` is a required list of `unit`,
`health_url` (loopback HTTP), optional `health_headers` (only Host/X-Forwarded-Proto; no credentials) and `status_codes`.
Each running service is preflighted independently: a custom `AWS_CA_BUNDLE` in
its runtime, systemd Environment, EnvironmentFiles or any shared AWS config profile stops without overwriting
that custom trust. Existing divergent dedicated drop-ins are also preserved.

The root-owned `50-aws-ca-bundle.conf` drop-in survives normal unit replacement.
The role reloads systemd and restarts one service at a time when configuration
changes or the running process lacks the override. This also handles retries
after an interrupted rollout. It verifies the new process's effective environment
and application health before proceeding. It does not modify EnvironmentFiles or
remove existing custom certificates. Check mode performs read-only preflight and
reports pending drop-in/restart changes.

To remove the override, deliberately remove the dedicated drop-in, reload systemd
and restart the unit only after botocore supplies an independently verified safe
default bundle. Keep the supported override until that verification is recorded.
