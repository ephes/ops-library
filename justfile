# ops-library Justfile
# Testing and development automation for Ansible collection

# Default - show available commands
default:
    @just --list

# Setup development environment with pre-commit hooks
setup:
    @echo "Setting up development environment..."
    @./setup-pre-commit.sh

# Run ALL tests (roles, lint)
test: venv test-roles lint
    @echo ""
    @echo "✅ All tests completed!"

# Test all roles
test-roles: venv
    @echo "Testing all roles..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ./test_roles.py --all

# Test a specific role
test-role ROLE: venv
    @echo "Testing role: {{ROLE}}"
    @UV_PROJECT_ENVIRONMENT=.venv uv run ./test_roles.py {{ROLE}}

# Quick syntax check for everything
syntax-check: venv
    @echo "Running quick syntax check..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ./test_roles.py --all | grep -E "(Testing role:|YAML Syntax|✓ PASSED|✗ FAILED)" || true

# Run ansible-lint on everything (non-failing for CI)
lint: venv
    @echo "Running ansible-lint..."
    @echo "Linting roles..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-lint roles/ 2>&1 | tail -3 || true

# Run strict ansible-lint (will fail on errors)
lint-strict: venv
    @echo "Running ansible-lint (strict mode)..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-lint roles/

# Run ansible-lint on a specific role
lint-role ROLE: venv
    @echo "Linting role: {{ROLE}}"
    @UV_PROJECT_ENVIRONMENT=.venv uv run ansible-lint roles/{{ROLE}}

# Run pre-commit on all files
pre-commit: venv
    @echo "Running pre-commit on all files..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run pre-commit run --all-files

# Update pre-commit hooks to latest versions
pre-commit-update: venv
    @echo "Updating pre-commit hooks..."
    @UV_PROJECT_ENVIRONMENT=.venv uv run pre-commit autoupdate

# Create virtual environment if it doesn't exist
venv:
    @if [ ! -d .venv ]; then \
        echo "Creating virtual environment..."; \
        uv venv .venv; \
        source .venv/bin/activate && uv pip sync pyproject.toml; \
    else \
        echo "Virtual environment already exists."; \
    fi

# Install/update Python dependencies
deps:
    @echo "Installing/updating dependencies..."
    @source .venv/bin/activate && uv pip sync pyproject.toml

# Clean up generated files and caches
clean:
    @echo "Cleaning up..."
    @find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    @find . -type f -name "*.pyc" -delete 2>/dev/null || true
    @find . -type f -name ".DS_Store" -delete 2>/dev/null || true
    @rm -rf .pytest_cache 2>/dev/null || true
    @rm -rf .mypy_cache 2>/dev/null || true
    @echo "✅ Cleanup complete!"

# Show test status for all components
status:
    @echo "==================================="
    @echo "ops-library Component Status"
    @echo "==================================="
    @echo ""
    @echo "Roles ($(ls -1 roles | wc -l) total):"
    @ls -1 roles | sed 's/^/  - /'
    @echo ""
    @echo "Run 'just test' to test everything"

# Show YAML lines of code statistics
stats:
    @cloc --include-lang=YAML --exclude-dir=.venv .

# Show YAML lines of code per role (top 20)
stats-roles:
    #!/usr/bin/env bash
    printf "%-35s %6s\n" "ROLE" "LINES"
    printf "%-35s %6s\n" "-----------------------------------" "------"
    for dir in roles/*/; do
        role=$(basename "$dir")
        count=$(cloc --include-lang=YAML --csv --quiet "$dir" 2>/dev/null | tail -1 | cut -d',' -f5)
        printf "%-35s %6s\n" "$role" "${count:-0}"
    done | sort -t' ' -k2 -rn | head -20

# Quick test - just syntax and structure
quick: syntax-check
    @echo "Quick test completed!"

# Development workflow - test the role you're working on
dev ROLE:
    @echo "Testing {{ROLE}} for development..."
    @just test-role {{ROLE}}
    @just lint-role {{ROLE}} || true
    @echo "Development test complete for {{ROLE}}"

# Documentation commands
docs-build:
    @echo "Building documentation..."
    @uv run --extra docs sphinx-build -b html docs/source docs/build/html

docs-serve:
    @echo "Serving documentation at http://localhost:8000"
    @python3 -m http.server 8000 -d docs/build/html

docs-watch:
    @echo "Starting documentation watch mode..."
    @uv run --extra docs sphinx-autobuild docs/source docs/build/html --watch roles --watch README.md --watch ARCHITECTURE.md --watch TESTING.md --watch README_TESTING.md --watch CHANGELOG.md

docs-check:
    @echo "Checking documentation for broken links..."
    @uv run --extra docs sphinx-build -b linkcheck docs/source docs/build/linkcheck

docs-clean:
    @echo "Cleaning documentation build artifacts..."
    @uv run --extra docs sphinx-build -M clean docs/source docs/build

docs-lint:
    @echo "Validating documentation integrity..."
    @uv run python validate_docs.py

# ------------------------------------------
# Container runtime detection (Colima/Podman/Docker)
# ------------------------------------------

# Internal: Detect Docker host socket
# Priority: 1) Existing DOCKER_HOST env, 2) Colima socket, 3) Podman socket, 4) Default Docker socket
_detect-docker-host:
    #!/usr/bin/env bash
    if [[ -n "${DOCKER_HOST:-}" ]]; then
        echo "$DOCKER_HOST"
    elif [[ -S "$HOME/.colima/default/docker.sock" ]]; then
        echo "unix://$HOME/.colima/default/docker.sock"
    elif command -v podman &>/dev/null && podman machine inspect &>/dev/null 2>&1; then
        # Escape Go template braces to avoid just interpolation
        socket_path=$(podman machine inspect --format '{{"{{"}}.ConnectionInfo.PodmanSocket.Path{{"}}"}}' 2>/dev/null)
        if [[ -n "$socket_path" ]]; then
            echo "unix://$socket_path"
        else
            echo ""
        fi
    elif [[ -S /var/run/docker.sock ]]; then
        echo "unix:///var/run/docker.sock"
    else
        echo ""
    fi

# Helper: export DOCKER_HOST only if detection returns non-empty
_export-docker-host:
    #!/usr/bin/env bash
    detected=$(just _detect-docker-host)
    if [[ -n "$detected" ]]; then
        echo "export DOCKER_HOST='$detected'"
    else
        echo "# DOCKER_HOST: using system default"
    fi

# ------------------------------------------
# Molecule helpers
# ------------------------------------------

# Run molecule test for a specific role
molecule-test role:
    #!/usr/bin/env bash
    eval "$(just _export-docker-host)"
    export ANSIBLE_ALLOW_BROKEN_CONDITIONALS=1
    cd roles/{{role}} && uv run molecule test

# Run molecule converge (apply without destroy) for debugging
molecule-converge role:
    #!/usr/bin/env bash
    eval "$(just _export-docker-host)"
    export ANSIBLE_ALLOW_BROKEN_CONDITIONALS=1
    cd roles/{{role}} && uv run molecule converge

# Run molecule verify (run verification tests only)
molecule-verify role:
    #!/usr/bin/env bash
    eval "$(just _export-docker-host)"
    export ANSIBLE_ALLOW_BROKEN_CONDITIONALS=1
    cd roles/{{role}} && uv run molecule verify

# Destroy molecule test containers
molecule-destroy role:
    #!/usr/bin/env bash
    eval "$(just _export-docker-host)"
    export ANSIBLE_ALLOW_BROKEN_CONDITIONALS=1
    cd roles/{{role}} && uv run molecule destroy

# SSH into running molecule container
molecule-login role:
    #!/usr/bin/env bash
    eval "$(just _export-docker-host)"
    export ANSIBLE_ALLOW_BROKEN_CONDITIONALS=1
    cd roles/{{role}} && uv run molecule login

# Run molecule tests for all roles that have molecule configs
molecule-test-all:
    #!/usr/bin/env bash
    set -euo pipefail
    eval "$(just _export-docker-host)"
    export ANSIBLE_ALLOW_BROKEN_CONDITIONALS=1

    shopt -s nullglob
    molecule_files=(roles/*/molecule/*/molecule.yml)

    if [[ ${#molecule_files[@]} -eq 0 ]]; then
        echo "No roles with molecule tests found"
        exit 0
    fi

    failed_roles=()
    for molecule_file in "${molecule_files[@]}"; do
        role_name=$(basename "$(dirname "$(dirname "$(dirname "$molecule_file")")")")
        scenario_name=$(basename "$(dirname "$molecule_file")")
        echo "========================================"
        echo "Testing role: $role_name (scenario: $scenario_name)"
        echo "========================================"
        if ! (cd "roles/$role_name" && uv run molecule test -s "$scenario_name"); then
            failed_roles+=("$role_name/$scenario_name")
        fi
    done

    if [[ ${#failed_roles[@]} -gt 0 ]]; then
        echo "========================================"
        echo "FAILED ROLES: ${failed_roles[*]}"
        echo "========================================"
        exit 1
    fi

    echo "All molecule tests passed!"

# Run molecule tests for all PostfixAdmin roles
molecule-test-postfixadmin:
    #!/usr/bin/env bash
    set -euo pipefail
    eval "$(just _export-docker-host)"
    export ANSIBLE_ALLOW_BROKEN_CONDITIONALS=1

    postfixadmin_roles=(
        "postfixadmin_deploy"
        "postfixadmin_backup"
        "postfixadmin_restore"
        "postfixadmin_remove"
    )

    failed_roles=()
    for role in "${postfixadmin_roles[@]}"; do
        if [[ -d "roles/$role/molecule" ]]; then
            echo "========================================"
            echo "Testing role: $role"
            echo "========================================"
            if ! (cd "roles/$role" && uv run molecule test); then
                failed_roles+=("$role")
            fi
        else
            echo "Skipping $role (no molecule tests)"
        fi
    done

    if [[ ${#failed_roles[@]} -gt 0 ]]; then
        echo "========================================"
        echo "FAILED ROLES: ${failed_roles[*]}"
        echo "========================================"
        exit 1
    fi

    echo "All PostfixAdmin molecule tests passed!"

# Help
help:
    @echo "ops-library Testing Commands"
    @echo ""
    @echo "Quick commands:"
    @echo "  just test           # Run all tests"
    @echo "  just test-roles     # Test all roles"
    @echo "  just lint           # Run ansible-lint"
    @echo "  just syntax-check   # Quick syntax validation"
    @echo ""
    @echo "Specific testing:"
    @echo "  just test-role fastdeploy_register_service"
    @echo "  just lint-role test_dummy"
    @echo ""
    @echo "Molecule (Docker-based integration tests):"
    @echo "  just molecule-test <role>         # Full test cycle for a role"
    @echo "  just molecule-converge <role>     # Apply without destroy (debugging)"
    @echo "  just molecule-verify <role>       # Run verification tests only"
    @echo "  just molecule-destroy <role>      # Destroy test containers"
    @echo "  just molecule-login <role>        # SSH into running container"
    @echo "  just molecule-test-all            # Test all roles with molecule"
    @echo "  just molecule-test-postfixadmin   # Test all PostfixAdmin roles"
    @echo ""
    @echo "Documentation:"
    @echo "  just docs-build     # Build documentation"
    @echo "  just docs-serve     # Serve documentation locally"
    @echo "  just docs-watch     # Watch and rebuild documentation"
    @echo "  just docs-check     # Check for broken links"
    @echo "  just docs-clean     # Clean build artifacts"
    @echo "  just docs-lint      # Validate documentation"
    @echo ""
    @echo "Setup:"
    @echo "  just setup          # Setup dev environment"
    @echo "  just venv           # Create virtual environment"
    @echo "  just deps           # Install dependencies"
    @echo ""
    @echo "Info:"
    @echo "  just status         # Show component overview"
    @echo "  just stats          # Show YAML lines of code (requires cloc)"
    @echo "  just stats-roles    # Show YAML lines per role (top 20)"
    @echo ""
    @echo "Run 'just' to see all available commands"
