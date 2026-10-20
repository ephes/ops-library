# Test image for the minio_backup Molecule scenario, built by
# `just test-minio-backup-molecule` before Molecule runs. dl.min.io no longer
# serves the pinned MinIO builds, so minio and mc come from a MinIO image.
ARG MINIO_TEST_IMAGE=minio/minio:RELEASE.2025-01-20T14-49-07Z
FROM ${MINIO_TEST_IMAGE} AS minio-bins

FROM geerlingguy/docker-ubuntu2404-ansible
COPY --from=minio-bins /usr/bin/minio /usr/local/bin/minio
COPY --from=minio-bins /usr/bin/mc /usr/local/bin/mc
