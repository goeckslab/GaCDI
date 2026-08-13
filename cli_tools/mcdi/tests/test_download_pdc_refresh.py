import base64
import json
import time

import pytest

from mcdi.download.sources.pdc import PDCSource, _cloudfront_policy_expiry, _is_stale
from mcdi.errors import InputError

STUDY = "PDC000001"


def _signed_url(expiry_epoch: int, resource: str = "https://x.cloudfront.net/f.raw") -> str:
    policy = json.dumps(
        {"Statement": [{"Resource": resource, "Condition": {"DateLessThan": {"AWS:EpochTime": expiry_epoch}}}]},
        separators=(",", ":"),
    ).encode()
    encoded = base64.b64encode(policy).decode().replace("+", "-").replace("=", "_").replace("/", "~")
    return f"{resource}?Policy={encoded}&Key-Pair-Id=X&Signature=Y"


def _manifest(tmp_path, url, filename="f.raw", md5="abc123", study=STUDY):
    path = tmp_path / "m.csv"
    path.write_text(
        "PDC Study ID,PDC Study Version,Data Category,File Type,File Name,File MD5sum,File Download Link\n"
        f"{study},1,Raw Mass Spectra,raw,{filename},{md5},{url}\n"
    )
    return path


class FakeRefresher:
    def __init__(self, studies: dict):
        self._studies = studies
        self.calls = []

    def fetch_study(self, study_id):
        self.calls.append(study_id)
        return self._studies[study_id]


def test_cloudfront_policy_expiry_roundtrip():
    url = _signed_url(1800000000)
    assert _cloudfront_policy_expiry(url) == 1800000000


def test_cloudfront_policy_expiry_none_for_malformed_url():
    assert _cloudfront_policy_expiry("https://example.com/f") is None
    assert _cloudfront_policy_expiry("https://example.com/f?Policy=not-base64!!") is None


def test_is_stale_true_for_expired_and_unparseable():
    assert _is_stale(_signed_url(1))
    assert _is_stale("https://example.com/f")


def test_is_stale_false_for_far_future_expiry():
    assert not _is_stale(_signed_url(int(time.time()) + 86400))


def test_fresh_url_skips_refresh(tmp_path):
    url = _signed_url(int(time.time()) + 86400)
    manifest = _manifest(tmp_path, url)

    class Unused:
        def fetch_study(self, study_id):
            raise AssertionError("should not be called")

    entries = PDCSource(refresher=Unused()).parse_manifest(manifest)
    assert entries[0].url == url


def test_stale_url_refreshed(tmp_path):
    stale_url = _signed_url(1)
    fresh_url = _signed_url(int(time.time()) + 86400)
    manifest = _manifest(tmp_path, stale_url, filename="f.raw", md5="abc123")
    refresher = FakeRefresher({STUDY: {"f.raw": {"md5sum": "abc123", "signedUrl": {"url": fresh_url}}}})

    entries = PDCSource(refresher=refresher).parse_manifest(manifest)

    assert entries[0].url == fresh_url
    assert refresher.calls == [STUDY]


def test_stale_url_missing_from_refresh_raises(tmp_path):
    manifest = _manifest(tmp_path, _signed_url(1), filename="f.raw")
    refresher = FakeRefresher({STUDY: {}})

    with pytest.raises(InputError, match="f.raw"):
        PDCSource(refresher=refresher).parse_manifest(manifest)


def test_stale_url_md5_mismatch_raises(tmp_path):
    manifest = _manifest(tmp_path, _signed_url(1), filename="f.raw", md5="abc123")
    refresher = FakeRefresher(
        {STUDY: {"f.raw": {"md5sum": "different", "signedUrl": {"url": _signed_url(int(time.time()) + 86400)}}}}
    )

    with pytest.raises(InputError, match="md5 mismatch"):
        PDCSource(refresher=refresher).parse_manifest(manifest)


def test_stale_url_no_manifest_md5_trusts_refresh(tmp_path):
    stale_url = _signed_url(1)
    fresh_url = _signed_url(int(time.time()) + 86400)
    manifest = _manifest(tmp_path, stale_url, filename="f.raw", md5="")
    refresher = FakeRefresher({STUDY: {"f.raw": {"md5sum": "fresh_md5", "signedUrl": {"url": fresh_url}}}})

    entries = PDCSource(refresher=refresher).parse_manifest(manifest)

    assert entries[0].url == fresh_url
    assert entries[0].md5 == "fresh_md5"


def test_multiple_studies_grouped_one_call_each(tmp_path):
    path = tmp_path / "m.csv"
    stale = _signed_url(1)
    fresh_a = _signed_url(int(time.time()) + 86400)
    fresh_b = _signed_url(int(time.time()) + 86400)
    path.write_text(
        "PDC Study ID,PDC Study Version,Data Category,File Type,File Name,File MD5sum,File Download Link\n"
        f"PDC000001,1,Raw Mass Spectra,raw,a.raw,md5a,{stale}\n"
        f"PDC000002,1,Raw Mass Spectra,raw,b.raw,md5b,{stale}\n"
    )
    refresher = FakeRefresher(
        {
            "PDC000001": {"a.raw": {"md5sum": "md5a", "signedUrl": {"url": fresh_a}}},
            "PDC000002": {"b.raw": {"md5sum": "md5b", "signedUrl": {"url": fresh_b}}},
        }
    )

    entries = PDCSource(refresher=refresher).parse_manifest(path)

    urls = {e.filename: e.url for e in entries}
    assert urls == {"a.raw": fresh_a, "b.raw": fresh_b}
    assert sorted(refresher.calls) == ["PDC000001", "PDC000002"]


def test_pagination_loops_until_short_page():
    from mcdi.download.sources.pdc import _PAGE_SIZE, PdcUrlRefresher

    class FakeSession:
        def __init__(self, pages):
            self.pages = pages
            self.calls = 0

        def post(self, url, json, timeout):
            offset = json["variables"]["offset"]
            page = self.pages[offset // _PAGE_SIZE]
            self.calls += 1
            return FakeResponse(page)

    class FakeResponse:
        def __init__(self, page):
            self._page = page
            self.status_code = 200

        def json(self):
            return {"data": {"filesPerStudy": self._page}}

    full_page = [{"file_name": f"f{i}.raw", "md5sum": "x", "signedUrl": {"url": "u"}} for i in range(_PAGE_SIZE)]
    last_page = [{"file_name": "last.raw", "md5sum": "x", "signedUrl": {"url": "u"}}]
    session = FakeSession([full_page, last_page])

    result = PdcUrlRefresher(session=session).fetch_study(STUDY)

    assert session.calls == 2
    assert len(result) == _PAGE_SIZE + 1
    assert "last.raw" in result
