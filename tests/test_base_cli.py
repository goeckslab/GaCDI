from pathlib import Path

import pytest

from gacdi.base import BaseImporter, RunConfig
from gacdi.cli import main
from gacdi.errors import AuthError, DependencyError, DownloadError, InputError
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
    assert [result.status for result in summary.results[2:]] == ["excluded_file_limit"] * 3


def test_run_records_byte_budget_exclusions(tmp_path):
    cfg = RunConfig(
        input_mode="accession",
        output_dir=str(tmp_path / "out"),
        summary=str(tmp_path / "s.tsv"),
        transfer_report=str(tmp_path / "transfer.tsv"),
        max_bytes=2,
    )
    summary = DummyImporter().run(cfg)
    assert [result.status for result in summary.results] == [
        "ok",
        "ok",
        "excluded_byte_limit",
        "excluded_byte_limit",
        "excluded_byte_limit",
    ]
    assert (tmp_path / "transfer.tsv").read_text().count("excluded_byte_limit") == 3


def test_retries_are_additional_attempts(tmp_path):
    class FlakyImporter(DummyImporter):
        attempts = 0

        def resolve(self, cfg, token):
            return [FileEntry(file_id="one", filename="one.txt", source="dummy")]

        def download(self, entry, dest_dir, cfg, token):
            self.attempts += 1
            if self.attempts < 3:
                raise DownloadError("transient")
            return DownloadResult(entry, "ok")

    importer = FlakyImporter()
    summary = importer.run(
        RunConfig(
            input_mode="accession",
            output_dir=str(tmp_path / "out"),
            summary=str(tmp_path / "s.tsv"),
            retries=2,
        )
    )
    assert importer.attempts == 3
    assert summary.results[0].attempts == 3


def test_nonretryable_dependency_failure_is_reported_per_asset(tmp_path):
    class MissingDependencyImporter(DummyImporter):
        def resolve(self, cfg, token):
            return [FileEntry(file_id="one", filename="one.txt", source="dummy")]

        def download(self, entry, dest_dir, cfg, token):
            raise DependencyError("required-client is unavailable")

    transfer = tmp_path / "transfer.tsv"
    summary = MissingDependencyImporter().run(
        RunConfig(
            input_mode="accession",
            output_dir=str(tmp_path / "out"),
            summary=str(tmp_path / "summary.tsv"),
            transfer_report=str(transfer),
        )
    )
    assert summary.results[0].status == "failed"
    assert summary.results[0].attempts == 1
    assert "required-client is unavailable" in transfer.read_text()


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
        "--set", "legacy_access=open",
        "--output-dir", str(tmp_path / "out"),
        "--summary", str(summ),
        "--dry-run",
    ])
    assert rc == 0
    assert "planned" in summ.read_text()


def test_cli_unknown_database():
    with pytest.raises(SystemExit):
        main(["nosuchdb"])


def test_version_string_includes_build(monkeypatch):
    import gacdi

    monkeypatch.setattr(gacdi, "BUILD", "deadbee")
    assert gacdi.version_string() == f"{gacdi.__version__}+deadbee"

    monkeypatch.setattr(gacdi, "BUILD", "")
    assert gacdi.version_string() == gacdi.__version__
