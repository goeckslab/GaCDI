from pathlib import Path

import pytest
import requests

from gacdi.base import RunConfig
from gacdi.errors import InputError
from gacdi.importers.xena import XenaImporter, download_candidates


def test_download_candidates_plain_and_gz():
    assert download_candidates("https://h", "A") == [
        "https://h/download/A",
        "https://h/download/A.gz",
    ]
    assert download_candidates("https://h/", "A")[0] == "https://h/download/A"


def test_download_candidates_full_url():
    assert download_candidates("h", "https://x/y.gz") == ["https://x/y.gz"]
    assert download_candidates("h", "https://x/y") == ["https://x/y", "https://x/y.gz"]


def test_resolve_accession_with_hub():
    imp = XenaImporter()
    cfg = RunConfig(input_mode="accession", accessions="TCGA/HiSeqV2", options={"hub": "https://h"})
    entries = imp.resolve(cfg, None)
    assert entries[0].filename == "HiSeqV2"
    assert entries[0].extra["candidates"][0] == "https://h/download/TCGA/HiSeqV2"


def test_resolve_query_mode(tmp_path):
    q = tmp_path / "q.json"
    q.write_text('{"hub": "https://h", "datasets": ["A", "B"]}')
    entries = XenaImporter().resolve(RunConfig(input_mode="query", query_json=str(q)), None)
    assert [e.file_id for e in entries] == ["A", "B"]


def test_resolve_requires_hub():
    with pytest.raises(InputError):
        XenaImporter().resolve(RunConfig(input_mode="accession", accessions="A", options={}), None)


def test_download_gz_fallback(tmp_path, requests_mock):
    imp = XenaImporter(session=requests.Session())
    entry = imp.resolve(
        RunConfig(input_mode="accession", accessions="DS", options={"hub": "https://h"}), None
    )[0]
    requests_mock.get("https://h/download/DS", status_code=404)
    requests_mock.get("https://h/download/DS.gz", content=b"matrix")
    res = imp.download(entry, str(tmp_path), RunConfig(), None)
    assert res.status == "ok"
    assert Path(res.paths[0]).name == "DS.gz"
    assert (tmp_path / "DS.gz").read_bytes() == b"matrix"
