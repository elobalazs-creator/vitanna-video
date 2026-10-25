"""VitAnna standalone MP3 + still images + timed captions -> H.264/AAC MP4."""
import argparse
import hashlib
import json
import math
import os
import subprocess
import tempfile
import time
from pathlib import Path

from captions import (INTRO_SECONDS, clean_text, from_alignment, parse_srt,
                      publication_label, validate_captions, write_ass)

AUDIO_PROFILE = "vitanna-loudness-v1"
TARGET_LUFS = -18.0
TRUE_PEAK_DBTP = -2.0
BRANDING_PROFILE = "vitanna-logo-intro-v2"

# Approved November 2026 cover assets, including their small versions.
BRANDED_COVERS = frozenset({
    "4fd7e0b5348dda8f7d21fc8e9c6bac6783020d435b365371f6b91a9b64a4d973",  # nov-2026-01-small.jpg
    "2d602a1e3f5aebb747e943bbd62632f191e21d56f695d5f99e48515091f25f3e",  # nov-2026-01.jpg
    "98d04c82588aebaa26d13f16d7591a1cfb89fa09e4063de0bf73ff421acd279d",  # nov-2026-02-small.jpg
    "827ab324783ad60d799913f71ddcb20ef017e72b5a5774c757bc88d5ac18428a",  # nov-2026-02.jpg
    "095ca10b8aa84dedac6c91b67f2f7176da39125aa172bf3fb02c491851717952",  # nov-2026-03-small.jpg
    "11ddb45e668e0f3c9686e13bfad6fca85b26b715cd35324306bac9cd59c08880",  # nov-2026-03.jpg
    "ddbbd39c3ef4c7a30ab818c4acb0fe09e02ffa8dbe3e675a7559c0ff38a05c8e",  # nov-2026-04-small.jpg
    "c846a8a78aeb68f25bed88e4788d0e31e2d6ef780ee2d8f0c99cfc8faf38e026",  # nov-2026-04.jpg
    "838e7d1190e53a730e8efb9b5c21730826c1df2749fd469ce8b506ef65365f34",  # nov-2026-05-small.jpg
    "a0375ddbaeaa9dba7208beb654a35b0d778fad0627f6d28bd5ad20a2bb81da67",  # nov-2026-05.jpg
    "d35b9b7b7f97889073eab00b213b1573c6544e8781c4e3d64f005a139ae193bc",  # nov-2026-06-small.jpg
    "01c85b9d7679704fc59861353f5498ff80c168e11304853d0cbc750539e87a39",  # nov-2026-06.jpg
    "4c5cf92cf706636a2789380fe170ca610508768cd682704739ce32844403150a",  # nov-2026-07-small.jpg
    "e93829947633e8b8dae7f988930a76f3bde8dafe33961d746e9385d43f393d8e",  # nov-2026-07.jpg
    "2dd1ad0b4da90b8748fd72c4b939fa92abdf7a06604f24bd3f0c42d27f7a697a",  # nov-2026-08-small.jpg
    "b81c5af73d7b5d69c88e22dc8962059326a1cd27b2a4c27208ebfe24e556a1b5",  # nov-2026-08.jpg
    "3971bef9211d60028b4d2c53d6a657e2491e6cee25274511e328006bb1c009bc",  # nov-2026-09-small.jpg
    "c32390b03af6ed428011bb8b23e14df0c08be55310cb79b9c933fb3db7ddbf93",  # nov-2026-09.jpg
    "35766508b20b55cfcab465414a65c0fe26a6385c112b93d481543984e766a5bf",  # nov-2026-10-small.jpg
    "f4560a870e11b3d624777a53ded91421b9509501736badef8264faa3724c9e5d",  # nov-2026-10.jpg
    "e52ec8a08a19f5e5585607bc8ccb346a5e10272868346f9266c3c7b066eff4f2",  # nov-2026-11-small.jpg
    "cc80811dbb91fae5f2c60e33d4b5123fa1d147e0c13b296db0c43c885f4809a8",  # nov-2026-11.jpg
    "ec6ce264e948b6abdd44b2d94c7e63f3fabe9261c241947ec1cc4b41e824864b",  # nov-2026-12-small.jpg
    "a6a1d955dff77dccbdf9f761f20666c340c131f091c8d4f6834e18dfea23b2be",  # nov-2026-12.jpg
    "d712ca4d9403e0baa6957431dc5f9e13692c4b8bc48ab7de912ca12efc27dd77",  # nov-2026-13-small.jpg
    "82ca76d64ee14dbb6b9a24b1c29779373e6ea8147010a95cc89ae3257bd86240",  # nov-2026-13.jpg
    "c5e0c044a0162f4fa3af46af0d1cd679a989dabc6e23f4608e4b8e6f3effbd01",  # nov-2026-14-small.jpg
    "c85cde8db23af0bdc20404cdf647a59c388bd2301584dbc81ebcd57ae8fac90d",  # nov-2026-14.jpg
    "069f72fe2ea731c309234bb33cdca6a0d457771fd8df38665780ae72ca22298c",  # nov-2026-15-small.jpg
    "8f99ad15cc90a7c7d10720efd6beee040a5eba915ad441367fcf1afc74317b5c",  # nov-2026-15.jpg
    "e97609ff2fd22048ccde5887e98e4ba09ed9bff57e72d7b7d999358248be62d1",  # nov-2026-16-small.jpg
    "c0b2d31d1f58f10f809624e34fd49e188e7b69e25d410b31dcce900a49555552",  # nov-2026-16.jpg
    "e8dc1b19c2e3f5539eb067946777c8a6efc5c8cf578153ffef53dcc29fa0b9ed",  # nov-2026-17-small.jpg
    "e13a7ff6183e6af0cfed4840751fe7328e738c840b13cc52fbe5aed754eb4ee3",  # nov-2026-17.jpg
    "572aa97586d938bd6ec39576cc03e74f5538890816fe21f8156ac256168eabb7",  # nov-2026-18-small.jpg
    "81cdfa4d7c8644764ef34695c86187d123e6acd8080e10551ccfeca5ec7a1b85",  # nov-2026-18.jpg
    "1fb2c31f492b97072b84af0c8d14c39fe711603dc3cea4996583c2f26bdddf5e",  # nov-2026-19-small.jpg
    "114448cdc251da6e437f39fe076bf7bd699fbaac8a83e821946fce2057a71170",  # nov-2026-19.jpg
    "4f1ec6330ff26655c3779729dfd054aaf8eab2a1644b966fcfaf405a360c0831",  # nov-2026-20-small.jpg
    "7ea4b55ae4e4365bb172534293dcb322d61dc8fd21de641c3f9094604fbaf00d",  # nov-2026-20.jpg
    "7f6a536e08a6cdb4d33c7166f20741a348a1252530cda3f1cdefa8dc78151896",  # nov-2026-21-small.jpg
    "0fa14a3680c5d30593ef5b76431434370b313e459df33191e62f48fda4679aa2",  # nov-2026-21.jpg
    "9396b7f89c5cf4d2b51fd6168d09be1bad0e425c2feb6a407c8819912209e88a",  # nov-2026-22-small.jpg
    "53527a68d0a432aa118b1c0239d6c0e10b67d729495518fd2834b8c1c08a3fba",  # nov-2026-22.jpg
    "e1770e80c5527c64233b632e0ae8c7d052b617d57ba4b9dd6440aeecf3042ce7",  # nov-2026-23-small.jpg
    "075514734e64fccd374ec27a499b79f0f2bb555bdba633836b531bc9129b70b2",  # nov-2026-23.jpg
    "b98e955da106865f39e7bb8a7465d4ecadab45076c6291605e9c18b9bf718511",  # nov-2026-24-small.jpg
    "f8f3f809ca2e3802e48663db725e84993927af561939470a766813e5a5a63612",  # nov-2026-24.jpg
    "9e72aae0c8dad6c17e756c490d219c996c3531017f0d59b234d8409f6a9d72d0",  # nov-2026-25-small.jpg
    "66e3f98802b640f537bc08342f3e14abbaba3c9567282c55014472a12b01c4cd",  # nov-2026-25.jpg
    "52169a511a9b11d68f2638b0660b1b590afde71eb607e604de9a594e0c71d890",  # nov-2026-26-small.jpg
    "040f61d724c017c8ce70cd188d1c3f1ff6014ed3c19757736c631129749f3ae3",  # nov-2026-26.jpg
    "0296915d4a768cd11a9ecbcf7afdd0d7fc0c81a92b932fb3d1dc761f2abc9eab",  # nov-2026-27-small.jpg
    "aa798978f646b8f6f373a737bc5e09bc10465b870bdbaa11403feb71bd39bd63",  # nov-2026-27.jpg
    "3ae8e899d8407665a6e6300250e606910c2afad51571ef8e233df932099760a8",  # nov-2026-28-small.jpg
    "d047e34339a07435ade4e64ef65f3a2ca53d0edf7371f545dc4df07aa245b937",  # nov-2026-28.jpg
    "51e3ca354acdc5596948abb394c3495d3eafb65db78778e693cd746abef7fec4",  # nov-2026-29-small.jpg
    "de2aceccc765f1e04d9157845a5b8d75b9c2d9161b5b92ba84612a1d99cfa440",  # nov-2026-29.jpg
    "1efd31f8225668fccfb6cba5d64a65ae3c26a6737d7cbd8828cfa277bc0dd4e5",  # nov-2026-30-small.jpg
    "93fa9c92728ea956c8b1e5b174466c7474feebdaa8c2f498987e854f15844bc4",  # nov-2026-30.jpg
})



class MediaProcessingError(RuntimeError):
    """Fixed diagnostic codes only: never expose FFmpeg arguments or raw stderr."""
    def __init__(self, reason, exit_code=None, timeout_seconds=None):
        messages = {
            'timeout': 'A médiafeldolgozás túllépte a futási időkorlátot.',
            'memory': 'A médiafeldolgozó nem tudott elegendő memóriát lefoglalni.',
            'disk_full': 'Elfogyott a médiafeldolgozás ideiglenes tárhelye.',
            'invalid_input': 'A médiafeldolgozó hibás vagy nem olvasható bemenetet talált.',
            'missing_filter': 'A szükséges FFmpeg-szűrő nem érhető el.',
            'missing_encoder': 'A szükséges videó- vagy hangkódoló nem érhető el.',
            'filter_failed': 'A kép- vagy feliratszűrő feldolgozása hibával leállt.',
            'killed': 'A médiafeldolgozó folyamatot SIGKILL jel állította le. Az okot a Render erőforrásnaplója mutathatja meg.',
            'process_failed': 'A médiafeldolgozó hibakóddal leállt.',
        }
        reason = reason if reason in messages else 'process_failed'
        super().__init__(messages[reason])
        self.media_reason = reason
        self.exit_code = exit_code
        self.timeout_seconds = timeout_seconds


def media_failure(exc):
    raw = exc.stderr or ''
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', errors='replace')
    raw = raw.lower()
    reason = 'process_failed'
    for text, code in (
        ('cannot allocate memory', 'memory'), ('out of memory', 'memory'),
        ('no space left on device', 'disk_full'),
        ('invalid data found', 'invalid_input'), ('error opening input', 'invalid_input'),
        ('no such filter', 'missing_filter'), ('unknown encoder', 'missing_encoder'),
        ('error reinitializing filters', 'filter_failed'),
        ('failed to configure output pad', 'filter_failed'),
    ):
        if text in raw:
            reason = code
            break
    if exc.returncode in (-9, 137):
        reason = 'killed'
    return MediaProcessingError(reason, exit_code=exc.returncode)


def render_step(stage, **numbers):
    """Call sites pass fixed stage names and numeric diagnostics only."""
    print(json.dumps({'event': 'render_step', 'stage': stage, **numbers},
                     ensure_ascii=False, allow_nan=False), flush=True)


def branding_logo():
    """The deployment supplies the same brand asset for every daily video."""
    path = Path(__file__).resolve().with_name("vitanna-logo.png")
    if not path.is_file() or not 0 < path.stat().st_size <= 2 * 1024 * 1024:
        raise ValueError("Hiányzik a vitanna-logo.png. A logót és a Dockerfile-t is töltsd fel, majd indíts új buildet.")
    info = probe(path)
    stream = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
    if stream.get("codec_name") != "png" or not 0 < stream.get("width", 0) * stream.get("height", 0) <= 4000000:
        raise ValueError("A VitAnna-logó érvénytelen PNG-fájl.")
    return path


def branded_slide(image, logo, width, height, output, already_branded=False):
    """Composite once per still image, before the timed captions are encoded."""
    if already_branded:
        run(["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
             "-i", str(image), "-vf",
             f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
             f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x203A31,setsar=1",
             "-frames:v", "1", "-threads", "1", str(output)])
        return
    factor = height / 1080
    x, y = round(56 * factor), round(44 * factor)
    box_w, box_h = round(312 * factor), round(126 * factor)
    logo_w, logo_h = round(280 * factor), round(94 * factor)
    inset_x, inset_y = round(16 * factor), round(16 * factor)
    filters = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x203A31,setsar=1,"
        f"drawbox=x={x}:y={y}:w={box_w}:h={box_h}:color=0xF8F7F1@0.94:t=fill[background];"
        f"[1:v]scale={logo_w}:{logo_h}:force_original_aspect_ratio=decrease,"
        f"format=rgba,pad={logo_w}:{logo_h}:(ow-iw)/2:(oh-ih)/2:color=0x00000000[logo];"
        f"[background][logo]overlay=x={x + inset_x}:y={y + inset_y}:format=auto,"
        "format=rgb24[branded]"
    )
    run(["ffmpeg", "-nostdin", "-v", "error", "-filter_complex_threads", "1",
         "-protocol_whitelist", "file,pipe", "-i", str(image),
         "-protocol_whitelist", "file,pipe", "-i", str(logo),
         "-filter_complex", filters, "-map", "[branded]", "-frames:v", "1",
         "-threads", "1", str(output)])


def audio_command(args, timeout=180):
    try:
        return subprocess.run(args, check=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        raise media_failure(exc) from None
    except subprocess.TimeoutExpired:
        raise MediaProcessingError("timeout", timeout_seconds=timeout) from None


def measure_audio(path):
    result = audio_command(["ffmpeg", "-nostdin", "-hide_banner", "-nostats",
        "-protocol_whitelist", "file,pipe", "-i", str(path), "-map", "0:a:0", "-vn",
        "-af", f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK_DBTP}:LRA=11:print_format=json",
        "-f", "null", "-"])
    try:
        values = json.loads(result.stderr[result.stderr.rfind("{"):])
        values = {key: float(values[key]) for key in
                  ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
        if not all(math.isfinite(value) for value in values.values()):
            raise ValueError()
        if not -70 <= values["input_i"] <= 0:
            raise ValueError()
        return values
    except (KeyError, ValueError, TypeError):
        raise RuntimeError("A hang néma, túl halk vagy nem mérhető biztonságosan.") from None


def normalize_pcm(source, target):
    info = probe(source)
    stream = next((s for s in info["streams"] if s["codec_type"] == "audio"), {})
    duration = float(info["format"]["duration"])
    if stream.get("channels") not in (1, 2) or not math.isfinite(duration) or not 1 <= duration <= 900:
        raise ValueError("1–900 másodperces mono vagy sztereó hang szükséges.")
    render_step("measure_source_audio", duration_seconds=round(duration, 3))
    measured = measure_audio(source)
    render_step("normalize_audio", source_lufs=measured["input_i"], source_peak_dbtp=measured["input_tp"])
    filters = (f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK_DBTP}:LRA=11:"
        f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
        f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
        f"offset={measured['target_offset']}:linear=true")
    audio_command(["ffmpeg", "-nostdin", "-v", "error", "-n",
        "-protocol_whitelist", "file,pipe", "-i", str(source), "-map", "0:a:0", "-vn",
        "-af", filters, "-ar", "48000", "-ac", str(stream["channels"]),
        "-c:a", "pcm_s24le", "-map_metadata", "-1", str(target)])
    return {"profile": AUDIO_PROFILE, "target_lufs": TARGET_LUFS,
            "true_peak_target_dbtp": TRUE_PEAK_DBTP,
            "source_integrated_lufs": measured["input_i"],
            "source_true_peak_dbtp": measured["input_tp"], "duration_seconds": duration}


def check_normalized(path, duration):
    render_step("verify_loudness")
    measured = measure_audio(path)
    actual_duration = float(probe(path)["format"]["duration"])
    render_step("loudness_result", integrated_lufs=measured["input_i"], true_peak_dbtp=measured["input_tp"], duration_seconds=round(actual_duration, 3), expected_duration_seconds=round(duration, 3))
    if abs(measured["input_i"] - TARGET_LUFS) > 0.8 or measured["input_tp"] > -1.0:
        raise RuntimeError("A javított hang hangereje vagy csúcsszintje nem megfelelő.")
    if abs(actual_duration - duration) > 0.30:
        raise RuntimeError("A hangjavítás közben megváltozott a hang hossza.")
    return {"integrated_lufs": measured["input_i"], "true_peak_dbtp": measured["input_tp"]}


def normalize_mp3(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.suffix.lower() != ".mp3" or output.exists():
        raise ValueError("Új .mp3 kimeneti fájlnév szükséges.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vitanna-audio-", dir=output.parent) as temp:
        work = Path(temp)
        pcm = work / "normalized.wav"
        report = normalize_pcm(source, pcm)
        result = work / "normalized.mp3"
        audio_command(["ffmpeg", "-nostdin", "-v", "error", "-n", "-i", str(pcm),
            "-map", "0:a:0", "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "48000",
            "-map_metadata", "-1", str(result)])
        report.update(check_normalized(result, report["duration_seconds"]))
        report.update({"source_sha256": sha256(source), "sha256": sha256(result),
                       "bytes": result.stat().st_size})
        os.link(result, output)
    return report


def run(args, cwd=None, timeout=90):
    try:
        return subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout).stdout
    except subprocess.CalledProcessError as exc:
        raise media_failure(exc) from None
    except subprocess.TimeoutExpired:
        raise MediaProcessingError("timeout", timeout_seconds=timeout) from None


def probe(path):
    return json.loads(run(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_format", "-show_streams", "-of", "json", str(path)]))


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def asset(root, spec, max_bytes):
    if not isinstance(spec, dict) or not isinstance(spec.get("path"), str):
        raise ValueError("Hiányzó helyi médiafájl.")
    rel = Path(spec["path"])
    path = (root / rel).resolve()
    if rel.is_absolute() or not path.is_relative_to(root) or not path.is_file():
        raise ValueError("A médiafájlnak a feladat könyvtárán belül kell lennie.")
    if not 0 < path.stat().st_size <= max_bytes:
        raise ValueError("Üres vagy túl nagy médiafájl.")
    if spec.get("sha256") and sha256(path) != spec["sha256"]:
        raise ValueError("A médiafájl ellenőrzőösszege eltér.")
    return path


def render(manifest_path, output_path):
    began = time.monotonic()
    render_step("validate_inputs")
    manifest_path, output_path = Path(manifest_path).resolve(), Path(output_path).resolve()
    if manifest_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Túl nagy feladatleíró.")
    job = json.loads(manifest_path.read_text(encoding="utf-8"))
    if job.get("schema_version") != 1:
        raise ValueError("Ismeretlen feladatverzió.")
    root = manifest_path.parent
    if job.get("skip_video") is True:
        return {"status": "skipped", "reason": "A cikk videója kihagyásra jelölve."}
    audio = asset(root, job.get("audio"), 100 * 1024 * 1024)
    audio_info = probe(audio)
    if not any(s["codec_type"] == "audio" for s in audio_info["streams"]):
        raise ValueError("Az MP3/fájl nem tartalmaz hangsávot.")
    duration = float(audio_info["format"]["duration"])
    if not math.isfinite(duration) or not 1 <= duration <= 900:
        raise ValueError("A hang hossza 1–900 másodperc lehet.")
    specs = job.get("images")
    if not isinstance(specs, list) or not 1 <= len(specs) <= 12:
        raise ValueError("1–12 háttérkép szükséges.")
    images = [asset(root, spec, 20 * 1024 * 1024) for spec in specs]
    for path in images:
        info = probe(path)
        stream = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
        if stream.get("codec_name") not in {"png", "mjpeg", "webp"}:
            raise ValueError("Csak PNG, JPEG és WebP háttérkép használható.")
        if stream.get("width", 0) * stream.get("height", 0) > 40000000:
            raise ValueError("Túl nagy képfelbontás.")
    config = job.get("video", {})
    width, height = int(config.get("width", 1920)), int(config.get("height", 1080))
    if (width, height) not in {(1920, 1080), (1280, 720)}:
        raise ValueError("A támogatott felbontás 1920×1080 vagy 1280×720.")
    fps = 25
    caption_inputs = [key for key in ("captions", "srt", "elevenlabs_alignment") if key in job]
    if len(caption_inputs) > 1:
        raise ValueError("Egyszerre csak egy feliratforrás adható meg.")
    captions = job.get("captions", [])
    if "srt" in job:
        captions = parse_srt(asset(root, job["srt"], 2 * 1024 * 1024).read_text(encoding="utf-8-sig"))
    if "elevenlabs_alignment" in job:
        captions = from_alignment(json.loads(asset(root, job["elevenlabs_alignment"], 4 * 1024 * 1024).read_text(encoding="utf-8")))
    captions = validate_captions(captions, duration)
    if job.get("require_captions", True) and not captions:
        raise ValueError("Hiányzik az időzített felirat; néma vagy felirat nélküli helyettesítő nem készül.")
    if output_path.suffix.lower() != ".mp4":
        raise ValueError("A kimenet .mp4 fájl legyen.")
    if output_path.exists():
        raise FileExistsError("A kész videót nem írjuk felül; adj új kimeneti fájlnevet.")
    logo = branding_logo()
    # November's delivered covers already contain the approved logo. Match exact
    # bytes, never a filename or a guess, so an unbranded replacement gets a logo.
    already_branded = [sha256(image) in BRANDED_COVERS for image in images]
    title_top = 360 if any(already_branded) else 190
    title = clean_text(job.get("title", ""))
    intro_duration = min(INTRO_SECONDS, duration) if title else 0.0
    publication_date = job.get("publication_date", "")
    publication_label(publication_date)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vitanna-", dir=output_path.parent) as temp:
        work = Path(temp)
        normalized = work / "normalized.wav"
        loudness = normalize_pcm(audio, normalized)
        render_step("audio_normalized", elapsed_seconds=round(time.monotonic() - began, 3))
        lines = ["ffconcat version 1.0"]
        total_frames = math.ceil(duration * fps)
        basic_frames, extra_frames = divmod(total_frames, len(images))
        offset_frames = 0
        # Encode each still-image span as a bounded stream. Long sparse-image PTS gaps
        # through an fps filter can otherwise queue thousands of raw Full HD frames.
        for index, image in enumerate(images):
            filename = f"slide-{index:02}.png"
            render_step("prepare_slide", slide=index + 1, slide_count=len(images))
            branded_slide(image, logo, width, height, work / filename, already_branded[index])
            frames = basic_frames + (1 if index < extra_frames else 0)
            start, end = offset_frames / fps, (offset_frames + frames) / fps
            segment_captions = [{"start": max(c["start"], start) - start, "end": min(c["end"], end) - start, "text": c["text"]} for c in captions if min(c["end"], end) - max(c["start"], start) >= 0.01]
            subtitle_file = f"captions-{index:02}.ass"
            render_step("prepare_captions", slide=index + 1, caption_count=len(segment_captions))
            write_ass(work / subtitle_file, segment_captions, title, frames / fps,
                      width, height, title_top=title_top, publication_date=publication_date,
                      segment_start=start, intro_duration=intro_duration)
            segment_file = f"segment-{index:02}.mp4"
            remaining = max(1, int(1800 - (time.monotonic() - began)))
            render_step("encode_slide", slide=index + 1, duration_seconds=round(frames / fps, 3), timeout_seconds=remaining)
            run(["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe", "-loop", "1", "-framerate", "25", "-i", filename, "-vf", f"ass={subtitle_file},format=yuv420p", "-frames:v", str(frames), "-an", "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "23", "-threads", "2", segment_file], cwd=work, timeout=remaining)
            render_step("slide_encoded", slide=index + 1, elapsed_seconds=round(time.monotonic() - began, 3))
            lines.append(f"file '{segment_file}'")
            offset_frames += frames
        (work / "slides.ffconcat").write_text("\n".join(lines) + "\n", encoding="utf-8")
        render_step("mux_video_audio")
        # Video stream copy avoids another encode. Measured/limited PCM becomes AAC.
        remaining = max(1, int(1800 - (time.monotonic() - began)))
        run(["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe", "-safe", "1", "-f", "concat", "-i", "slides.ffconcat", "-protocol_whitelist", "file,pipe", "-i", str(normalized), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-t", f"{duration:.6f}", "-movflags", "+faststart", "-map_metadata", "-1", "result.mp4"], cwd=work, timeout=remaining)
        video = work / "result.mp4"
        render_step("verify_output")
        info = probe(video)
        streams = {stream["codec_type"]: stream for stream in info["streams"]}
        v, a = streams.get("video", {}), streams.get("audio", {})
        if v.get("codec_name") != "h264" or a.get("codec_name") != "aac":
            raise RuntimeError("A kimenet nem H.264/AAC videó.")
        actual_duration = float(info["format"]["duration"])
        render_step("output_result", duration_seconds=round(actual_duration, 3), expected_duration_seconds=round(duration, 3), width=v.get("width", 0), height=v.get("height", 0), bytes=video.stat().st_size)
        if abs(actual_duration - duration) > 0.30 or (v.get("width"), v.get("height")) != (width, height):
            raise RuntimeError("A kimenet hossza vagy mérete hibás.")
        if video.stat().st_size > 500 * 1024 * 1024:
            raise RuntimeError("A videó túl nagy a feltöltéshez.")
        loudness.update(check_normalized(video, duration))
        result = {"status": "ready", "duration_seconds": round(actual_duration, 3), "width": width, "height": height, "video_codec": "h264", "audio_codec": "aac", "image_count": len(images), "caption_count": len(captions), "bytes": video.stat().st_size, "sha256": sha256(video), "processing_seconds": round(time.monotonic() - began, 3), "source_audio_sha256": sha256(audio)}
        result["audio_loudness"] = loudness
        result["branding"] = {"profile": BRANDING_PROFILE, "logo_sha256": sha256(logo),
                              "placement": "top_left", "all_slides": True,
                              "added_to_slides": already_branded.count(False),
                              "existing_on_slides": already_branded.count(True),
                              "intro_seconds": intro_duration,
                              "publication_date": publication_date or None,
                              "audio_offset_seconds": 0}
        # Atomic, no-clobber publication on the same filesystem; retries cannot replace a file.
        os.link(video, output_path)
    output_path.with_suffix(".report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VitAnna videó összeállítása helyi fájlokból")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(render(args.manifest, args.output), ensure_ascii=False))
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
        parser.exit(1, f"Hiba: {exc}\n")
