from __future__ import annotations

import logging

from gacdi_manifest.download import cli


def test_cli_dispatches_gdc(tmp_path, monkeypatch):
    manifest = tmp_path / "gdc.tsv"
    manifest.write_text("id\tfilename\tmd5\tsize\tstate\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(cli, "download_gdc", lambda manifest, outdir: calls.append((manifest, outdir)) or 0)
    monkeypatch.setattr(cli, "download_pdc", lambda *args: (_ for _ in ()).throw(AssertionError("PDC called")))
    assert cli.main(["--manifest", str(manifest), "--outdir", str(tmp_path / "out")]) == 0
    assert calls == [(str(manifest), str(tmp_path / "out"))]


def test_cli_dispatches_pdc(tmp_path, monkeypatch):
    manifest = tmp_path / "pdc.csv"
    manifest.write_text("File ID,File Name,Md5sum,File Download Link\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(cli, "download_pdc", lambda manifest, outdir: calls.append((manifest, outdir)) or 0)
    monkeypatch.setattr(cli, "download_gdc", lambda *args: (_ for _ in ()).throw(AssertionError("GDC called")))
    assert cli.main(["--manifest", str(manifest), "--outdir", str(tmp_path / "out")]) == 0
    assert calls == [(str(manifest), str(tmp_path / "out"))]


def test_unknown_manifest_exits_two_without_backend(tmp_path, monkeypatch, caplog):
    manifest = tmp_path / "unknown.tsv"
    manifest.write_text("sample\tlabel\n", encoding="utf-8")
    monkeypatch.setattr(cli, "download_pdc", lambda *args: (_ for _ in ()).throw(AssertionError("PDC called")))
    monkeypatch.setattr(cli, "download_gdc", lambda *args: (_ for _ in ()).throw(AssertionError("GDC called")))
    with caplog.at_level(logging.ERROR):
        assert cli.main(["--manifest", str(manifest), "--outdir", str(tmp_path / "out")]) == 2
    assert "sample" in caplog.text
