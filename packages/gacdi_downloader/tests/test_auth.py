import stat

import pytest

from gacdi.auth import TokenFile
from gacdi.errors import AuthError


def test_token_file_secure(tmp_path):
    src = tmp_path / "tok.txt"
    src.write_text("SECRET-TOKEN\n")
    with TokenFile(src) as tf:
        p = tf.path
        assert p.exists()
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
        assert p.read_text() == "SECRET-TOKEN"
        assert str(tf) == str(p)
    assert not p.exists()


def test_token_missing(tmp_path):
    with pytest.raises(AuthError):
        TokenFile(tmp_path / "nope.txt")


def test_token_empty(tmp_path):
    src = tmp_path / "empty.txt"
    src.write_text("   \n")
    with pytest.raises(AuthError):
        TokenFile(src)
