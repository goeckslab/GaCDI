"""Unit + contract round-trip tests for the shared foundation."""

from __future__ import annotations

import pytest

from gacdi_core.contracts import (
    ASSET_COLUMNS,
    CONTRACT_VERSION,
    SelectionAsset,
    association_row_id,
)
from gacdi_core.errors import GacdiError, InputError
from gacdi_core.net import build_session
from gacdi_core.validation import validate_assets


def _asset(asset_id: str) -> SelectionAsset:
    return SelectionAsset(
        source="gdc",
        asset_id=asset_id,
        asset_kind="file",
        download_method="gdc-client",
        drs_uri="",
        access_url="",
        access="open",
        asset_name=f"{asset_id}.bam",
        source_size=10,
        source_checksum_type="md5",
        source_checksum="a" * 32,
        file_format="BAM",
        payload_profile="raw_mixed",
        galaxy_ext_hint="bam",
        dbkey="",
    )


def test_contract_version_is_stable():
    assert CONTRACT_VERSION == "1.0"


def test_asset_as_row_roundtrips_all_columns():
    row = _asset("uuid1").as_row()
    assert tuple(row) == ASSET_COLUMNS


def test_association_row_id_is_deterministic():
    a = association_row_id("gdc", "uuid1", "asset")
    b = association_row_id("gdc", "uuid1", "asset")
    assert a == b and a.startswith("md_")


def test_validate_assets_accepts_a_single_source_bundle():
    validate_assets([_asset("uuid1"), _asset("uuid2")])


def test_validate_assets_rejects_out_of_order():
    with pytest.raises(InputError):
        validate_assets([_asset("uuid2"), _asset("uuid1")])


def test_error_hierarchy():
    assert issubclass(InputError, GacdiError)
    assert GacdiError.exit_code == 1
    assert InputError.exit_code == 2


def test_build_session_mounts_https_adapter():
    session = build_session()
    assert session.get_adapter("https://example.org") is not None
