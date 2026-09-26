"""Tests for download_data.py, the downloader. A small local web server stands in for the internet, so there is no network.

Run inside the Docker image:
    docker compose run --rm --no-deps --entrypoint python etl -m pytest tests -q
"""
import hashlib
import io
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import download_data  # noqa: E402

BODY = bytes(range(256)) * 12_000  # about 3 MB


def make_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.txt", "x" * 100_000)
    return buf.getvalue()


ZIP = make_zip()


@pytest.fixture
def server(monkeypatch):
    """Serves BODY at /big and ZIP at /a.zip. The first request to each path is cut off part way through."""
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/forbidden":
                self.send_response(403)
                self.end_headers()
                return
            data = ZIP if self.path.endswith(".zip") else BODY
            seen[self.path] = seen.get(self.path, 0) + 1
            range_header = self.headers.get("Range")
            start = int(range_header.split("=")[1].rstrip("-")) if range_header else 0
            body = data[start:]
            self.send_response(206 if start else 200)
            if start:
                self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body[: len(body) * 4 // 10] if seen[self.path] == 1 else body)  # first request: 40% only
            self.wfile.flush()
            if seen[self.path] == 1:
                self.connection.close()

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setattr(download_data.time, "sleep", lambda seconds: None)  # do not wait between retries
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_a_cut_off_download_carries_on_and_ends_up_complete(server, tmp_path):
    download_data.download(f"{server}/big", tmp_path / "big.bin", {})
    assert hashlib.sha256((tmp_path / "big.bin").read_bytes()).hexdigest() == hashlib.sha256(BODY).hexdigest()
    assert not (tmp_path / "big.bin.part").exists()  # the .part file is gone once the download is whole


def test_a_zip_is_checked_to_be_complete(server, tmp_path):
    download_data.download(f"{server}/a.zip", tmp_path / "a.zip", {})
    assert zipfile.is_zipfile(tmp_path / "a.zip")


def test_a_403_stops_at_once_with_a_clear_message(server, tmp_path):
    with pytest.raises(RuntimeError, match="403"):
        download_data.download(f"{server}/forbidden", tmp_path / "x.bin", {})
