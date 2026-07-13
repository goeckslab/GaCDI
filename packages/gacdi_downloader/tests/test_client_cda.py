"""Phase 5: isolated tests for the CDA SDK adapter."""

from __future__ import annotations

import sys
import types

import pytest

from gacdi.clients.cda import CDASdkAdapter
from gacdi.errors import DependencyError


def test_adapter_missing_cdapython_raises_dependency_error(monkeypatch):
    # Ensure the optional SDK is not importable.
    monkeypatch.setitem(sys.modules, "cdapython", None)
    with pytest.raises(DependencyError):
        CDASdkAdapter().fetch_rows(table="file")


def test_adapter_normalises_list_result(monkeypatch):
    fake = types.ModuleType("cdapython")
    fake.fetch_rows = lambda **kw: [{"file_id": "F1"}]
    monkeypatch.setitem(sys.modules, "cdapython", fake)
    assert CDASdkAdapter().fetch_rows(table="file") == [{"file_id": "F1"}]


def test_adapter_normalises_dataframe_like_result(monkeypatch):
    class _DF:
        def to_dict(self, orient):
            assert orient == "records"
            return [{"file_id": "F2"}]

    fake = types.ModuleType("cdapython")
    fake.fetch_rows = lambda **kw: _DF()
    monkeypatch.setitem(sys.modules, "cdapython", fake)
    assert CDASdkAdapter().fetch_rows(table="file") == [{"file_id": "F2"}]
