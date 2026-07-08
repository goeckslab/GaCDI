from pathlib import Path

import pytest

from gacdi.base import BaseImporter, RunConfig
from gacdi.cli import main
from gacdi.errors import AuthError, InputError
from gacdi.model import DownloadResult, FileEntry


class DummyImporter(BaseImporter):
    name = "dummy"
    supported_modes = ("accession",)

    def resolve(self, cfg, token):
        return [FileEntry(file_id=str(i), filename=f"f{i}.txt", source="dummy") for i in range(5)]

    def download(self, entry, dest_dir, cfg, token):
        p = Path(dest_dir) / entry.filename
        p.write_text("x")
        return DownloadResult(entry, "ok", paths=[str(p)], bytes=1)


def test_run_enforces_max_files(tmp_path):
    cfg = RunConfig(
        input_mode="accession",
        output_dir=str(tmp_path / "out"),
        summary=str(tmp_path / "s.tsv"),
        max_files=2,
    )
    summary = DummyImporter().run(cfg)
    assert len(summary.ok) == 2


def test_run_dry_run_downloads_nothing(tmp_path):
    cfg = RunConfig(
        input_mode="accession",
        output_dir=str(tmp_path / "out"),
        summary=str(tmp_path / "s.tsv"),
        dry_run=True,
    )
    summary = DummyImporter().run(cfg)
    assert all(r.status == "planned" for r in summary.results)
    assert not any((tmp_path / "out").glob("*"))


def test_run_rejects_unsupported_mode(tmp_path):
    cfg = RunConfig(input_mode="manifest", summary=str(tmp_path / "s.tsv"))
    with pytest.raises(InputError):
        DummyImporter().run(cfg)


def test_run_rejects_token_when_unsupported(tmp_path):
    tok = tmp_path / "t.txt"
    tok.write_text("x")
    cfg = RunConfig(input_mode="accession", token=str(tok), summary=str(tmp_path / "s.tsv"))
    with pytest.raises(AuthError):
        DummyImporter().run(cfg)


def test_cli_gdc_dry_run(tmp_path):
    man = tmp_path / "m.txt"
    man.write_text("id\tfilename\tmd5\tsize\tstate\nID1\ta.bam\tx\t10\treleased\n")
    summ = tmp_path / "s.tsv"
    rc = main([
        "gdc",
        "--input-mode", "manifest",
        "--manifest", str(man),
        "--output-dir", str(tmp_path / "out"),
        "--summary", str(summ),
        "--dry-run",
    ])
    assert rc == 0
    assert "planned" in summ.read_text()


def test_cli_unknown_database():
    with pytest.raises(SystemExit):
        main(["nosuchdb"])
