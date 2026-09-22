# Specification: Browsable Documentation on ReadTheDocs

**Date:** 2025-10-07
**Status:** Ready for Implementation
**Goal:** Make ops-library Ansible role documentation browsable and host it on ReadTheDocs

---

## Overview

Transform the existing Markdown documentation into a browsable, searchable documentation website hosted on ReadTheDocs. This will improve discoverability and provide a professional documentation experience for users of the ops-library Ansible collection.

---

## Requirements

### 1. Documentation Framework

#### 1.1 Core Technologies
- **Sphinx** as the documentation generator
- **MyST Parser** for Markdown support (allows keeping existing .md files)
- **Furo theme** for modern, clean documentation appearance

#### 1.2 File Structure
```
ops-library-documentation/
├── docs/
│   ├── source/                   # Sphinx source directory
│   │   ├── conf.py              # Sphinx configuration (reads galaxy.yml for version)
│   │   ├── index.md             # Main documentation landing page (MyST Markdown)
│   │   ├── architecture.md      # Include/symlink to ../../ARCHITECTURE.md
│   │   ├── testing.md           # Include/symlink to ../../TESTING.md
│   │   ├── changelog.md         # Include/symlink to ../../CHANGELOG.md
│   │   ├── roles/               # Role documentation directory
│   │   │   ├── index.md         # Roles overview/index with category sections
│   │   │   ├── deployment/      # Deployment roles category
│   │   │   │   ├── index.md     # Category landing page with role list
│   │   │   │   ├── fastdeploy_deploy.md  # MyST include of role README
│   │   │   │   ├── nyxmon_deploy.md      # MyST include of role README
│   │   │   │   └── ...
│   │   │   ├── removal/         # Removal roles category
│   │   │   ├── registration/    # Registration roles category
│   │   │   ├── bootstrap/       # Bootstrap roles category
│   │   │   └── testing/         # Testing roles category
│   │   └── _static/             # Static assets (logos, etc.)
│   ├── build/                   # Generated HTML (git-ignored)
│   └── Makefile                 # Sphinx makefile
├── .readthedocs.yaml            # ReadTheDocs configuration
├── requirements-docs.txt        # Documentation build dependencies (RTD)
└── requirements-docs-dev.txt    # Local development dependencies (sphinx-autobuild)
```

**Rationale for index.md:**
- Use `index.md` (Markdown) instead of `index.rst` (reStructuredText) to maintain consistency with existing documentation
- MyST Parser allows full Markdown usage while providing Sphinx features
- Easier for contributors familiar with Markdown
- Existing role READMEs are all in Markdown

### 2. Just Commands (Developer Experience)

Add the following commands to the `justfile`:

**Note:** Local development commands should use `requirements-docs-dev.txt` which includes `sphinx-autobuild` for live reload functionality.

#### 2.1 `just docs-build`
- Build the documentation locally
- Output to `docs/build/html`
- Command: `sphinx-build -b html docs/source docs/build/html`

#### 2.2 `just docs-serve`
- View documentation locally in a browser
- Start a local HTTP server serving `docs/build/html`
- Command: `python -m http.server 8000 -d docs/build/html`
- Should print URL to access (e.g., http://localhost:8000)

#### 2.3 `just docs-watch`
- Watch mode for documentation with auto-rebuild
- Use `sphinx-autobuild` for live reload
- Command: `sphinx-autobuild docs/source docs/build/html --watch roles --watch README.md --watch ARCHITECTURE.md --watch TESTING.md --watch README_TESTING.md --watch CHANGELOG.md`
- Should open browser automatically or print URL
- **Note:** Watch all root-level documentation files that are included in Sphinx docs so live reload catches any edits without manual rebuild

#### 2.4 `just docs-check`
- Check documentation for broken links
- Use Sphinx linkcheck builder
- Command: `sphinx-build -b linkcheck docs/source docs/build/linkcheck`
- Should report any broken internal or external links

#### 2.5 `just docs-clean`
- Clean documentation build artifacts
- Remove `docs/build/` directory
- Command: `sphinx-build -M clean docs/source docs/build` (cross-platform)
- Alternative: Use Python to remove directory for better cross-platform support
- Rationale: `sphinx-build -M clean` is cross-platform and works on Windows, Linux, and macOS

#### 2.6 `just docs-lint`
- Validate documentation integrity
- Check that all role READMEs referenced in documentation exist
- Run a Python script to verify includes (see section 9.2 for implementation)
- Should be added to pre-commit hooks or CI pipeline

### 3. Documentation Content Requirements

#### 3.1 Landing Page (index)
- Project overview and purpose
- Quick start / installation instructions
- Link to architecture documentation
- Link to role catalog
- Link to testing documentation
- Link to changelog

#### 3.2 Role Documentation

**Organized by category:**
- Deployment roles (fastdeploy_deploy, nyxmon_deploy, traefik_deploy, etc.)
- Removal roles (fastdeploy_remove, nyxmon_remove, traefik_remove, etc.)
- Registration roles (apt_upgrade_register, fastdeploy_register_service)
- Bootstrap roles (ansible_install, uv_install, sops_dependencies)
- Testing/Demo roles (test_dummy)

**How role READMEs are surfaced:**

Each role documentation page (e.g., `docs/source/roles/deployment/fastdeploy_deploy.md`) uses MyST's `include` directive:

**Option A: Direct include (recommended)**
```markdown
```{include} ../../../../roles/fastdeploy_deploy/README.md
```
```

**Option B: With heading adjustment (if needed)**
```markdown
```{include} ../../../../roles/fastdeploy_deploy/README.md
:heading-offset: 1
```
```

**Important - Avoid duplicate H1 headings:**
- Do NOT add a manual H1 heading in the wrapper file (e.g., `# FastDeploy Deploy`)
- The included README already contains its own H1 heading
- If you need a different heading structure, use `:heading-offset:` to demote all headings by N levels
- Duplicate top-level headings will confuse Sphinx's table of contents and navigation

This approach:
- Maintains single source of truth (role README stays in `roles/`)
- Automatically includes all content without duplication
- Preserves existing sections (Description, Requirements, Variables, Examples)
- Updates documentation when role README changes
- Avoids duplicate H1 headings that break navigation

**Category index pages** (e.g., `docs/source/roles/deployment/index.md`) use MyST's `toctree` directive:

```markdown
# Deployment Roles

```{toctree}
:maxdepth: 1

fastdeploy_deploy
nyxmon_deploy
traefik_deploy
```
```

**Each role page includes:**
- Full content from `roles/{role_name}/README.md` via MyST include
- Breadcrumb navigation (automatic via Furo theme)
- "Edit on GitHub" link (configured in conf.py)

#### 3.3 Existing Documentation Integration
- Include/link the following root-level documents:
  - `README.md` → Overview/Quick Start
  - `ARCHITECTURE.md` → Architecture section
  - `TESTING.md` → Testing Guide
  - `README_TESTING.md` → Quick Testing Reference
  - `CHANGELOG.md` → Version History
- Evaluate existing `docs/README.md`: reuse if useful, otherwise rewrite as needed

**Critical: Handling Relative Links**

When including root-level Markdown files (README.md, ARCHITECTURE.md, etc.), their relative links will break because they resolve from the Sphinx page's location, not the original file location.

**Example Problem:**
- Original `README.md` contains: `[Architecture](./ARCHITECTURE.md)`
- When included in `docs/source/overview.md`, the link tries to resolve to `docs/source/ARCHITECTURE.md` (doesn't exist)
- Expected: Should resolve to `../../ARCHITECTURE.md` or use Sphinx `:doc:` reference

**Strategy: Fix relative links during migration**

**Option 1: Convert to Sphinx :doc: references (recommended)**
```markdown
<!-- Before (in original README.md) -->
[Architecture](./ARCHITECTURE.md)
[Role Documentation](./roles/fastdeploy_deploy/README.md)

<!-- After (in docs/source/overview.md) -->
{doc}`architecture`
{doc}`roles/deployment/fastdeploy_deploy`
```

**Option 2: Adjust relative paths**
```markdown
<!-- Before (in original README.md) -->
[Architecture](./ARCHITECTURE.md)

<!-- After (when migrated/included) -->
[Architecture](../../ARCHITECTURE.md)
```

**Option 3: Create symlinks in docs/source/**
```bash
cd docs/source/
ln -s ../../ARCHITECTURE.md architecture.md
ln -s ../../TESTING.md testing.md
```

**Implementation checklist:**
1. Audit all root-level Markdown files for relative links
2. Choose conversion strategy (prefer :doc: references)
3. Update links during migration or via automated script
4. Add link validation to `just docs-lint` to catch broken references
5. Test all navigation paths after migration

#### 3.4 Navigation Structure
```
Home
├── Overview (README content)
├── Architecture (ARCHITECTURE.md)
├── Roles
│   ├── Overview (table from README)
│   ├── Deployment Roles
│   │   ├── FastDeploy Deploy
│   │   ├── Nyxmon Deploy
│   │   ├── Traefik Deploy
│   │   └── ...
│   ├── Removal Roles
│   │   ├── FastDeploy Remove
│   │   ├── Nyxmon Remove
│   │   └── ...
│   ├── Registration Roles
│   │   ├── APT Upgrade Register
│   │   └── FastDeploy Register Service
│   ├── Bootstrap Roles
│   │   ├── Ansible Install
│   │   ├── UV Install
│   │   └── SOPS Dependencies
│   └── Testing Roles
│       └── Test Dummy
├── Testing
│   ├── Testing Guide (TESTING.md)
│   └── Quick Reference (README_TESTING.md)
└── Changelog (CHANGELOG.md)
```

### 4. ReadTheDocs Configuration

#### 4.1 `.readthedocs.yaml`
- Specify Python version (3.11 or later)
- Specify build dependencies from `requirements-docs.txt`
- Configure Sphinx as the documentation builder
- Set documentation source directory

#### 4.2 Documentation Dependencies

**`requirements-docs.txt` (ReadTheDocs build):**
Lean dependencies for ReadTheDocs - only what's needed to build documentation:
```
sphinx>=7.0
myst-parser>=2.0
furo>=2024.0
sphinx-copybutton>=0.5
PyYAML>=6.0  # For reading galaxy.yml in conf.py
linkify-it-py>=2.0  # Required for myst_enable_extensions "linkify"
```

**`requirements-docs-dev.txt` (Local development):**
Additional dependencies for local development workflow:
```
-r requirements-docs.txt  # Include base requirements
sphinx-autobuild>=2024.0  # Live reload server for docs-watch
```

**Rationale:**
- ReadTheDocs doesn't need `sphinx-autobuild` (watcher for local development)
- Splitting dependencies prevents unnecessary packages in RTD builds
- Reduces build warnings and potential conflicts
- Keeps RTD builds fast and minimal

#### 4.3 ReadTheDocs Project Setup
- Connect to GitHub repository
- Configure webhook for automatic builds on push to main branch
- Use default subdomain: `ops-library.readthedocs.io`
- Single version build (main branch only, no version tags)

### 5. Sphinx Configuration (`docs/source/conf.py`)

#### 5.1 Required Extensions
```python
extensions = [
    'myst_parser',           # MyST Markdown support
    'sphinx.ext.autosectionlabel',  # Auto-generate section labels
    'sphinx.ext.intersphinx',       # Link to other projects
    'sphinx_copybutton',            # Copy button for code blocks
]

# Prevent duplicate label warnings when multiple role READMEs have same headings
# (e.g., "Requirements", "Variables", "Examples" appear in every role)
autosectionlabel_prefix_document = True  # Namespace labels by document path
autosectionlabel_maxdepth = 3            # Only auto-label up to H3
```

**Rationale:**
- Without `autosectionlabel_prefix_document = True`, Sphinx will raise warnings when multiple role READMEs contain identical section headings like "Requirements" or "Variables"
- Setting this to `True` namespaces each label by its document path (e.g., `roles/deployment/fastdeploy_deploy:requirements` vs `roles/deployment/nyxmon_deploy:requirements`)
- This allows cross-referencing specific sections without label collisions

#### 5.2 Theme Configuration
```python
html_theme = 'furo'
html_theme_options = {
    # "Edit on GitHub" link configuration for Furo theme
    "source_repository": "https://github.com/yourusername/ops-library",
    "source_branch": "main",
    "source_directory": "docs/source/",

    # Optional: Customize appearance
    # "light_css_variables": {
    #     "color-brand-primary": "#2980b9",
    #     "color-brand-content": "#2980b9",
    # },
}
```

**Important:**
- Furo requires `source_repository`, `source_branch`, and `source_directory` in `html_theme_options` (NOT `html_context`) for "Edit on GitHub" links to appear
- Update `source_repository` URL with the actual GitHub repository
- Without these options, edit buttons will be absent on ReadTheDocs
- The `source_directory` should match where the Sphinx source files live relative to repository root

#### 5.3 MyST Configuration

Concrete configuration in `conf.py`:

```python
myst_enable_extensions = [
    "colon_fence",      # ::: directives (alternative to backtick fences)
    "deflist",          # Definition lists
    "fieldlist",        # Field lists
    "substitution",     # Variable substitutions
    "tasklist",         # GitHub-style task lists (- [ ] and - [x])
    "linkify",          # Auto-convert URLs to links
    "attrs_block",      # Block attributes {.class #id}
]

myst_heading_anchors = 3  # Auto-generate anchors for h1, h2, h3
```

This ensures existing Markdown in role READMEs renders correctly, including:
- Tables (built-in MyST support)
- Code fences with syntax highlighting (built-in)
- Definition lists (via `deflist`)
- Task lists for examples/checklists (via `tasklist`)
- Auto-linked URLs (via `linkify` - requires `linkify-it-py` package)

**Note:** The `linkify` extension requires the `linkify-it-py` package to be installed. Without it, the build will fail with an import error. This dependency is included in `requirements-docs.txt`.

#### 5.4 Project Metadata

Include a helper in `conf.py` that reads version from `galaxy.yml`:

```python
from pathlib import Path
import yaml

# Read version from galaxy.yml
galaxy_yml_path = Path(__file__).parent.parent.parent / "galaxy.yml"
with open(galaxy_yml_path) as f:
    galaxy_data = yaml.safe_load(f)

# Project information
project = "ops-library"
author = galaxy_data.get("authors", ["Jochen Wersdörfer"])[0]
version = galaxy_data.get("version", "0.1.0")
release = version
copyright = f"2025, {author}"
```

**Rationale:**
- Automatically syncs documentation version with collection version
- Eliminates manual version updates in multiple files
- Reduces risk of version mismatch when cutting releases
- Single source of truth in `galaxy.yml`

**Note:** GitHub repository information is configured in `html_theme_options` (see section 5.2), not in `html_context`

### 6. Cross-References and Links

#### 6.1 Internal Linking
- All role documentation should be cross-referenced
- Architecture documentation should link to relevant roles
- Testing documentation should reference specific test commands

#### 6.2 External Linking
- Link to Ansible documentation
- Link to collection dependencies (community.general, ansible.posix)
- Link to GitHub repository
- Link to issue tracker

### 7. README.md Integration

#### 7.1 Link to Documentation
Add a prominent link at the top of `README.md`:
```markdown
# Ops Library

📚 **[Full Documentation](https://ops-library.readthedocs.io/)** | [Architecture](./ARCHITECTURE.md) | [Testing](./TESTING.md)
```

Or if preferred:
```markdown
# Ops Library

A collection of reusable Ansible roles for homelab automation and service deployment.

📖 **[Read the full documentation on ReadTheDocs](https://ops-library.readthedocs.io/)**
```

#### 7.2 Update Existing Documentation Link Section
Replace or enhance the current documentation section to prominently feature the ReadTheDocs link

### 8. Build and Deployment Process

#### 8.1 Local Development Workflow
1. Developer edits documentation (role READMEs, guides, etc.)
2. Run `just docs-watch` to preview changes
3. Run `just docs-check` to verify links
4. Commit changes to git

#### 8.2 CI/CD Integration (Optional but Recommended)
- Add documentation validation to pre-commit hooks:
  - Run `just docs-lint` to catch missing READMEs and broken relative links
  - Run `just docs-build` to verify documentation builds without errors or warnings
- Add to CI pipeline:
  - `just docs-lint` - Validate documentation integrity
  - `just docs-build` - Build documentation to catch Sphinx errors
  - `just docs-check` - Verify no broken links (can be slow, consider making optional)
- Fail the build on any errors to ensure documentation quality

#### 8.3 ReadTheDocs Automation
- Automatic build on every commit to main branch
- Automatic build on pull requests (preview)
- Publish to readthedocs.io domain

### 9. Documentation Maintenance

#### 9.1 Keeping Content in Sync

**Source of Truth:**
- Role documentation lives in `roles/{role}/README.md` (single source of truth)
- Sphinx uses MyST include directives to reference these files (no duplication)
- Top-level docs (ARCHITECTURE.md, TESTING.md) remain in root
- Use MyST include directives to avoid duplication

**Handling docs/README.md:**
- **Decision:** Migrate useful content from existing `docs/README.md` into the Sphinx documentation structure
- Retire `docs/README.md` after migration to avoid maintaining two competing documentation homes
- Update any references to point to the new ReadTheDocs site
- Add a simple redirect note in `docs/README.md` if needed: "Documentation has moved to https://ops-library.readthedocs.io/"

#### 9.2 Lint Checks for Documentation Integrity

Add a documentation validation script or just command (`just docs-lint`) to catch:

**Broken includes:**
```python
# Script: validate_docs.py
# Verify all role READMEs exist and check for broken relative links
from pathlib import Path
import sys
import re

errors = []

# Check 1: Verify all role READMEs exist
docs_roles = Path("docs/source/roles")
repo_roles = Path("roles")

for role_doc in docs_roles.rglob("*.md"):
    if role_doc.name == "index.md":
        continue
    # Extract role name and check if README exists
    role_name = role_doc.stem
    expected_readme = repo_roles / role_name / "README.md"
    if not expected_readme.exists():
        errors.append(f"Missing README: {expected_readme}")

# Check 2: Scan for potentially broken relative links in included files
# Look for Markdown links that might not resolve correctly
root_md_files = ["README.md", "ARCHITECTURE.md", "TESTING.md", "README_TESTING.md"]
relative_link_pattern = re.compile(r'\[([^\]]+)\]\((\./[^\)]+|(?!https?://)[^\)]+\.md)\)')

for md_file in root_md_files:
    file_path = Path(md_file)
    if not file_path.exists():
        continue
    content = file_path.read_text()
    matches = relative_link_pattern.findall(content)
    if matches:
        errors.append(f"Warning: {md_file} contains relative links that may break when included:")
        for link_text, link_url in matches:
            errors.append(f"  [{link_text}]({link_url})")

if errors:
    print("Documentation validation errors:")
    for error in errors:
        print(f"  - {error}")
    print("\nPlease fix these issues before building documentation.")
    sys.exit(1)
else:
    print("✓ Documentation validation passed!")
```

**New role onboarding checklist:**
1. Create role directory with README.md: `roles/{role_name}/README.md`
2. Create wrapper doc in appropriate category: `docs/source/roles/{category}/{role_name}.md`
3. Add MyST include directive in wrapper (NO manual H1 heading - the included README has one):
   ```markdown
   ```{include} ../../../../roles/{role_name}/README.md
   ```
   ```
4. Add to category index toctree: `docs/source/roles/{category}/index.md`
5. Verify no relative links in the role README that might break, or convert them to Sphinx `:doc:` references
6. Run `just docs-lint` to verify all includes work and catch broken links
7. Run `just docs-build` to verify documentation builds without warnings
8. Run `just docs-check` to verify no broken links

**CI Guard:**
- Add documentation lint check to pre-commit hooks or CI
- Fail the build if role READMEs are missing
- Fail the build if documentation doesn't build cleanly

#### 9.3 Version Management
- Sync version number in `docs/source/conf.py` with `galaxy.yml` (automatic via helper function)
- Single version documentation (main branch only)
- Documentation is NOT versioned to match collection releases
- Always shows the latest documentation from main branch

### 10. Nice-to-Have Features (Optional)

#### 10.1 Search
- Full-text search (built into Sphinx/ReadTheDocs)
- Search configuration for better results

#### 10.2 Code Examples
- Syntax highlighting for YAML, shell, Python
- Copy buttons on all code blocks (via sphinx-copybutton)
- Line numbers where appropriate

#### 10.3 Navigation Enhancements
- Table of contents on each page
- Breadcrumb navigation
- "Next/Previous" page navigation
- "Edit this page on GitHub" link

#### 10.4 Social/Meta Tags
- OpenGraph tags for social media sharing
- Proper page titles and descriptions

---

## Success Criteria

1. ✅ Documentation is successfully built and published on ReadTheDocs
2. ✅ All existing role READMEs are accessible through the documentation
3. ✅ Navigation is intuitive with clear categorization
4. ✅ `just docs-*` commands work correctly for local development
5. ✅ No broken internal or external links
6. ✅ Documentation automatically rebuilds on git push
7. ✅ README.md contains prominent link to ReadTheDocs
8. ✅ Documentation uses Furo theme with clean, modern appearance
9. ✅ Search functionality works correctly
10. ✅ Code blocks have syntax highlighting and copy buttons

---

## Out of Scope

- Generating API documentation from code (roles are declarative YAML)
- Multi-language support (English only)
- Custom domain setup (using default ops-library.readthedocs.io)
- PDF builds for offline documentation
- Versioned documentation (only main branch, not tied to collection releases)
- Analytics integration
- Comment/feedback system on documentation pages
- Custom branding/logo (beyond basic Furo theme configuration)

---

## Implementation Notes

- **Do not duplicate content:** Use includes/references to maintain single source of truth
- **Preserve existing structure:** Keep role READMEs in their current locations
- **Git-ignore build artifacts:** Add `docs/build/` to `.gitignore`
- **Test thoroughly:** Verify all links and navigation before going live
- **Mobile-responsive:** Furo theme should work well on mobile devices
- **Accessibility:** Ensure documentation meets basic accessibility standards

## Critical Configuration Gotchas

These are easy-to-miss configuration issues that will cause problems if not addressed:

1. **Duplicate section labels** (Section 5.1)
   - **Problem:** Multiple role READMEs contain identical headings ("Requirements", "Variables", etc.)
   - **Solution:** Set `autosectionlabel_prefix_document = True` in conf.py
   - **Symptom if missing:** Sphinx warnings about duplicate label targets

2. **"Edit on GitHub" links missing** (Section 5.2)
   - **Problem:** Furo theme requires specific configuration keys
   - **Solution:** Use `html_theme_options` with `source_repository`, `source_branch`, `source_directory` (NOT `html_context`)
   - **Symptom if missing:** No edit buttons on documentation pages

3. **Duplicate H1 headings** (Section 3.2)
   - **Problem:** Adding manual heading in wrapper file AND including README (which has its own H1)
   - **Solution:** Do NOT add manual H1 in wrapper files - let the included README provide the heading
   - **Symptom if missing:** Confusing table of contents, broken navigation hierarchy

4. **Broken relative links** (Section 3.3)
   - **Problem:** Included Markdown files contain relative links that resolve incorrectly from new location
   - **Solution:** Convert to Sphinx `:doc:` references or adjust paths; add validation to `just docs-lint`
   - **Symptom if missing:** 404 errors when clicking links in documentation

5. **Split dependencies** (Section 4.2)
   - **Problem:** Including `sphinx-autobuild` in RTD builds causes unnecessary warnings
   - **Solution:** Use `requirements-docs.txt` for RTD, `requirements-docs-dev.txt` for local development
   - **Symptom if missing:** Slower RTD builds, potential warnings in build logs

6. **Missing linkify-it-py dependency** (Section 5.3)
   - **Problem:** `myst_enable_extensions` includes `"linkify"` but `linkify-it-py` package is not installed
   - **Solution:** Add `linkify-it-py>=2.0` to both `requirements-docs.txt` and `requirements-docs-dev.txt`
   - **Symptom if missing:** Build fails with ImportError when Sphinx tries to use the linkify extension

---

## Decisions

The following decisions have been made for this implementation:

1. **Subdomain:** Use default `ops-library.readthedocs.io` (no custom domain)
2. **Versioning:** Single version only (main branch), no version tags or multi-version builds
3. **Existing docs/README.md:** Evaluate and reuse if useful, otherwise rewrite as needed
4. **Custom branding:** Not required at this time (standard Furo theme is sufficient)
5. **PDF builds:** Not required at this time (HTML documentation only)
6. **Version matching:** Documentation is NOT tied to collection releases in galaxy.yml
7. **Python version:** Python 3.11+ (not 3.8+)

---

## Dependencies

### Python Packages (Build)
Core packages needed for ReadTheDocs builds:
- sphinx>=7.0
- myst-parser>=2.0
- furo>=2024.0
- sphinx-copybutton>=0.5
- PyYAML>=6.0
- linkify-it-py>=2.0  # Required for MyST "linkify" extension

### Python Packages (Local Development)
Additional packages for local development:
- sphinx-autobuild>=2024.0

### Development Tools
- just (for running documentation commands)
- Python 3.11+
- Git

### External Services
- ReadTheDocs account
- GitHub repository with webhook access

---

## Timeline Estimate

- Initial Sphinx setup: 2-4 hours
- Content organization and migration: 4-6 hours
- Theme customization: 2-3 hours
- Testing and link validation: 2-3 hours
- ReadTheDocs configuration: 1-2 hours
- Documentation and cleanup: 1-2 hours

**Total: 12-20 hours** (depending on complexity and customization)

---

## References

- [Sphinx Documentation](https://www.sphinx-doc.org/)
- [MyST Parser Documentation](https://myst-parser.readthedocs.io/)
- [Furo Theme Documentation](https://pradyunsg.me/furo/)
- [ReadTheDocs Documentation](https://docs.readthedocs.io/)
- [Ansible Collection Best Practices](https://docs.ansible.com/ansible/latest/dev_guide/developing_collections.html)
