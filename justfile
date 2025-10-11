# ops-library Justfile
# Testing and development automation for Ansible collection

# Default - show available commands
default:
    @just --list

# Setup development environment with pre-commit hooks
setup:
    @echo "Setting up development environment..."
    @./setup-pre-commit.sh

# Run ALL tests (roles, services, lint)
test: test-roles test-services lint
    @echo ""
    @echo "✅ All tests completed!"

# Test all roles
test-roles:
    @echo "Testing all roles..."
    @./test_roles.py --all

# Test a specific role
test-role ROLE:
    @echo "Testing role: {{ROLE}}"
    @./test_roles.py {{ROLE}}

# Test all services
test-services:
    @echo "Testing all services..."
    @./test_runner.sh all

# Test a specific service
test-service SERVICE="apt_upgrade":
    @echo "Testing service: {{SERVICE}}"
    @./test_runner.sh {{SERVICE}}

# Run molecule tests for apt_upgrade service
test-molecule ACTION="test":
    @echo "Running molecule {{ACTION}} for apt_upgrade..."
    @./test_apt_upgrade.sh {{ACTION}}

# Quick syntax check for everything
syntax-check:
    @echo "Running quick syntax check..."
    @./test_roles.py --all | grep -E "(Testing role:|YAML Syntax|✓ PASSED|✗ FAILED)" || true
    @./test_runner.sh all | grep -E "(Testing service:|syntax check|✓|✗)" || true

# Run ansible-lint on everything (non-failing for CI)
lint:
    @echo "Running ansible-lint..."
    @if [ -d .venv ]; then \
        source .venv/bin/activate && \
        echo "Linting roles..." && \
        ansible-lint roles/ 2>&1 | tail -3 || true && \
        echo "Linting services..." && \
        ansible-lint services/ 2>&1 | tail -3 || true; \
    else \
        echo "Virtual environment not found. Run 'just setup' first."; \
    fi

# Run strict ansible-lint (will fail on errors)
lint-strict:
    @echo "Running ansible-lint (strict mode)..."
    @source .venv/bin/activate && ansible-lint roles/ services/

# Run ansible-lint on a specific role
lint-role ROLE:
    @echo "Linting role: {{ROLE}}"
    @source .venv/bin/activate && ansible-lint roles/{{ROLE}}

# Run ansible-lint on a specific service
lint-service SERVICE="apt_upgrade":
    @echo "Linting service: {{SERVICE}}"
    @source .venv/bin/activate && ansible-lint services/{{SERVICE}}

# Run pre-commit on all files
pre-commit:
    @echo "Running pre-commit on all files..."
    @source .venv/bin/activate && pre-commit run --all-files

# Update pre-commit hooks to latest versions
pre-commit-update:
    @echo "Updating pre-commit hooks..."
    @source .venv/bin/activate && pre-commit autoupdate

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
    @echo "Services ($(ls -1 services | wc -l) total):"
    @ls -1 services | sed 's/^/  - /'
    @echo ""
    @echo "Run 'just test' to test everything"

# Test a service against a real host (be careful!)
test-remote SERVICE HOST:
    @echo "⚠️  Testing {{SERVICE}} against {{HOST}}"
    @echo "This will run in check mode only"
    @./test_service.sh {{SERVICE}} {{HOST}} remote

# Quick test - just syntax and structure
quick: syntax-check
    @echo "Quick test completed!"

# Full test suite with molecule (requires Docker)
test-full: test test-molecule
    @echo "Full test suite completed!"

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

# Help
help:
    @echo "ops-library Testing Commands"
    @echo ""
    @echo "Quick commands:"
    @echo "  just test           # Run all tests"
    @echo "  just test-roles     # Test all roles"
    @echo "  just test-services  # Test all services"
    @echo "  just lint           # Run ansible-lint"
    @echo "  just syntax-check   # Quick syntax validation"
    @echo ""
    @echo "Specific testing:"
    @echo "  just test-role fastdeploy_register_service"
    @echo "  just test-service apt_upgrade"
    @echo "  just lint-role test_dummy"
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
    @echo "Run 'just' to see all available commands"