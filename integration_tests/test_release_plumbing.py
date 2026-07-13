"""Release metadata shared by packages, Galaxy wrappers, and containers."""

from __future__ import annotations

import re
from pathlib import Path

from gacdi import __version__ as downloader_version
from gacdi_manifest import __version__ as builder_version

ROOT = Path(__file__).resolve().parents[1]


def _tool_version(path: Path) -> str:
    match = re.search(
        r'<token name="@TOOL_VERSION@">([^<]+)</token>', path.read_text()
    )
    assert match, f"missing @TOOL_VERSION@ in {path}"
    return match.group(1)


def test_package_and_galaxy_versions_stay_in_sync():
    assert downloader_version == builder_version
    macro_paths = [
        ROOT / "tools/macros.xml",
        ROOT / "tools/manifest_gdc/macros.xml",
        ROOT / "tools/manifest_idc/macros.xml",
        ROOT / "tools/manifest_pdc/macros.xml",
    ]
    assert {_tool_version(path) for path in macro_paths} == {downloader_version}


def test_downloader_child_images_default_to_the_release_base():
    expected = f"quay.io/goeckslab/gacdi-base:{downloader_version}"
    for source in ("cda", "gdc", "geo", "sra"):
        dockerfile = ROOT / f"containers/downloader/Dockerfile.{source}"
        assert f"ARG BASE_IMAGE={expected}" in dockerfile.read_text()
