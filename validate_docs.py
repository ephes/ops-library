#!/usr/bin/env python3
"""
Validate documentation integrity.

This script checks:
1. All role README files referenced in documentation exist
2. Root-level Markdown files don't contain broken relative links
"""

from pathlib import Path
import sys
import re

def main():
    errors = []

    # Check 1: Verify all role READMEs exist
    print("Checking role documentation...")
    docs_roles = Path("docs/source/roles")
    repo_roles = Path("roles")

    if not docs_roles.exists():
        errors.append("docs/source/roles directory does not exist")
    else:
        for role_doc in docs_roles.rglob("*.md"):
            if role_doc.name == "index.md":
                continue
            # Extract role name and check if README exists
            role_name = role_doc.stem
            expected_readme = repo_roles / role_name / "README.md"
            if not expected_readme.exists():
                errors.append(f"Missing README: {expected_readme} (referenced in {role_doc})")

    # Check 2: Scan for potentially broken relative links in included files
    print("Checking for relative links in root Markdown files...")
    root_md_files = ["README.md", "ARCHITECTURE.md", "TESTING.md", "README_TESTING.md", "CHANGELOG.md"]
    relative_link_pattern = re.compile(r'\[([^\]]+)\]\((\./[^\)]+|(?!https?://|#)[^\)]+\.md)\)')

    warnings = []
    for md_file in root_md_files:
        file_path = Path(md_file)
        if not file_path.exists():
            warnings.append(f"Note: {md_file} does not exist (expected for migration)")
            continue
        content = file_path.read_text()
        matches = relative_link_pattern.findall(content)
        if matches:
            warnings.append(f"Warning: {md_file} contains relative links that may break when included:")
            for link_text, link_url in matches:
                warnings.append(f"  [{link_text}]({link_url})")

    # Report results
    if errors:
        print("\n❌ Documentation validation FAILED:")
        for error in errors:
            print(f"  - {error}")
        print("\nPlease fix these issues before building documentation.")
        return 1

    if warnings:
        print("\n⚠️  Warnings:")
        for warning in warnings:
            print(f"  {warning}")
        print("\nThese warnings may indicate links that need to be updated.")
        print("Consider converting relative links to Sphinx :doc: references.")

    print("\n✅ Documentation validation passed!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
