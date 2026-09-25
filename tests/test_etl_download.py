"""Tests for the downloader, against a small local server that cuts transfers short, as ABS sometimes does."""
import hashlib
import io
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from etl.core import Ctx, EtlError


def make_zip(size=400_000) -> bytes:
    payload = hashlib.sha256(b"seed").digest() * (size // 32)  # not compressible enough to matter (it is stored anyway)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as z:
        z.writestr("data.bin", payload)
    return buffer.getvalue()


class Flaky(BaseHTTPRequestHandler):
    body = b""
    cut_first = 0  # cut this many transfers short
    cut_after = 100_000  # after this many bytes of each response
    supports_range = True
    requests_seen: list = []

    def do_GET(self):
        cls = type(self)
        cls.requests_seen.append(self.headers.get("Range"))
        start = 0
        rng = self.headers.get("Range")
        if rng and cls.supports_range:
            start = int(rng.split("=")[1].rstrip("-"))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(cls.body) - 1}/{len(cls.body)}")
        else:
            self.send_response(200)
        chunk = cls.body[start:]
        self.send_header("Content-Length", str(len(chunk)))
        self.send_header("Content-Type", "application/zip")
        self.end_headers()
        if cls.cut_first > 0:
            cls.cut_first -= 1
            self.wfile.write(chunk[:cls.cut_after])  # promise the whole file, send part of it, hang up
            self.wfile.flush()
            self.close_connection = True
            return
        self.wfile.write(chunk)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    Flaky.body, Flaky.cut_first, Flaky.supports_range, Flaky.requests_seen = make_zip(), 0, True, []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Flaky)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/file.zip"
    httpd.shutdown()


def test_a_clean_download_is_saved_with_its_checksum(server, tmp_path):
    ctx = Ctx(verbose=False)
    meta = ctx.fetch_to(server, tmp_path / "file.zip")
    assert (tmp_path / "file.zip").read_bytes() == Flaky.body
    assert meta["sha256"] == hashlib.sha256(Flaky.body).hexdigest()
    assert meta["bytes"] == len(Flaky.body)


def test_an_interrupted_download_resumes_where_it_stopped(server, tmp_path):
    Flaky.cut_first = 2  # the first two transfers are cut short
    ctx = Ctx(verbose=False)
    ctx.fetch_to(server, tmp_path / "file.zip")
    assert (tmp_path / "file.zip").read_bytes() == Flaky.body
    assert Flaky.requests_seen[0] is None  # the first request is for the whole file
    starts = [int(r.split("=")[1].rstrip("-")) for r in Flaky.requests_seen[1:3]]  # then it asks to continue
    assert all(r and r.startswith("bytes=") for r in Flaky.requests_seen[1:3])
    assert 0 < starts[0] < starts[1]  # from further on each time, never from the start again
    assert not (tmp_path / "file.zip.part").exists()


def test_a_server_that_ignores_range_requests_is_downloaded_again_from_the_start(server, tmp_path):
    Flaky.cut_first, Flaky.supports_range = 1, False
    ctx = Ctx(verbose=False)
    ctx.fetch_to(server, tmp_path / "file.zip")
    assert (tmp_path / "file.zip").read_bytes() == Flaky.body


def test_it_gives_up_after_repeated_attempts_that_get_no_further(server, tmp_path):
    Flaky.cut_first, Flaky.cut_after = 100, 0  # every transfer is cut before any data arrives
    ctx = Ctx(verbose=False)
    with pytest.raises(EtlError, match="kept failing"):
        ctx.fetch_to(server, tmp_path / "file.zip", stalls_allowed=2)
    assert not (tmp_path / "file.zip").exists()
    Flaky.cut_after = 100_000
