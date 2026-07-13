import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

from gacdi.base import RunConfig
from gacdi.importers.gdc import GDCImporter


def _fixture_query(tmp_path: Path) -> Path:
    query = tmp_path / "query.json"
    query.write_text(json.dumps({"filters": {"fixture": True}, "size": 10}))
    return query


def _fixture_response(request, context):
    return {
        "data": {
            "hits": [
                {"file_id": "A1", "file_name": "sample.vcf.gz", "file_size": "7"},
                {"file_id": "FAIL", "file_name": "failed.bam", "file_size": "7"},
            ],
            "pagination": {"total": 2},
        }
    }


def test_planemo_tool_declares_typed_profile_outputs():
    root = ET.parse(Path(__file__).parents[1] / "tools/gdc/gacdi_gdc.xml").getroot()
    outputs = root.find("outputs")
    collections = {node.attrib["name"]: node.attrib["type"] for node in outputs if node.tag == "collection"}
    assert collections["downloaded_bam"] == "list"
    assert collections["downloaded_vcf"] == "list"
    assert collections["downloaded_paired"] == "list:paired"


def test_offline_fake_gdc_client_strict_and_best_effort_retry(
    tmp_path, requests_mock, monkeypatch
):
    endpoint = "https://fixture.invalid/gdc/files"
    requests_mock.post(endpoint, json=_fixture_response)
    fake_client = Path(__file__).parents[1] / "tools/gdc/test-data/gdc-client"
    monkeypatch.setenv("PATH", f"{fake_client.parent}{os.pathsep}{os.environ['PATH']}")

    strict = GDCImporter().run(
        RunConfig(
            input_mode="query",
            query_json=str(_fixture_query(tmp_path)),
            output_dir=str(tmp_path / "strict-downloads"),
            summary=str(tmp_path / "strict-summary.tsv"),
            options={"gdc_files_endpoint": endpoint},
            retries=1,
        )
    )
    assert [result.status for result in strict.results] == ["ok", "failed"], [
        result.message for result in strict.results
    ]
    assert strict.results[1].attempts == 2
    assert (tmp_path / "strict-downloads/sample.vcf.gz").read_bytes() == b"payload"

    best_effort = GDCImporter().run(
        RunConfig(
            input_mode="query",
            query_json=str(_fixture_query(tmp_path)),
            output_dir=str(tmp_path / "best-effort-downloads"),
            summary=str(tmp_path / "best-effort-summary.tsv"),
            transfer_report=str(tmp_path / "best-effort-transfer.tsv"),
            options={"gdc_files_endpoint": endpoint},
            retries=2,
            continue_on_error=True,
        )
    )
    assert best_effort.results[1].status == "failed"
    assert best_effort.results[1].attempts == 3
    assert "failed" in (tmp_path / "best-effort-transfer.tsv").read_text()
