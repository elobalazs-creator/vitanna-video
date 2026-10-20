"""Render entry point for the VitAnna queue bridge; disabled by default."""
from contextlib import contextmanager
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

from renderer import render, normalize_mp3, AUDIO_PROFILE

WORKER_VERSION = "2026-10-20-loudness-1"


@contextmanager
def phase(name):
    """Record only fixed local step names, never request/response contents."""
    log("step", stage=name)
    try:
        yield
    except Exception as exc:
        if not hasattr(exc, "vitanna_stage"):
            exc.vitanna_stage = name
        raise


def failure_details(exc):
    details = {"error_type": type(exc).__name__,
               "stage": getattr(exc, "vitanna_stage", "validation"),
               "worker_version": WORKER_VERSION}
    if isinstance(exc, urllib.error.HTTPError):
        details["http_status"] = exc.code
        hints = {
            400: "A szerver hibásnak találta a kérést.",
            401: "A szerver nem fogadta el a hitelesítést. A kulcs egyezését és az Authorization fejléc továbbítását kell ellenőrizni.",
            403: "A szerver vagy a tárhely megtagadta a hozzáférést.",
            404: "A kért végpont vagy médiafájl nem található.",
            405: "A szerver nem engedélyezi ezt a kérési módot.",
            409: "A feladat állapota vagy foglalása már nem érvényes.",
            413: "A szerver túl nagynak találta a feltöltést.",
            422: "A szerver hibásnak találta a feltöltött videót.",
            429: "A szerver átmenetileg korlátozza a kéréseket.",
            500: "A weboldalon belső szerverhiba történt.",
            502: "A kiszolgáló köztes kapcsolati hibát jelzett.",
            503: "A kiszolgáló átmenetileg nem elérhető vagy foglalt.",
            504: "A kiszolgáló válaszideje lejárt.",
        }
        details["message"] = hints.get(exc.code, "A szerver HTTP-hibát jelzett.")
        if exc.headers:
            if exc.headers.get("X-Vitanna-Bridge-Version") == "2026-10-19-auth-1":
                details["bridge_version"] = "2026-10-19-auth-1"
            reason = exc.headers.get("X-Vitanna-Auth-Error", "")
            auth_hints = {
                "missing": "A hitelesítési fejlécek nem érkeztek meg a PHP-hoz.",
                "mismatch": "A PHP-hoz megérkezett hitelesítési adat eltér a weboldalon tárolt kulcstól.",
                "not_configured": "A weboldalon nem található beállított Render-kapcsolati kulcs.",
            }
            if exc.code == 401 and reason in auth_hints:
                details["auth_error"] = reason
                details["message"] = auth_hints[reason]
    elif isinstance(exc, json.JSONDecodeError):
        details["message"] = "A szerver válasza nem érvényes JSON."
    elif isinstance(exc, urllib.error.URLError):
        details["message"] = "A hálózati vagy TLS-kapcsolat nem jött létre."
    else:
        # Exact allow-list of our own messages. Never print arbitrary exception
        # text: it may contain URLs, tokens, server bodies or article contents.
        safe_messages = {
            "Átirányítás nem engedélyezett a média- és feladatkapcsolatnál.",
            "A bridge címe HTTPS-cím legyen, lekérdezés és belépési adat nélkül.",
            "Legalább 32 karakteres külön worker-token szükséges.",
            "RUN_MODE: disabled, check vagy queue lehet.",
            "Hiányzik a job mező a szerverválaszból.",
            "A média csak a konfigurált VitAnna HTTPS-eredetről tölthető le.",
            "A letöltött fájl hibás vagy nem a várt változat.",
            "A szerver nem igazolta vissza a teljes videó átvételét.",
        }
        if type(exc) is ValueError and str(exc) in safe_messages:
            details["message"] = str(exc)
    return details


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

    def auth_headers(self):
        # The same secret is sent only to the validated HTTPS origin. The
        # dedicated header supports hosts that strip Authorization in CGI.
        return {"Authorization": "Bearer " + self.token,
                "X-Vitanna-Worker-Token": self.token}

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
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode(), headers={**self.auth_headers(), "Content-Type": "application/json", "Accept": "application/json"}, method="POST")
        with self.opener.open(request, timeout=60) as response:
            return self.json_response(response)

    def download(self, spec, target, limit, lease=None):
        if not isinstance(spec, dict) or not re.fullmatch(r"[0-9a-f]{64}", spec.get("sha256", "")):
            raise ValueError("Minden távoli médiához SHA-256 ellenőrzőösszeg szükséges.")
        headers = self.auth_headers()
        if lease is not None:
            headers["X-Vitanna-Lease"] = lease
        request = urllib.request.Request(self.asset_url(spec.get("url")), headers=headers, method="GET")
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
        headers = {**self.auth_headers(), "X-Vitanna-Lease": job["lease_token"], "X-Content-SHA256": report["sha256"], "Content-Type": "video/mp4", "Content-Length": str(path.stat().st_size), "Accept": "application/json"}
        # File-like body streams the upload, rather than loading the video into RAM.
        with path.open("rb") as body:
            request = urllib.request.Request(self.url + "?" + query, data=body, headers=headers, method="POST")
            with self.opener.open(request, timeout=300) as response:
                result = self.json_response(response)
        if result.get("ok") is not True or result.get("job_id") != job["job_id"] or result.get("sha256") != report["sha256"] or result.get("status") != "ready":
            raise ValueError("A szerver nem igazolta vissza a teljes videó átvételét.")

    def complete_audio(self, job, path, report):
        query = urllib.parse.urlencode({"action": "complete", "job_id": job["job_id"]})
        headers = {**self.auth_headers(), "X-Vitanna-Lease": job["lease_token"],
            "X-Content-SHA256": report["sha256"], "Content-Type": "audio/mpeg",
            "Content-Length": str(path.stat().st_size), "Accept": "application/json",
            "X-Vitanna-Audio-Profile": AUDIO_PROFILE,
            "X-Vitanna-Audio-Lufs": str(report["integrated_lufs"]),
            "X-Vitanna-Audio-Peak": str(report["true_peak_dbtp"])}
        with path.open("rb") as body:
            request = urllib.request.Request(self.url + "?" + query, data=body,
                                             headers=headers, method="POST")
            with self.opener.open(request, timeout=180) as response:
                result = self.json_response(response)
        if result.get("ok") is not True or result.get("job_id") != job["job_id"] or result.get("sha256") != report["sha256"] or result.get("status") != "ready":
            raise ValueError("A szerver nem igazolta vissza a javított MP3 átvételét.")


def normalize_daily(client):
    """One ready MP3 per tick, independently of video eligibility. No TTS calls."""
    job = None
    try:
        with phase("audio_claim"):
            response = client.post({"action": "claim", "profile": AUDIO_PROFILE})
            if "job" not in response:
                raise ValueError("Hiányzik a job mező a szerverválaszból.")
            job = response["job"]
        if job is None:
            return
        if not isinstance(job, dict) or not re.fullmatch(r"[0-9a-f]{64}", job.get("job_id", "")) or not re.fullmatch(r"[0-9a-f]{64}", job.get("lease_token", "")):
            job = None
            raise ValueError("Hibás hangjavítási feladat.")
        with tempfile.TemporaryDirectory(prefix="vitanna-audio-worker-") as temp:
            root = Path(temp)
            with phase("audio_download"):
                client.download(job.get("audio"), root / "source.mp3", 100 * 1024 * 1024, lease=job["lease_token"])
            with phase("audio_normalize"):
                report = normalize_mp3(root / "source.mp3", root / "normalized.mp3")
            with phase("audio_upload"):
                client.complete_audio(job, root / "normalized.mp3", report)
            log("audio_ready", job_id=job["job_id"], profile=AUDIO_PROFILE,
                integrated_lufs=report["integrated_lufs"], true_peak_dbtp=report["true_peak_dbtp"])
    except Exception:
        if job:
            try:
                client.post({"action": "failed", "job_id": job["job_id"],
                             "lease_token": job["lease_token"]})
            except Exception:
                pass
        raise


def run_once(client):
    with phase("claim"):
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
            with phase("download_audio"):
                local["audio"] = client.download(manifest.get("audio"), root / "audio.bin", 100 * 1024 * 1024)
            images = manifest.get("images")
            if not isinstance(images, list) or not 1 <= len(images) <= 12:
                raise ValueError("1–12 kép szükséges.")
            with phase("download_images"):
                local["images"] = [client.download(spec, root / f"image-{i:02}.bin", 20 * 1024 * 1024) for i, spec in enumerate(images)]
            for key, limit in (("srt", 2 * 1024 * 1024), ("elevenlabs_alignment", 4 * 1024 * 1024)):
                if key in manifest:
                    with phase("download_captions"):
                        local[key] = client.download(manifest[key], root / (key + ".bin"), limit)
            manifest_path = root / "job.json"
            manifest_path.write_text(json.dumps(local, ensure_ascii=False), encoding="utf-8")
            log("render_started", job_id=job["job_id"])
            output = root / "video.mp4"
            with phase("render"):
                report = render(manifest_path, output)
            with phase("upload_video"):
                client.complete(job, output, report)
            log("ready", job_id=job["job_id"], duration_seconds=report["duration_seconds"], processing_seconds=report["processing_seconds"], bytes=report["bytes"], audio_loudness=report.get("audio_loudness"))
    except Exception as exc:
        # The bridge ignores stale failures after a committed completion.
        try:
            client.post({"action": "failed", "job_id": job["job_id"], "revision": job["revision"], "lease_token": job["lease_token"], "error_code": type(exc).__name__})
        except Exception:
            pass
        raise


def main():
    log("worker_started", worker_version=WORKER_VERSION)
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
    with phase("configuration"):
        client = Bridge(os.environ.get("VITANNA_BRIDGE_URL", ""), os.environ.get("VITANNA_WORKER_TOKEN", ""))
    # A temporary MP3-normalization error must not block the existing video / Metricool tick.
    try:
        audio_client = Bridge(urllib.parse.urljoin(client.url, "napi-audio-level.php"), client.token)
        normalize_daily(audio_client)
    except Exception as exc:
        log("audio_failed", **failure_details(exc))
    run_once(client)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Do not include URLs, tokens, article text or remote response bodies in logs.
        log("failed", **failure_details(exc))
        raise SystemExit(1)
