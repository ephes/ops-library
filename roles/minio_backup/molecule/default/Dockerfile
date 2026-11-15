# Test image for the minio_backup Molecule scenario, built by
# `just test-minio-backup-molecule` (and `just molecule-test-all`) before
# Molecule runs. MinIO, Inc. no longer publishes binaries or images (the
# minio/minio tags cannot be pulled any more), so the server and client come
# from SILO, the community-maintained MinIO fork by Pigsty (PGSTY): `silo` is
# the MinIO server with the same `server` CLI and MINIO_* environment, `mcli`
# the MinIO client. They are installed under the names the scenario's unit
# and the role expect. Pinned by tag and digest (multi-arch: amd64, arm64).
ARG MINIO_TEST_IMAGE=pgsty/silo:RELEASE.2026-10-26T00-00-00Z@sha256:7bb2aff6b89efe1cb1303c10fc21d579447434ed06649ac9ec05a5e2dbf30ad7
FROM ${MINIO_TEST_IMAGE} AS minio-bins

FROM geerlingguy/docker-ubuntu2404-ansible
# Server and client paths inside MINIO_TEST_IMAGE (for a minio/minio image:
# /usr/bin/minio and /usr/bin/mc).
ARG MINIO_TEST_SERVER_BIN=/usr/bin/silo
ARG MINIO_TEST_CLIENT_BIN=/usr/bin/mcli
COPY --from=minio-bins ${MINIO_TEST_SERVER_BIN} /usr/local/bin/minio
COPY --from=minio-bins ${MINIO_TEST_CLIENT_BIN} /usr/local/bin/mc
