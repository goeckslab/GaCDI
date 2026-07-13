import csv
import hashlib
import json

from gacdi.history import (
    DATASET_MAP_COLUMNS,
    TRANSFER_REPORT_COLUMNS,
    safe_filename,
    unique_path,
    write_dataset_map,
    write_galaxy_metadata,
    write_imported_metadata,
    write_summary,
    write_transfer_report,
)
from gacdi.contracts import SelectionMetadataRow, association_row_id
from gacdi.model import DownloadResult, FileEntry, ProducedDataset, RunSummary


def test_safe_filename():
    assert safe_filename("a b/c*.txt") == "a_b_c_.txt"
    assert safe_filename("   ") == "dataset"


def test_unique_path(tmp_path):
    p1 = unique_path(tmp_path, "x.txt")
    p1.write_text("1")
    p2 = unique_path(tmp_path, "x.txt")
    assert p1.name == "x.txt"
    assert p2.name == "x_1.txt"


def test_write_summary_rows(tmp_path):
    entry = FileEntry(file_id="ID1", filename="a.bam", md5="deadbeef", size=10, source="gdc")
    res = DownloadResult(entry, "ok", paths=[str(tmp_path / "a.bam")], bytes=10)
    summary = RunSummary("gdc", [res])
    out = tmp_path / "s.tsv"
    write_summary(out, summary)
    text = out.read_text().splitlines()
    assert text[0].split("\t")[0] == "database"
    assert "a.bam" in text[1]
    assert "ok" in text[1]


def test_write_summary_entry_without_paths(tmp_path):
    entry = FileEntry(file_id="ID1", filename="a.bam", source="gdc")
    res = DownloadResult(entry, "planned")
    out = tmp_path / "s.tsv"
    write_summary(out, RunSummary("gdc", [res]))
    assert "planned" in out.read_text()


def test_transfer_report_and_dataset_map_have_separate_cardinality(tmp_path):
    first = tmp_path / "sample_1.fastq.gz"
    second = tmp_path / "sample_2.fastq.gz"
    first.write_bytes(b"forward")
    second.write_bytes(b"reverse")
    entry = FileEntry(
        file_id="SRR1",
        filename="SRR1",
        size=100,
        source="sra",
        extra={
            "asset_kind": "run",
            "payload_profile": "reads_paired",
            "source_checksum_type": "md5",
            "source_checksum": "0" * 32,
        },
    )
    produced = [
        ProducedDataset(
            path=str(first),
            element_id="SRR1",
            role="forward",
            galaxy_ext="fastqsanger.gz",
            bytes=first.stat().st_size,
            checksum_type="sha256",
            checksum=hashlib.sha256(first.read_bytes()).hexdigest(),
            verification="calculated",
        ),
        ProducedDataset(
            path=str(second),
            element_id="SRR1",
            role="reverse",
            galaxy_ext="fastqsanger.gz",
            bytes=second.stat().st_size,
            checksum_type="sha256",
            checksum=hashlib.sha256(second.read_bytes()).hexdigest(),
            verification="calculated",
        ),
    ]
    summary = RunSummary(
        "sra",
        [
            DownloadResult(
                entry,
                "ok",
                paths=[str(first), str(second)],
                bytes=first.stat().st_size + second.stat().st_size,
                produced=produced,
                attempts=2,
            )
        ],
    )

    transfer = tmp_path / "transfer.tsv"
    dataset_map = tmp_path / "map.tsv"
    write_transfer_report(transfer, summary)
    write_dataset_map(dataset_map, summary)

    transfer_rows = list(csv.reader(transfer.open(), delimiter="\t"))
    map_rows = list(csv.reader(dataset_map.open(), delimiter="\t"))
    assert transfer_rows[0] == TRANSFER_REPORT_COLUMNS
    assert len(transfer_rows) == 2
    assert transfer_rows[1][1:6] == ["SRR1", "run", "reads_paired", "retrieved", "2"]
    assert map_rows[0] == DATASET_MAP_COLUMNS
    assert len(map_rows) == 3
    assert [row[4] for row in map_rows[1:]] == ["forward", "reverse"]
    assert [int(row[7]) for row in map_rows[1:]] == [len(b"forward"), len(b"reverse")]


def test_legacy_paths_get_independent_sha256_records(tmp_path):
    first = tmp_path / "one.dat"
    second = tmp_path / "two.dat"
    first.write_bytes(b"one")
    second.write_bytes(b"two-two")
    entry = FileEntry(file_id="A", filename="asset", source="x")
    result = DownloadResult(entry, "ok", paths=[str(first), str(second)], bytes=10)
    out = tmp_path / "map.tsv"
    write_dataset_map(out, RunSummary("x", [result]))
    rows = list(csv.DictReader(out.open(), delimiter="\t"))
    assert [row["actual_size"] for row in rows] == ["3", "7"]
    assert [row["actual_checksum"] for row in rows] == [
        hashlib.sha256(b"one").hexdigest(),
        hashlib.sha256(b"two-two").hexdigest(),
    ]
    assert all(row["actual_checksum_type"] == "sha256" for row in rows)


def test_galaxy_metadata_handles_multidot_and_duplicate_filenames(tmp_path):
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    left_dir.mkdir()
    right_dir.mkdir()
    left = left_dir / "calls.vcf.gz"
    right = right_dir / "calls.vcf.gz"
    left.write_bytes(b"left")
    right.write_bytes(b"right")
    entries = []
    for asset_id, path in (("A1", left), ("A2", right)):
        entry = FileEntry(file_id=asset_id, filename=path.name, source="gdc")
        dataset = ProducedDataset(
            path=str(path),
            element_id=asset_id,
            galaxy_ext="vcf_bgzip",
            dbkey="hg38",
            bytes=path.stat().st_size,
            checksum_type="sha256",
            checksum=hashlib.sha256(path.read_bytes()).hexdigest(),
            verification="calculated",
        )
        entries.append(DownloadResult(entry, "ok", paths=[str(path)], produced=[dataset]))

    output = tmp_path / "galaxy.json"
    write_galaxy_metadata(output, RunSummary("gdc", entries))
    values = json.loads(output.read_text())
    assert set(values) == {"downloaded"}
    datasets = values["downloaded"]["datasets"]
    assert [row["identifier_0"] for row in datasets] == ["A1", "A2"]
    assert [row["filename"] for row in datasets] == [str(left), str(right)]
    assert all(row["ext"] == "vcf_bgzip" for row in datasets)
    assert all(row["dbkey"] == "hg38" for row in datasets)
    assert all("name" not in row for row in datasets)


def test_imported_metadata_joins_associations_to_elements(tmp_path):
    row_id = association_row_id("gdc", "A1", "sample", "C1", "S1")
    association = SelectionMetadataRow(
        {
            "metadata_row_id": row_id,
            "source": "gdc",
            "asset_id": "A1",
            "relationship": "sample",
            "case_id": "C1",
            "sample_id": "S1",
            "project": "P1",
            "sample_type": "Tumor",
            "annotation_state": "not_requested",
        }
    )
    produced = tmp_path / "a.bam"
    produced.write_bytes(b"bam")
    entry = FileEntry(
        file_id="A1",
        filename="a.bam",
        source="gdc",
        extra={"selection_metadata": (association,)},
    )
    result = DownloadResult(
        entry,
        "ok",
        paths=[str(produced)],
        produced=[ProducedDataset(path=str(produced), element_id="A1", galaxy_ext="bam")],
    )
    output = tmp_path / "imported.tsv"
    write_imported_metadata(output, RunSummary("gdc", [result]))
    rows = list(csv.DictReader(output.open(), delimiter="\t"))
    assert rows[0]["metadata_row_id"] == row_id
    assert rows[0]["element_id"] == "A1"
    assert rows[0]["collection_output"] == "downloaded"
