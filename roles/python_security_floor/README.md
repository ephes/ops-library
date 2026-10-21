# python_security_floor

Keeps `certifi` and upstream `pip` at security floors across normal application
deploys, so a deploy cannot reinstall a CA bundle that still trusts distrusted
roots (the eMudhra/emSign incident, certifi advisory
[GHSA-6q48-6c7w-9gw2](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2)).
Deploy roles include it with `tasks_from`; it has no handlers and never restarts
anything.

It never adds a package to an environment that lacks it, never changes an
application version, never rewrites a lock file and never replaces explicit
trust configuration (`SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE` and similar are left
as they are and are not inspected). Everything it cannot establish fails closed.

## Entry points

| `tasks_from` | Inputs | Effect |
| --- | --- | --- |
| `lock.yml` | `python_security_floor_lock_text`, `python_security_floor_label` | Fails when the `uv.lock` text locks a floor package below its floor. Call it with the lock of exactly the revision the role is about to install, before it changes the deployed source or environment. |
| `constraints.yml` | `python_security_floor_constraints_path`, `python_security_floor_owner`, `python_security_floor_group` | Writes a pip/uv constraint file (`certifi>=…`, `pip>=…`). Pass it to every package install the role runs. |
| `verify.yml` | `python_security_floor_python`, `python_security_floor_user`, `python_security_floor_label`, optional `python_security_floor_deferred` | Runs `files/inspect_python_security.py` with the environment's interpreter (`-I`, as the application user, importing only certifi and pip's vendored certifi) and fails on any problem below. |

`verify.yml` checks, per package that is installed:

- **In the environment:** the installed version meets the floor. If the
  environment's Python is outside the floor release's `Requires-Python`
  (`python_security_floor_requires_python`, taken from the wheels' METADATA:
  certifi `>=3.7`, pip `>=3.10`) the message says it cannot be updated in place;
  it is never bypassed or migrated.
- **Outside the environment** (system site packages): accepted only when
  `dpkg-query` shows the module owned by `python3-certifi`/`python3-pip` and its
  bundle is `/etc/ssl/certs/ca-certificates.crt`. A custom or unknown bundle fails.
- **Every effective bundle** (certifi's and pip's vendored one) contains none of
  `python_security_floor_distrusted_roots`. The bundle is loaded by the
  environment's own `ssl`/OpenSSL and every CA certificate it holds is matched
  by SHA-256 fingerprint of OpenSSL's DER (what `openssl x509 -fingerprint`
  hashes), so `TRUSTED CERTIFICATE` blocks and unusual encodings count as
  OpenSSL sees them. A bundle OpenSSL cannot load fails the check. Names are
  labels: a custom CA that only shares a name is not rejected. The check
  identifies the published distrusted certificates; it is not a defence
  against someone who can already rewrite the environment.

`python_security_floor_deferred` lists packages that the calling role's next,
constrained install raises itself (for example certifi before an install that
runs on every deploy). A deferred package is still reported when the floor
release does not support the environment's Python, because the install could
not raise it. Use it only for a preflight and run `verify.yml` again after the
install without it.

### As a role dependency (preflight before other dependencies)

A deploy role whose meta dependencies change the host (package, Redis or
PostgreSQL installs) lists this role first, with
`python_security_floor_preflight` (a list of `{python, user, label, deferred}`).
`tasks/main.yml` then verifies each existing environment before any later
dependency runs; missing environments are skipped (first deploy).

```yaml
dependencies:
  - role: local.ops_library.python_security_floor
    vars:
      python_security_floor_preflight:
        - python: "{{ app_virtualenv }}/bin/python"
          user: "{{ app_user }}"
          label: app environment
    when: app_python_security_floor_enabled | bool
  - role: local.ops_library.postgres_install
```

## Why constraints

A constraint file only limits the versions a resolution may pick; it does not
request a package. With it, an install that touches an environment with an old
certifi upgrades it, and a dependency that caps certifi below the floor makes
uv/pip fail during resolution, before anything is installed. Constraints do not
upgrade `pip` itself unless pip is requested, so a stale pip is caught by the
preflight `verify.yml` (fail closed before the role changes anything) unless the
role upgrades pip explicitly.

## Defaults

| Variable | Default |
| --- | --- |
| `python_security_floor_packages` | `{certifi: "2026.10.19", pip: "26.2.2"}` |
| `python_security_floor_requires_python` | `{certifi: ">=3.7", pip: ">=3.10"}` |
| `python_security_floor_distrusted_roots` | emSign ECC Root CA - G3 (`86A1…BE6B`), AAA Certificate Services (`D7A7…9EF4`) |
| `python_security_floor_deferred` | `[]` |
| `python_security_floor_become` | `true` |

## Roles using it

`metube_deploy`, `homeassistant_deploy`, `open_webui_venv_deploy`,
`paperless_deploy` and `takahe_deploy`; each has
`<role>_python_security_floor_enabled` (default `true`). See their READMEs.

## Example

```yaml
- name: Refuse a stale lock before changing anything
  ansible.builtin.include_role:
    name: local.ops_library.python_security_floor
    tasks_from: lock.yml
  vars:
    python_security_floor_lock_text: "{{ app_lock.stdout }}"
    python_security_floor_label: "app {{ app_rev }}"

- name: Verify the environment after the install
  ansible.builtin.include_role:
    name: local.ops_library.python_security_floor
    tasks_from: verify.yml
  vars:
    python_security_floor_python: /opt/app/.venv/bin/python
    python_security_floor_user: app
    python_security_floor_label: app environment
```

## Tests

`just test-python-security-floor`: filter unit tests, real uv/pip resolver
lifecycle tests (old certifi upgraded under constraints, a capped dependency
refused before any change, absent pip not added, stale pip caught), the role's
entry points through the collection loader (FQCN), and the wiring of the roles
above (ordering, constraint arguments, MeTube exact-revision lock check).
