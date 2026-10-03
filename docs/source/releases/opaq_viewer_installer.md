# Synthetic company viewer installer — 2.27.0

Adds `opaq_company_viewer_deploy`: exact synthetic bundle admission, dedicated
nonlogin identity and loopback service, required externally provisioned private
auth file, verification, automatic failure recovery and scoped operator rollback.
Only the viewer's six owned artifacts are changed; global Traefik configuration,
credentials, FastDeploy registration, inventories and financial state are excluded.

This is an offline-tested candidate. Native host, TLS, BasicAuth credential
acceptance and proxy behavior still require separately authorized operator checks.
The disabled FastDeploy draft and private rollout preparation are not activated
by this change. No DNS assignment, enrollment, deployment or backup is recorded.
