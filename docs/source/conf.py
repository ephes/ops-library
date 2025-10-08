# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

from pathlib import Path
import yaml

# -- Read version from galaxy.yml ---------------------------------------------

galaxy_yml_path = Path(__file__).parent.parent.parent / "galaxy.yml"
with open(galaxy_yml_path) as f:
    galaxy_data = yaml.safe_load(f)

# -- Project information -------------------------------------------------------

project = "ops-library"
author = galaxy_data.get("authors", ["Jochen Wersdörfer"])[0]
version = galaxy_data.get("version", "0.1.0")
release = version
copyright = f"2025, {author}"

# -- General configuration -----------------------------------------------------

extensions = [
    'myst_parser',                     # MyST Markdown support
    'sphinx.ext.autosectionlabel',     # Auto-generate section labels
    'sphinx.ext.intersphinx',          # Link to other projects
    'sphinx_copybutton',               # Copy button for code blocks
]

# Prevent duplicate label warnings when multiple role READMEs have same headings
# (e.g., "Requirements", "Variables", "Examples" appear in every role)
autosectionlabel_prefix_document = True  # Namespace labels by document path
autosectionlabel_maxdepth = 3            # Only auto-label up to H3

# MyST configuration
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

templates_path = ['_templates']
exclude_patterns = []

# -- Options for HTML output ---------------------------------------------------

html_theme = 'furo'
html_theme_options = {
    # "Edit on GitHub" link configuration for Furo theme
    "source_repository": "https://github.com/ephes/ops-library",
    "source_branch": "main",
    "source_directory": "docs/source/",
}

html_static_path = ['_static']
html_title = f"{project} {version}"

# -- Options for intersphinx extension -----------------------------------------

intersphinx_mapping = {
    'ansible': ('https://docs.ansible.com/ansible/latest/', None),
    'python': ('https://docs.python.org/3', None),
}
