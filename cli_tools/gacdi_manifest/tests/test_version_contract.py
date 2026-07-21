"""Contract between the package version, the wrapper pins, and the published tags.

``containers.yml`` tags both GaCDI images with ``gacdi_manifest.__version__``,
and each wrapper resolves its ``<container>`` requirement through its own
``@TOOL_VERSION@`` token. Nothing in Galaxy or the workflow checks that these
agree, and the failure modes are quiet in both directions:

- a wrapper pinned *behind* the package silently orphans every tag that the
  other wrapper's changes cause CI to publish
- a wrapper pinned *ahead* of the package resolves to a tag that was never
  built, so jobs fail at container pull time rather than at merge

Both are caught here instead.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from gacdi_manifest import __version__

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = REPO_ROOT / "tools"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "containers.yml"

MACRO_FILES = sorted(TOOLS_DIR.glob("*/macros.xml"))


def _token(macros: Path, name: str) -> str | None:
    for token in ET.parse(macros).getroot().findall("token"):
        if token.get("name") == name:
            return (token.text or "").strip()
    return None


def _containers(macros: Path) -> list[str]:
    return [(c.text or "").strip() for c in ET.parse(macros).getroot().iter("container")]


def test_wrappers_were_found():
    assert MACRO_FILES, f"no macros.xml under {TOOLS_DIR}"


@pytest.mark.parametrize("macros", MACRO_FILES, ids=lambda p: p.parent.name)
def test_wrapper_tool_version_matches_package_version(macros):
    assert _token(macros, "@TOOL_VERSION@") == __version__, (
        f"{macros.parent.name} pins @TOOL_VERSION@ to {_token(macros, '@TOOL_VERSION@')!r} but the "
        f"package is {__version__!r}; containers.yml tags images with the package version, so this "
        f"wrapper would reference a tag that is orphaned or was never built"
    )


@pytest.mark.parametrize("macros", MACRO_FILES, ids=lambda p: p.parent.name)
def test_container_tags_resolve_through_the_version_token(macros):
    """A hardcoded tag would not be updated by a version bump."""
    for container in _containers(macros):
        assert container.startswith("quay.io/goeckslab/"), container
        assert container.endswith(":@TOOL_VERSION@"), (
            f"{macros.parent.name} hardcodes {container!r}; use :@TOOL_VERSION@ so the pin follows the package"
        )


@pytest.mark.parametrize("macros", MACRO_FILES, ids=lambda p: p.parent.name)
def test_every_referenced_image_is_built_by_the_workflow(macros):
    """Each wrapper's image must have a corresponding build in containers.yml."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    for container in _containers(macros):
        image = container.split("/")[-1].split(":")[0]
        assert re.search(rf"\b{re.escape(image)}:\$\{{\{{ steps\.version\.outputs\.version \}}\}}", workflow), (
            f"{macros.parent.name} requires {image!r}, but containers.yml never pushes that image "
            f"tagged with the package version"
        )


def test_workflow_derives_tags_from_the_package_version():
    """Guards the sed expression CI uses to read __version__."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "cli_tools/gacdi_manifest/gacdi_manifest/__init__.py" in workflow
    assert re.search(r"__version__ = \\?\"\(\.\*\)\\?\"", workflow), (
        "containers.yml no longer parses __version__ the way this package declares it"
    )
