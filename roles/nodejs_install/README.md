# Node.js Install Role

Install one Node.js release line system-wide from the
[NodeSource](https://github.com/nodesource/distributions) apt repository.

Use it for hosts where a service needs a newer Node.js than the distribution
ships (Ubuntu 24.04 has Node.js 18), for example a Django site that renders
JSON Resume themes with `resumed` 7, which needs Node.js 24.

## What it does

- Stores the NodeSource signing key in `/etc/apt/keyrings/nodesource.asc`.
- Writes `/etc/apt/sources.list.d/nodesource.list` with exactly one release
  line. Changing `nodejs_install_major` replaces the line.
- Pins the `nodejs` package to NodeSource (`/etc/apt/preferences.d/nodesource`,
  priority 700), so an apt upgrade never swaps in a newer Node.js of the
  distribution.
- Installs `nodejs` from that line. An older or newer `nodejs` package is
  replaced (downgrades are allowed).
- Fails unless `/usr/bin/node --version` reports the requested major version
  and `/usr/bin/npm` runs.

Later patch releases of the same line arrive with the host's normal apt
upgrades.

## What it changes on a host that already has the distribution's Node.js

The NodeSource `nodejs` package bundles npm (and corepack) and conflicts with
the distribution's `npm` package. apt therefore removes the distribution's
`npm` and the packages that depend on it or on the old `nodejs` (`libnode-dev`,
`node-gyp`, distribution builds of `eslint`, `webpack`, `handlebars`, ...) in
the same transaction. The `node-*` libraries that only they needed stay
installed as unused automatic packages until `apt autoremove`.

`/usr/bin/node` and `/usr/bin/npm` are system-wide: every user and service
that resolves `node` through `PATH` gets the new version. Runtimes that bring
their own Node.js (nvm, as in `mastodon_deploy`) are not affected.

## Requirements

- Debian or Ubuntu on an architecture NodeSource builds for (amd64, arm64).
- Root (`become: true`) and outbound HTTPS to `deb.nodesource.com`.

## Role Variables

```yaml
# Node.js major release line to install from NodeSource (for example 22 or 24).
nodejs_install_major: 24

# NodeSource apt repository
nodejs_install_repo_url: "https://deb.nodesource.com/node_{{ nodejs_install_major }}.x"
nodejs_install_key_url: "https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key"
nodejs_install_keyring: "/etc/apt/keyrings/nodesource.asc"
nodejs_install_sources_list: "/etc/apt/sources.list.d/nodesource.list"
nodejs_install_preferences: "/etc/apt/preferences.d/nodesource"
```

## Example

```yaml
- hosts: production
  become: true
  roles:
    - role: local.ops_library.nodejs_install
      vars:
        nodejs_install_major: 24
```

## Going back to the distribution's Node.js

The role has no removal mode. On the host:

```bash
rm /etc/apt/sources.list.d/nodesource.list /etc/apt/preferences.d/nodesource \
   /etc/apt/keyrings/nodesource.asc
apt-get update
apt-get install --allow-downgrades nodejs/noble npm   # use the host's release name
```

and remove the role from the playbook, or the next deploy installs NodeSource
again.

## Testing

```bash
just molecule-test nodejs_install
```

The scenario starts from Ubuntu 24.04 with the distribution's `nodejs` 18 and
`npm` installed, converges to Node.js 24, checks idempotence, and verifies
that an unprivileged user gets Node.js 24 with its bundled npm.
