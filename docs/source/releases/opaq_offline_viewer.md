# Offline synthetic company viewer — 2.26.0 candidate

Unreleased local candidate; no collection publication or deployment.

Prepare a hash-pinned company HTML-only bundle with loopback service, owner-authenticated
Traefik routing on all content paths and private/no-store responses. Separate disabled
FastDeploy registration inputs from company ingestion. Source databases, credentials,
DNS assignment, host installation and live backup enrollment remain excluded. Existing
static-site/homelab roles are unchanged.

See the [offline operator contract](../howto/opaq_offline_viewer.md) for validation,
narrow later rollout/rollback and missing decisions. Fixtures preserve the exact
reviewed synthetic Daybook views; no new real-data format is supported.
