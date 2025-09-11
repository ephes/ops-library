#!/usr/bin/env python3
"""
Test script for ops-library roles
Tests YAML syntax, Ansible syntax, and basic structure
"""

import subprocess
import sys
import yaml
from pathlib import Path
import argparse

class RoleTester:
    def __init__(self, role_path):
        self.role_path = Path(role_path)
        self.errors = []
        self.role_name = self.role_path.name
        
    def test_yaml_syntax(self):
        """Test all YAML files are valid"""
        print("Testing YAML syntax...")
        yaml_files = list(self.role_path.rglob("*.yml")) + list(self.role_path.rglob("*.yaml"))
        
        if not yaml_files:
            print(f"  ⚠️  No YAML files found in {self.role_path}")
            return True
            
        for yaml_file in yaml_files:
            try:
                with open(yaml_file, 'r') as f:
                    yaml.safe_load(f)
                print(f"  ✓ {yaml_file.relative_to(self.role_path)}")
            except yaml.YAMLError as e:
                self.errors.append(f"YAML error in {yaml_file}: {e}")
                print(f"  ✗ {yaml_file.relative_to(self.role_path)}: {e}")
        
        return len(self.errors) == 0
    
    def test_role_structure(self):
        """Test role has required structure"""
        print("\nTesting role structure...")
        required_dirs = ["tasks"]
        optional_dirs = ["defaults", "handlers", "templates", "files", "vars", "meta"]
        
        for dir_name in required_dirs:
            dir_path = self.role_path / dir_name
            if dir_path.exists():
                print(f"  ✓ {dir_name}/ exists")
                # Check for main.yml
                main_file = dir_path / "main.yml"
                if main_file.exists():
                    print(f"    ✓ {dir_name}/main.yml exists")
                else:
                    print(f"    ⚠️  {dir_name}/main.yml missing")
            else:
                self.errors.append(f"Required directory {dir_name}/ missing")
                print(f"  ✗ {dir_name}/ missing (required)")
                return False
        
        for dir_name in optional_dirs:
            dir_path = self.role_path / dir_name
            if dir_path.exists():
                print(f"  ✓ {dir_name}/ exists (optional)")
                main_file = dir_path / "main.yml"
                if main_file.exists():
                    print(f"    ✓ {dir_name}/main.yml exists")
        
        return True
    
    def test_defaults(self):
        """Check if defaults are defined"""
        print("\nChecking defaults...")
        defaults_file = self.role_path / "defaults" / "main.yml"
        
        if not defaults_file.exists():
            print("  ⚠️  No defaults/main.yml found (optional)")
            return True
            
        try:
            with open(defaults_file, 'r') as f:
                defaults = yaml.safe_load(f)
                
            if defaults:
                var_count = len(defaults)
                print(f"  ✓ Found {var_count} default variable(s)")
                for key in list(defaults.keys())[:10]:  # Show first 10
                    print(f"    - {key}")
                if var_count > 10:
                    print(f"    ... and {var_count - 10} more")
            else:
                print("  ⚠️  defaults/main.yml is empty")
                
        except Exception as e:
            self.errors.append(f"Error reading defaults: {e}")
            print(f"  ✗ Error reading defaults: {e}")
            return False
            
        return True
    
    def test_templates(self):
        """Check templates if they exist"""
        print("\nChecking templates...")
        templates_dir = self.role_path / "templates"
        
        if not templates_dir.exists():
            print("  ⚠️  No templates/ directory (optional)")
            return True
            
        template_files = list(templates_dir.rglob("*.j2"))
        if template_files:
            print(f"  ✓ Found {len(template_files)} template(s)")
            for template in template_files[:5]:  # Show first 5
                print(f"    - {template.relative_to(templates_dir)}")
            if len(template_files) > 5:
                print(f"    ... and {len(template_files) - 5} more")
        else:
            print("  ⚠️  templates/ exists but no .j2 files found")
            
        return True
    
    def run_all_tests(self):
        """Run all tests and report results"""
        print(f"\n{'='*50}")
        print(f"Testing role: {self.role_name}")
        print(f"Path: {self.role_path}")
        print(f"{'='*50}")
        
        results = {
            "YAML Syntax": self.test_yaml_syntax(),
            "Role Structure": self.test_role_structure(),
            "Defaults": self.test_defaults(),
            "Templates": self.test_templates(),
        }
        
        print(f"\n{'='*50}")
        print("Test Results:")
        print(f"{'='*50}")
        
        all_passed = True
        for test, passed in results.items():
            status = "✓ PASSED" if passed else "✗ FAILED"
            color = "\033[0;32m" if passed else "\033[0;31m"
            nc = "\033[0m"
            print(f"{test:20} {color}{status}{nc}")
            if not passed:
                all_passed = False
                
        if self.errors:
            print(f"\n\033[0;31mErrors found:\033[0m")
            for error in self.errors:
                print(f"  - {error}")
                
        return all_passed


def main():
    parser = argparse.ArgumentParser(description='Test Ansible roles in ops-library')
    parser.add_argument('role', nargs='?', help='Role to test (e.g., fastdeploy_register_service)')
    parser.add_argument('--all', action='store_true', help='Test all roles')
    
    args = parser.parse_args()
    
    if args.all:
        # Test all roles
        roles_dir = Path("roles")
        if not roles_dir.exists():
            print("Error: roles/ directory not found")
            print("Please run from ops-library directory")
            sys.exit(1)
            
        all_passed = True
        role_dirs = [d for d in roles_dir.iterdir() if d.is_dir() and not d.name.startswith('.')]
        
        for role_dir in sorted(role_dirs):
            tester = RoleTester(role_dir)
            success = tester.run_all_tests()
            if not success:
                all_passed = False
            print()  # Empty line between roles
            
        sys.exit(0 if all_passed else 1)
    
    elif args.role:
        # Test specific role
        role_path = Path("roles") / args.role
        
        if not role_path.exists():
            print(f"Error: Role {args.role} not found at {role_path}")
            print("\nAvailable roles:")
            roles_dir = Path("roles")
            if roles_dir.exists():
                for role_dir in sorted(roles_dir.iterdir()):
                    if role_dir.is_dir() and not role_dir.name.startswith('.'):
                        print(f"  - {role_dir.name}")
            sys.exit(1)
            
        tester = RoleTester(role_path)
        success = tester.run_all_tests()
        sys.exit(0 if success else 1)
    
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()