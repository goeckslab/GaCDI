import pytest
import requests

from gacdi.base import RunConfig
from gacdi.errors import InputError
from gacdi.importers.geo import GEOImporter, suppl_dir_url


def test_suppl_dir_url_series():
    url = suppl_dir_url("GSE12345")
    assert "/geo/series/GSE12nnn/GSE12345/suppl/" in url


def test_suppl_dir_url_short():
    assert "/geo/series/GSEnnn/GSE123/suppl/" in suppl_dir_url("GSE123")


def test_suppl_dir_url_sample():
    assert "/geo/samples/GSMnnn/GSM1/suppl/" in suppl_dir_url("GSM1")


def test_suppl_dir_url_invalid():
    with pytest.raises(InputError):
        suppl_dir_url("XYZ1")


def test_resolve_lists_supplementary(requests_mock):
    url = suppl_dir_url("GSE12345")
    html = (
        '<a href="../">Parent</a>'
        '<a href="GSE12345_RAW.tar">GSE12345_RAW.tar</a>'
        '<a href="filelist.txt">filelist.txt</a>'
    )
    requests_mock.get(url, text=html)
    imp = GEOImporter(session=requests.Session())
    entries = imp.resolve(RunConfig(input_mode="accession", accessions="GSE12345"), None)
    names = {e.filename for e in entries}
    assert names == {"GSE12345_RAW.tar", "filelist.txt"}
    assert all(e.url.startswith(url) for e in entries)


def test_resolve_empty_dir_raises(requests_mock):
    url = suppl_dir_url("GSE12345")
    requests_mock.get(url, text='<a href="../">Parent</a>')
    imp = GEOImporter(session=requests.Session())
    with pytest.raises(InputError):
        imp.resolve(RunConfig(input_mode="accession", accessions="GSE12345"), None)


def test_download_streams(tmp_path, requests_mock):
    url = suppl_dir_url("GSE12345")
    requests_mock.get(url, text='<a href="a.txt">a.txt</a>')
    requests_mock.get(url + "a.txt", content=b"hello")
    imp = GEOImporter(session=requests.Session())
    cfg = RunConfig(input_mode="accession", accessions="GSE12345")
    entry = imp.resolve(cfg, None)[0]
    res = imp.download(entry, str(tmp_path), cfg, None)
    assert res.status == "ok"
    assert (tmp_path / "a.txt").read_bytes() == b"hello"
