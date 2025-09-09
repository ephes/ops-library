#!/bin/bash
# Test script for ops-library services
# This is self-contained and doesn't depend on ops-control

set -e

echo "==================================="
echo "ops-library Service Tester"
echo "==================================="

# Parse arguments
SERVICE="${1:-apt_upgrade}"
TEST_HOST="${2:-localhost}"
TEST_TYPE="${3:-syntax}"  # syntax, local, or remote

echo "Service: $SERVICE"
echo "Host: $TEST_HOST"
echo "Test type: $TEST_TYPE"
echo ""

# Check if service exists
if [ ! -d "services/$SERVICE" ]; then
    echo "Error: Service 'services/$SERVICE' not found"
    echo "Available services:"
    ls -1 services/
    exit 1
fi

# Activate venv if it exists
if [ -d .venv ]; then
    source .venv/bin/activate
elif [ -d ../.venv ]; then
    source ../.venv/bin/activate
fi

# Create temporary test playbook
TEMP_PLAYBOOK=$(mktemp /tmp/test-playbook-XXXX.yml)

# Clean up on exit
trap "rm -f $TEMP_PLAYBOOK" EXIT

# Use existing inventory if available, otherwise create temp one
if [ -f "test/inventory.yml" ]; then
    INVENTORY_FILE="test/inventory.yml"
    echo "Using existing inventory: test/inventory.yml"
elif [ -f "test/inventory.ini" ]; then
    INVENTORY_FILE="test/inventory.ini"
    echo "Using existing inventory: test/inventory.ini"
else
    # Create temporary inventory only if no existing one
    TEMP_INVENTORY=$(mktemp /tmp/test-inventory-XXXX.yml)
    trap "rm -f $TEMP_PLAYBOOK $TEMP_INVENTORY" EXIT
    
    cat > "$TEMP_INVENTORY" <<EOF
all:
  hosts:
    $TEST_HOST:
      ansible_host: ${ANSIBLE_HOST:-$TEST_HOST}
      ansible_user: ${ANSIBLE_USER:-$USER}
      ansible_python_interpreter: ${ANSIBLE_PYTHON:-/usr/bin/python3}
EOF
    INVENTORY_FILE="$TEMP_INVENTORY"
    echo "Using temporary inventory"
fi

# Create test playbook
cat > "$TEMP_PLAYBOOK" <<EOF
---
- name: Test $SERVICE service
  hosts: $TEST_HOST
  gather_facts: yes
  become: ${ANSIBLE_BECOME:-false}
  
  vars:
    # Test-specific variables
    apt_upgrade_fastdeploy_enabled: false
    apt_upgrade_update_cache: false
    apt_upgrade_dist_upgrade: false
    apt_upgrade_auto_clean: false
    apt_upgrade_auto_remove: false
    
  tasks:
    - name: Include service tasks
      include_tasks: $(pwd)/services/$SERVICE/tasks/main.yml
EOF

case "$TEST_TYPE" in
    syntax)
        echo "Running syntax check..."
        ansible-playbook -i "$INVENTORY_FILE" "$TEMP_PLAYBOOK" --syntax-check
        
        echo ""
        echo "Running YAML lint..."
        if command -v yamllint &> /dev/null; then
            yamllint services/"$SERVICE"
        else
            echo "yamllint not installed, skipping"
        fi
        
        echo ""
        echo "Running Ansible lint..."
        if command -v ansible-lint &> /dev/null; then
            ansible-lint --offline services/"$SERVICE"
        else
            echo "ansible-lint not installed, skipping"
        fi
        ;;
        
    local)
        echo "Running local test (dry-run)..."
        ansible-playbook -i "$INVENTORY_FILE" "$TEMP_PLAYBOOK" --check --diff
        ;;
        
    remote)
        echo "Testing connectivity to $TEST_HOST..."
        ansible -i "$INVENTORY_FILE" "$TEST_HOST" -m ping
        
        echo ""
        echo "Running remote test (dry-run)..."
        ansible-playbook -i "$INVENTORY_FILE" "$TEMP_PLAYBOOK" --check --diff
        
        echo ""
        echo "Would you like to run the actual deployment? (y/n)"
        read -r response
        if [[ "$response" == "y" ]]; then
            ansible-playbook -i "$INVENTORY_FILE" "$TEMP_PLAYBOOK"
        fi
        ;;
        
    *)
        echo "Unknown test type: $TEST_TYPE"
        echo "Valid types: syntax, local, remote"
        exit 1
        ;;
esac

echo ""
echo "✅ Test completed successfully!"