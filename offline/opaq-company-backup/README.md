# Offline company package transport reference

Synthetic-only, controller-local adapter for the reviewed four-member Daybook
bound-journal recovery package at `8f99443f910105153180255b26f26768a0f80bec`.
No Ansible installation, FastDeploy registration, network connector, credentials,
retention or live restore is supplied. Company native sources remain authoritative.

The eventual Echoport boundary is `service_owned`: fixed synthetic target and
bucket, immutable per-run object key and `ECHOPORT_RESULT` step message. Success
requires expected input digest, deep pinned-validator admission, complete fake
upload/download byte equality and a second deep validation. Malformed result/envelope JSON and encrypted
manifests emit only sanitized failure result JSON, never raw input/error bodies. The local fake is
not MinIO transport acceptance. Interrupted uploads remain unreferenced owned
objects; the adapter never sweeps or deletes them, nor overwrites prior objects.

Restore accepts an exact result identity/digest and reuses the same validator in
a fresh private scratch subtree; it never imports, registers, decides, promotes,
starts consumers or switches active pointers. Inactive markers are descriptive,
not production authorization. Quiescence assumptions belong to package capture;
transport does not make live multi-store capture atomic or authenticate hashes.

The validator is extracted from P's exact digest-pinned 108-file dependency
closure, never loaded from a Daybook checkout. No source archive is copied into
this repo or published. No source tree is edited. Required experiments/spec/stdlib
dependencies are extracted into temporary private scratch and removed afterward.
An installed Python >=3.14 is required; no site packages or third-party dependencies
are used and no install/download is performed. Input, object roots and scratch
must be explicitly chosen disposable local directories.

Example (all paths are caller-chosen disposable scratch; no real data):

```sh
mkdir -m 700 /tmp/company-fake-objects /tmp/company-adapter-scratch
python3 offline/opaq-company-backup/adapter.py backup \
  --validator-source /path/to/validator-source-8f99443.tar \
  --python /path/to/existing/validator/python \
  --objects /tmp/company-fake-objects --scratch /tmp/company-adapter-scratch \
  --package /path/to/invented-bound.zip --sha256 <explicit-package-sha256>
```

Save the JSON after `ECHOPORT_RESULT:` into a private result file. Restore it with
`restore --result /path/to/result.json` and the same validator/objects/scratch
arguments. Caller-owned directories/ancestors must be private and quiescent;
this is not an adversarial multi-user filesystem or authenticated provenance
boundary. Validator subprocesses have a whole-command timeout and are reaped;
the existing validator creates no subprocesses. Failed staging is removed only
inside this invocation's new temporary directory. No arbitrary orphan sweep.

Run `uv run pytest -q tests/test_opaq_offline_backup_adapter.py`. The optional
real-validator test requires explicit `OPAQ_PINNED_PACKAGE`, `OPAQ_PINNED_SHA256`,
`OPAQ_VALIDATOR_SOURCE`, and optionally `OPAQ_VALIDATOR_PYTHON` pointing to P's
reviewed synthetic handoff and an existing interpreter. Without those inputs it
is visibly skipped; unit envelope fakes do not constitute deep recovery proof.
No dependencies are fetched. The pinned validator independently checks its
canonical manifest, exact members, historical source bindings and journal schema.
The adapter admits only the checksum-pinned producer dependency closure;
untracked/modified checkout files and site packages cannot supply validator code.

Later real transport/enrollment and attended production restore require separate
work and authority. Echoport SQLite cleanup/restore creation can race; an existing
RestoreRun is not an unconditional artifact retention guard. No cleanup or retention
policy is implemented here; future drills must exclude object deletion while
selecting/downloading/restoring a recovery point.
