# Redis + PostgreSQL Combo Smoke Test

Molecule scenario that installs `redis_install` and `postgres_install` on the same container to ensure the infrastructure roles coexist without conflicting dependencies.

## Usage

```bash
cd tests/redis_postgres_combo
molecule test
```

What it does:
1. Boots an Ubuntu 24.04 systemd-enabled container.
2. Applies `redis_install` with authentication enabled.
3. Applies `postgres_install` with a sample `combo` database/user.
4. Verifies both services are running and reachable (redis-cli ping + psql query).

Use this scenario whenever you modify shared role defaults or upgrade the supported PostgreSQL/Redis versions to confirm the stack still behaves on a clean host.
