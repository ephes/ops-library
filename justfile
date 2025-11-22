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
