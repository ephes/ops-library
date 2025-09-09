#!/bin/bash
# Test runner for apt_upgrade service using molecule

set -e

echo "==================================="
echo "APT Upgrade Service Test Runner"
echo "==================================="

# Activate virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment with uv..."
    uv venv .venv
fi

echo "Activating virtual environment..."
source .venv/bin/activate

# Check if dependencies are installed
if ! command -v molecule &> /dev/null; then
    echo "Installing test dependencies..."
    uv pip install molecule molecule-docker ansible-lint yamllint pytest
fi

# Navigate to service directory
cd services/apt_upgrade

# Run tests
echo ""
echo "Running molecule tests..."
echo "========================="

# Test options
case "${1:-test}" in
    create)
        echo "Creating test containers..."
        molecule create
        ;;
    converge)
        echo "Running convergence..."
        molecule converge
        ;;
    verify)
        echo "Running verification..."
        molecule verify
        ;;
    test)
        echo "Running full test suite..."
        molecule test
        ;;
    destroy)
        echo "Destroying test containers..."
        molecule destroy
        ;;
    lint)
        echo "Running linters..."
        molecule lint
        yamllint .
        ansible-lint
        ;;
    *)
        echo "Usage: $0 {create|converge|verify|test|destroy|lint}"
        exit 1
        ;;
esac

echo ""
echo "Test execution completed!"