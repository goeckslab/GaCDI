from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

from gacdi_manifest.download.gdc import download_gdc
from gacdi_manifest.errors import DownloadError


def _manifest(tmp_path, *, rows=True):
    manifest = tmp_path / "manifest.tsv"
    content = "id\tfilename\tmd5\tsize\tstate\n"
    if rows:
        content += "uuid\tfile.txt\td41d8cd98f00b204e9800998ecf8427e\t0\treleased\n"
    manifest.write_text(content, encoding="utf-8")
    return manifest


def test_gdc_argv_without_token(tmp_path, monkeypatch):
    captured = {}
    manifest = _manifest(tmp_path)

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert download_gdc(manifest, tmp_path / "out", environ={}) == 0
    assert captured["argv"][:2] == ["gdc-client", "download"]
    assert captured["argv"][2:6] == ["-m", str(manifest), "-d", str(tmp_path / "out")]
    assert "-t" not in captured["argv"]


def test_gdc_uses_short_temp_path_for_multiprocessing_sockets(tmp_path, monkeypatch):
    captured = {}
    manifest = _manifest(tmp_path)

    def fake_run(argv, **kwargs):
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(argv, 0, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    download_gdc(manifest, tmp_path / "out", environ={})
    assert captured["env"]["TMPDIR"] == "/tmp"
    assert captured["env"]["TMP"] == "/tmp"
    assert captured["env"]["TEMP"] == "/tmp"


def test_gdc_token_uses_mode_0600_fifo_and_never_argv(tmp_path, monkeypatch):
    captured = {}
    manifest = _manifest(tmp_path)

    def fake_run(argv, **kwargs):
        fifo = Path(argv[argv.index("-t") + 1])
        captured["mode"] = stat.S_IMODE(fifo.stat().st_mode)
        captured["is_fifo"] = stat.S_ISFIFO(fifo.stat().st_mode)
        captured["token"] = fifo.read_text(encoding="utf-8")
        captured["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    download_gdc(manifest, tmp_path / "out", environ={"GDC_AUTH_TOKEN": "top-secret"})
    assert captured["is_fifo"]
    assert captured["mode"] == 0o600
    assert captured["token"] == "top-secret"
    assert "top-secret" not in captured["argv"]
    assert not list((tmp_path / "out").glob(".gdc-token-*"))


def test_gdc_nonzero_surfaces_stderr(tmp_path, monkeypatch, capsys):
    manifest = _manifest(tmp_path)
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 7, stderr="remote GDC failure\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(DownloadError, match="status 7.*remote GDC failure"):
        download_gdc(manifest, tmp_path / "out", environ={})
    assert "remote GDC failure" in capsys.readouterr().err


def test_gdc_logs_are_removed(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path)
    log_dir = tmp_path / "out/uuid/logs"
    log_dir.mkdir(parents=True)
    (log_dir / "client.log").write_text("log", encoding="utf-8")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, stderr=""),
    )
    download_gdc(manifest, tmp_path / "out", environ={})
    assert not log_dir.exists()


def test_gdc_header_only_manifest_does_not_start_client(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path, rows=False)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("gdc-client started")),
    )
    assert download_gdc(manifest, tmp_path / "out", environ={}) == 0
