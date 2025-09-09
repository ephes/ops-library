#!/usr/bin/env python3
"""
Simple Ansible role tester without virtualization
Tests using check mode and validates YAML/syntax
"""

import subprocess
import sys
import yaml
import json
from pathlib import Path

class AnsibleTester:
    def __init__(self, role_path, inventory="localhost,"):
        self.role_path = Path(role_path)
        self.inventory = inventory
        self.errors = []
        
    def test_yaml_syntax(self):
        """Test all YAML files are valid"""
        print("Testing YAML syntax...")
        yaml_files = list(self.role_path.rglob("*.yml")) + list(self.role_path.rglob("*.yaml"))
        
        for yaml_file in yaml_files:
            try:
                with open(yaml_file, 'r') as f:
                    yaml.safe_load(f)
                print(f"  ✓ {yaml_file.relative_to(self.role_path)}")
            except yaml.YAMLError as e:
                self.errors.append(f"YAML error in {yaml_file}: {e}")
                print(f"  ✗ {yaml_file.relative_to(self.role_path)}: {e}")
        
        return len(self.errors) == 0
    
    def test_ansible_syntax(self):
        """Test Ansible playbook syntax"""
        print("\nTesting Ansible syntax...")
        tasks_file = self.role_path / "tasks" / "main.yml"
        
        if not tasks_file.exists():
            print(f"  ✗ No tasks/main.yml found")
            return False
            
        # Create a temporary playbook
        test_playbook = f"""
---
- hosts: localhost
  gather_facts: no
  tasks:
    - include_tasks: {tasks_file}
"""
        
        try:
            result = subprocess.run(
                ["ansible-playbook", "--syntax-check", "-i", self.inventory, "/dev/stdin"],
                input=test_playbook,
                text=True,
                capture_output=True
            )
            
            if result.returncode == 0:
                print(f"  ✓ Ansible syntax valid")
                return True
            else:
                print(f"  ✗ Syntax error: {result.stderr}")
                self.errors.append(result.stderr)
                return False
                
        except Exception as e:
            print(f"  ✗ Error running syntax check: {e}")
            return False
    
    def test_templates(self):
        """Test Jinja2 templates are valid"""
        print("\nTesting templates...")
        template_dir = self.role_path / "templates"
        
        if not template_dir.exists():
            print("  No templates directory found")
            return True
            
        templates = list(template_dir.rglob("*.j2"))
        
        for template in templates:
            try:
                with open(template, 'r') as f:
                    content = f.read()
                    # Basic check for common Jinja2 syntax issues
                    if content.count("{{") != content.count("}}"):
                        raise ValueError("Mismatched {{ }} brackets")
                    if content.count("{%") != content.count("%}"):
                        raise ValueError("Mismatched {% %} brackets")
                        
                print(f"  ✓ {template.relative_to(self.role_path)}")
            except Exception as e:
                self.errors.append(f"Template error in {template}: {e}")
                print(f"  ✗ {template.relative_to(self.role_path)}: {e}")
                
        return len(self.errors) == 0
    
    def test_defaults(self):
        """Check that defaults are defined"""
        print("\nChecking defaults...")
        defaults_file = self.role_path / "defaults" / "main.yml"
        
        if defaults_file.exists():
            with open(defaults_file, 'r') as f:
                defaults = yaml.safe_load(f)
                if defaults:
                    print(f"  ✓ Found {len(defaults)} default variable(s)")
                    for key in defaults:
                        print(f"    - {key}")
                else:
                    print("  ⚠ No defaults defined")
        else:
            print("  ⚠ No defaults/main.yml found")
            
        return True
    
    def run_all_tests(self):
        """Run all tests"""
        print(f"\n{'='*50}")
        print(f"Testing role: {self.role_path}")
        print(f"{'='*50}")
        
        results = {
            "YAML Syntax": self.test_yaml_syntax(),
            "Ansible Syntax": self.test_ansible_syntax(),
            "Templates": self.test_templates(),
            "Defaults": self.test_defaults(),
        }
        
        print(f"\n{'='*50}")
        print("Test Results:")
        print(f"{'='*50}")
        
        for test, passed in results.items():
            status = "✓ PASSED" if passed else "✗ FAILED"
            print(f"{test:20} {status}")
            
        if self.errors:
            print(f"\nErrors found:")
            for error in self.errors:
                print(f"  - {error}")
                
        return all(results.values())


if __name__ == "__main__":
    # Test apt_upgrade service
    role_path = Path("services/apt_upgrade")
    
    if not role_path.exists():
        print(f"Error: {role_path} not found")
        print("Please run from ops-library directory")
        sys.exit(1)
        
    tester = AnsibleTester(role_path)
    success = tester.run_all_tests()
    
    sys.exit(0 if success else 1)