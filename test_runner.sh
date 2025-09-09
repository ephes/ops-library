#!/bin/bash
# Comprehensive test runner for ops-library
# Can test services independently without ops-control

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "==================================="
echo "ops-library Test Runner"
echo "==================================="

# Configuration
SERVICE="${1:-}"
INVENTORY="${2:-test/inventory.yml}"
ANSIBLE_OPTS="${ANSIBLE_OPTS:-}"

# Help function
show_help() {
    cat << EOF
Usage: $0 [SERVICE] [INVENTORY_FILE]

Test ops-library services independently.

Arguments:
  SERVICE         Service to test (default: all services)
  INVENTORY_FILE  Ansible inventory file (default: test/inventory.yml)

Environment variables:
  ANSIBLE_HOST    Override host for testing
  ANSIBLE_USER    Override user for testing
  ANSIBLE_BECOME  Set to 'true' to use sudo
  ANSIBLE_OPTS    Additional ansible-playbook options

Examples:
  # Test apt_upgrade service syntax
  $0 apt_upgrade

  # Test all services
  $0 all

  # Test with custom inventory
  $0 apt_upgrade my-inventory.yml

  # Test remote host
  ANSIBLE_HOST=macmini.local ANSIBLE_USER=root $0 apt_upgrade

EOF
    exit 0
}

# Check for help
if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    show_help
fi

# Check if inventory exists, if not create from example
if [ ! -f "$INVENTORY" ]; then
    if [ -f "test/inventory.example.yml" ]; then
        echo -e "${YELLOW}Creating inventory from example...${NC}"
        mkdir -p test
        cp test/inventory.example.yml "$INVENTORY"
        echo -e "${GREEN}Created $INVENTORY - please customize it${NC}"
    else
        echo -e "${YELLOW}No inventory found. Creating minimal one...${NC}"
        mkdir -p test
        cat > "$INVENTORY" <<EOF
all:
  hosts:
    localhost:
      ansible_connection: local
      ansible_python_interpreter: auto
EOF
    fi
fi

# Activate virtual environment
if [ -d .venv ]; then
    echo "Activating virtual environment..."
    source .venv/bin/activate
fi

# Function to test a single service
test_service() {
    local service=$1
    echo ""
    echo -e "${GREEN}Testing service: $service${NC}"
    echo "----------------------------------------"
    
    if [ ! -d "services/$service" ]; then
        echo -e "${RED}✗ Service not found: services/$service${NC}"
        return 1
    fi
    
    # Check YAML syntax
    echo -n "  YAML syntax check... "
    if yamllint -c .yamllint "services/$service" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
        yamllint -c .yamllint "services/$service"
    fi
    
    # Check Ansible syntax
    echo -n "  Ansible syntax check... "
    TEMP_PLAYBOOK=$(mktemp /tmp/test-$service-XXXX.yml)
    cat > "$TEMP_PLAYBOOK" <<EOF
---
- name: Test $service
  hosts: localhost
  gather_facts: no
  tasks:
    - name: Include service tasks
      include_tasks: $(pwd)/services/$service/tasks/main.yml
      vars:
        apt_upgrade_fastdeploy_enabled: false
        apt_upgrade_update_cache: false
        apt_upgrade_dist_upgrade: false
EOF
    
    if ansible-playbook -i "$INVENTORY" "$TEMP_PLAYBOOK" --syntax-check > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
        ansible-playbook -i "$INVENTORY" "$TEMP_PLAYBOOK" --syntax-check
    fi
    rm -f "$TEMP_PLAYBOOK"
    
    # Check with ansible-lint
    echo -n "  Ansible lint check... "
    if ansible-lint --offline "services/$service" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${YELLOW}⚠ (warnings)${NC}"
    fi
    
    # Check templates
    if [ -d "services/$service/templates" ]; then
        echo -n "  Template syntax check... "
        template_errors=0
        for template in services/$service/templates/**/*.j2; do
            if [ -f "$template" ]; then
                # Basic syntax check for Jinja2
                if ! python3 -c "
import jinja2
with open('$template', 'r') as f:
    try:
        jinja2.Template(f.read())
    except:
        exit(1)
" 2>/dev/null; then
                    template_errors=$((template_errors + 1))
                fi
            fi
        done
        
        if [ $template_errors -eq 0 ]; then
            echo -e "${GREEN}✓${NC}"
        else
            echo -e "${RED}✗ ($template_errors errors)${NC}"
        fi
    fi
    
    echo -e "  ${GREEN}Service test complete${NC}"
    return 0
}

# Main logic
if [ -z "$SERVICE" ] || [ "$SERVICE" == "all" ]; then
    # Test all services
    echo "Testing all services..."
    for service_dir in services/*/; do
        if [ -d "$service_dir" ]; then
            service=$(basename "$service_dir")
            test_service "$service" || true
        fi
    done
else
    # Test specific service
    test_service "$SERVICE"
fi

echo ""
echo "==================================="
echo -e "${GREEN}✅ Testing complete!${NC}"
echo "==================================="
echo ""
echo "To test against a real host:"
echo "  ANSIBLE_HOST=macmini.local $0 apt_upgrade"
echo ""
echo "To run actual deployment (be careful!):"
echo "  ansible-playbook -i $INVENTORY playbooks/deploy.yml"