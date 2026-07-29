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

import yaml

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

    # Check 2: every role explicitly marked for rendered public documentation must
    # have a reachable category page. The marker lives with role defaults so adding a
    # new intended public role cannot silently omit it from Sphinx.
    print("Checking intended rendered role pages...")
    role_catalog = (docs_roles / "index.md").read_text(encoding="utf-8")
    for defaults_path in repo_roles.glob("*/defaults/main.yml"):
        defaults = yaml.safe_load(defaults_path.read_text(encoding="utf-8")) or {}
        category = defaults.get("ops_library_documentation_category")
        if not category:
            continue
        role_name = defaults_path.parents[1].name
        category_index = docs_roles / category / "index.md"
        role_page = docs_roles / category / f"{role_name}.md"
        if not category_index.exists():
            errors.append(f"Missing rendered category index: {category_index}")
            continue
        if f"{category}/index" not in role_catalog:
            errors.append(f"Rendered category is unreachable from role catalog: {category}/index")
        category_content = category_index.read_text(encoding="utf-8")
        if role_name not in category_content:
            errors.append(f"Rendered role omitted from category toctree: {role_name}")
        if not role_page.exists():
            errors.append(f"Missing rendered role page: {role_page}")
        elif f"roles/{role_name}/README.md" not in role_page.read_text(encoding="utf-8"):
            errors.append(f"Rendered role page does not include its README: {role_page}")

    # Check 3: Scan for potentially broken relative links in included files
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
