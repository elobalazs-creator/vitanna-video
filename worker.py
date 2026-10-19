"""Render entry point. Requires a future VitAnna queue bridge; disabled by default."""
import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from renderer import render


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Átirányítás nem engedélyezett a média- és feladatkapcsolatnál.")


def log(event, **data):
    print(json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)


class Bridge:
    def __init__(self, url, token):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.fragment or parts.query:
            raise ValueError("A bridge címe HTTPS-cím legyen, lekérdezés és belépési adat nélkül.")
        if len(token) < 32 or any(c in token for c in "\r\n"):
            raise ValueError("Legalább 32 karakteres külön worker-token szükséges.")
        self.url = url
        self.origin = (parts.scheme, parts.hostname, parts.port or 443)
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect)

    def asset_url(self, value):
        if not isinstance(value, str):
            raise ValueError("Hibás média-URL.")
        parts = urllib.parse.urlsplit(value)
        if (parts.scheme, parts.hostname, parts.port or 443) != self.origin or parts.username or parts.password or parts.fragment:
            raise ValueError("A média csak a konfigurált VitAnna HTTPS-eredetről tölthető le.")
        return value

    def json_response(self, response):
        raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("Túl nagy szerverválasz.")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Hibás JSON szerverválasz.")
        return result

    def post(self, payload):
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode(), headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json", "Accept": "application/json"}, method="POST")
        with self.opener.open(request, timeout=60) as response:
            return self.json_response(response)

    def download(self, spec, target, limit):
        if not isinstance(spec, dict) or not re.fullmatch(r"[0-9a-f]{64}", spec.get("sha256", "")):
            raise ValueError("Minden távoli médiához SHA-256 ellenőrzőösszeg szükséges.")
        request = urllib.request.Request(self.asset_url(spec.get("url")), headers={"Authorization": "Bearer " + self.token}, method="GET")
        digest, total = hashlib.sha256(), 0
        with self.opener.open(request, timeout=60) as response, target.open("xb") as out:
            length = response.headers.get("Content-Length")
            if length and int(length) > limit:
                raise ValueError("Túl nagy letöltés.")
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ValueError("Túl nagy letöltés.")
                out.write(chunk)
                digest.update(chunk)
        if total == 0 or digest.hexdigest() != spec["sha256"]:
            raise ValueError("A letöltött fájl hibás vagy nem a várt változat.")
        return {"path": target.name, "sha256": digest.hexdigest()}

    def complete(self, job, path, report):
        query = urllib.parse.urlencode({"action": "complete", "job_id": job["job_id"], "revision": job["revision"]})
        headers = {"Authorization": "Bearer " + self.token, "X-Vitanna-Lease": job["lease_token"], "X-Content-SHA256": report["sha256"], "Content-Type": "video/mp4", "Content-Length": str(path.stat().st_size), "Accept": "application/json"}
        # File-like body streams the upload, rather than loading the video into RAM.
        with path.open("rb") as body:
            request = urllib.request.Request(self.url + "?" + query, data=body, headers=headers, method="POST")
            with self.opener.open(request, timeout=300) as response:
                result = self.json_response(response)
        if result.get("ok") is not True or result.get("job_id") != job["job_id"] or result.get("sha256") != report["sha256"] or result.get("status") != "ready":
            raise ValueError("A szerver nem igazolta vissza a teljes videó átvételét.")


def run_once(client):
    response = client.post({"action": "claim", "worker_id": str(uuid.uuid4()), "lease_seconds": 7200})
    if "job" not in response:
        raise ValueError("Hiányzik a job mező a szerverválaszból.")
    job = response["job"]
    if job is None:
        log("idle")
        return
    if not isinstance(job, dict) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", job.get("job_id", "")):
        raise ValueError("Hibás feladatazonosító.")
    if not isinstance(job.get("revision"), int) or job["revision"] < 1 or not re.fullmatch(r"[A-Za-z0-9_-]{32,160}", job.get("lease_token", "")):
        raise ValueError("Hibás feladatverzió vagy foglalási token.")
    try:
        manifest = job.get("manifest")
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
            raise ValueError("Hibás feladatleíró.")
        if manifest.get("skip_video") is True:
            skipped = client.post({"action": "skipped", "job_id": job["job_id"], "revision": job["revision"], "lease_token": job["lease_token"]})
            if skipped.get("ok") is not True:
                raise ValueError("A kihagyás visszaigazolása hiányzik.")
            log("skipped", job_id=job["job_id"])
            return
        # Explicit allow-list: remote fields cannot supply local paths or output filenames.
        local = {key: manifest[key] for key in ("schema_version", "title", "require_captions", "video", "captions") if key in manifest}
        with tempfile.TemporaryDirectory(prefix="vitanna-worker-") as temp:
            root = Path(temp)
            local["audio"] = client.download(manifest.get("audio"), root / "audio.bin", 100 * 1024 * 1024)
            images = manifest.get("images")
            if not isinstance(images, list) or not 1 <= len(images) <= 12:
                raise ValueError("1–12 kép szükséges.")
            local["images"] = [client.download(spec, root / f"image-{i:02}.bin", 20 * 1024 * 1024) for i, spec in enumerate(images)]
            for key, limit in (("srt", 2 * 1024 * 1024), ("elevenlabs_alignment", 4 * 1024 * 1024)):
                if key in manifest:
                    local[key] = client.download(manifest[key], root / (key + ".bin"), limit)
            manifest_path = root / "job.json"
            manifest_path.write_text(json.dumps(local, ensure_ascii=False), encoding="utf-8")
            log("render_started", job_id=job["job_id"])
            output = root / "video.mp4"
            report = render(manifest_path, output)
            client.complete(job, output, report)
            log("ready", job_id=job["job_id"], duration_seconds=report["duration_seconds"], processing_seconds=report["processing_seconds"], bytes=report["bytes"])
    except Exception as exc:
        # The future bridge must ignore stale failures after a committed completion.
        try:
            client.post({"action": "failed", "job_id": job["job_id"], "revision": job["revision"], "lease_token": job["lease_token"], "error_code": type(exc).__name__})
        except Exception:
            pass
        raise


def main():
    mode = os.environ.get("RUN_MODE", "disabled")
    if mode == "disabled":
        log("disabled", message="Előkészítő mód; nincs hálózati hívás vagy videókészítés.")
        return
    if mode == "check":
        for name in ("ffmpeg", "ffprobe", "fc-match"):
            if not shutil.which(name):
                raise RuntimeError("Hiányzó rendszerprogram: " + name)
        log("check_ok")
        return
    if mode != "queue":
        raise ValueError("RUN_MODE: disabled, check vagy queue lehet.")
    run_once(Bridge(os.environ.get("VITANNA_BRIDGE_URL", ""), os.environ.get("VITANNA_WORKER_TOKEN", "")))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Do not include URLs, tokens, article text or remote response bodies in logs.
        log("failed", error_type=type(exc).__name__)
        raise SystemExit(1)
