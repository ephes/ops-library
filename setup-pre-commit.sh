#!/bin/bash
# Setup pre-commit hooks for ops-library

set -e

echo "=================================="
echo "Setting up pre-commit hooks"
echo "=================================="

# Check if we're in a git repository
if [ ! -d .git ]; then
    echo "Error: Not in a git repository. Please run from the ops-library root directory."
    exit 1
fi

# Activate virtual environment if it exists
if [ -d .venv ]; then
    echo "Activating virtual environment..."
    source .venv/bin/activate
else
    echo "Creating virtual environment..."
    uv venv .venv
    source .venv/bin/activate
fi

# Install/update dependencies
echo "Installing/updating dependencies..."
uv pip sync pyproject.toml

# Install pre-commit hooks
echo "Installing pre-commit hooks..."
pre-commit install

# Initialize secrets baseline (for detect-secrets hook)
if [ ! -f .secrets.baseline ]; then
    echo "Creating secrets baseline..."
    detect-secrets scan --baseline .secrets.baseline
fi

# Run pre-commit on all files to check current status
echo ""
echo "Running pre-commit checks on all files..."
echo "========================================="
pre-commit run --all-files || true

echo ""
echo "✅ Pre-commit setup complete!"
echo ""
echo "Pre-commit will now run automatically on git commit."
echo "To run manually: pre-commit run --all-files"
echo "To update hooks: pre-commit autoupdate"
echo "To skip hooks: git commit --no-verify"