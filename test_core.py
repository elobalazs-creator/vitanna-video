import json
import hashlib
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from captions import from_alignment, parse_srt, validate_captions
from renderer import asset, render
from worker import Bridge, main, run_once


class CoreTests(unittest.TestCase):
    def test_disabled_never_connects(self):
        with patch.dict("os.environ", {"RUN_MODE": "disabled"}), patch("worker.Bridge", side_effect=AssertionError("network")):
            main()

    def test_skip_needs_no_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "job.json"
            path.write_text(json.dumps({"schema_version": 1, "skip_video": True}))
            output = Path(temp) / "out.mp4"
            self.assertEqual(render(path, output)["status"], "skipped")
            self.assertFalse(output.exists())

    def test_asset_cannot_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            with self.assertRaises(ValueError):
                asset(root, {"path": "../private.txt"}, 100)

    def test_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "file.txt").write_text("test")
            with self.assertRaises(ValueError):
                asset(root, {"path": "file.txt", "sha256": "0" * 64}, 100)

    def test_srt_accented_and_overlap(self):
        items = parse_srt("1\n00:00:00,100 --> 00:00:02,000\nŐrizd a belső békéd.\n")
        self.assertEqual(validate_captions(items, 3)[0]["text"], "Őrizd a belső békéd.")
        with self.assertRaises(ValueError):
            validate_captions(items * 2, 3)

    def test_alignment_keeps_real_times(self):
        text = "Ősz van."
        data = {"alignment": {"characters": list(text), "character_start_times_seconds": [i/10 for i in range(len(text))], "character_end_times_seconds": [(i+1)/10 for i in range(len(text))]}}
        items = from_alignment(data)
        self.assertEqual(items[0], {"start": 0, "end": 0.8, "text": text})

    def test_nonfinite_times_rejected(self):
        with self.assertRaises(ValueError):
            validate_captions([{"start": 0, "end": float("nan"), "text": "Próba"}], 5)

    def test_bridge_rejects_cross_origin(self):
        client = Bridge("https://vitanna.example/bridge.php", "x" * 40)
        with self.assertRaises(ValueError):
            client.asset_url("https://other.example/audio.mp3")
        with self.assertRaises(ValueError):
            client.asset_url("http://vitanna.example/audio.mp3")

    def test_idle_never_renders(self):
        class Fake:
            def post(self, payload):
                return {"job": None}
        with patch("worker.render", side_effect=AssertionError("unexpected render")):
            run_once(Fake())

    def test_missing_audio_reports_failure(self):
        calls = []
        class Fake:
            def post(self, payload):
                calls.append(payload)
                if payload["action"] == "claim":
                    return {"job": {"job_id": "test-1", "revision": 1, "lease_token": "a" * 40, "manifest": {"schema_version": 1, "images": []}}}
                return {"ok": True}
            def download(self, spec, target, limit):
                raise ValueError("audio not ready")
        with self.assertRaises(ValueError):
            run_once(Fake())
        self.assertEqual(calls[-1]["action"], "failed")

    def test_worker_completion_requires_ack(self):
        calls = []
        class Fake:
            def post(self, payload):
                calls.append(payload)
                if payload["action"] == "claim":
                    return {"job": {"job_id": "test-2", "revision": 1, "lease_token": "a" * 40, "manifest": {"schema_version": 1, "audio": {}, "images": [{}], "captions": []}}}
                return {"ok": True}
            def download(self, spec, target, limit):
                target.write_bytes(b"media")
                return {"path": target.name}
            def complete(self, job, output, report):
                raise ValueError("server did not acknowledge")
        with patch("worker.render", return_value={"status": "ready"}), self.assertRaises(ValueError):
            run_once(Fake())
        self.assertEqual(calls[-1]["action"], "failed")

    def test_streamed_upload_bytes_and_ack(self):
        seen = {}
        payload = b"test-video-bytes" * 5000
        checksum = hashlib.sha256(payload).hexdigest()
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                seen["body"] = self.rfile.read(int(self.headers["Content-Length"]))
                seen["authorization"] = self.headers.get("Authorization")
                seen["lease"] = self.headers.get("X-Vitanna-Lease")
                response = json.dumps({"ok": True, "job_id": "stream-test", "status": "ready", "sha256": checksum}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
            def log_message(self, *args):
                pass
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        # Test-only local transport. Production Bridge.__init__ still requires HTTPS.
        client = object.__new__(Bridge)
        client.url = f"http://127.0.0.1:{server.server_port}/bridge"
        client.token = "x" * 40
        client.opener = urllib.request.build_opener()
        try:
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "video.mp4"
                path.write_bytes(payload)
                client.complete({"job_id": "stream-test", "revision": 1, "lease_token": "y" * 40}, path, {"sha256": checksum})
            thread.join(timeout=3)
            self.assertEqual(seen["body"], payload)
            self.assertEqual(seen["authorization"], "Bearer " + "x" * 40)
            self.assertEqual(seen["lease"], "y" * 40)
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
