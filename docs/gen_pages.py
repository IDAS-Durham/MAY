"""Generate API reference stub pages for may/ under may/ in the nav.

For every .py file in ../may (skipping __init__.py and packages without
__init__.py, which griffe cannot render), write a virtual
docs/may/<path>.md page containing an mkdocstrings directive.
"""

from pathlib import Path

import mkdocs_gen_files

MAY_ROOT = Path(__file__).parent.parent / "may"

for path in sorted(MAY_ROOT.rglob("*.py")):
    if path.name == "__init__.py":
        continue

    if not (path.parent / "__init__.py").exists():
        continue

    relative_path = path.relative_to(MAY_ROOT.parent)
    doc_path = relative_path.with_suffix(".md")

    module_path = ".".join(relative_path.with_suffix("").parts)
    title = path.stem.replace("_", " ").capitalize()

    with mkdocs_gen_files.open(doc_path, "w") as documentation_file:
        documentation_file.write(
            f"# {title}\n\n::: {module_path}\n    options:\n      docstring_style: google\n"
        )
