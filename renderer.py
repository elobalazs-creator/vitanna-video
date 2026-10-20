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

from captions import from_alignment, parse_srt, validate_captions, write_ass

AUDIO_PROFILE = "vitanna-loudness-v1"
TARGET_LUFS = -18.0
TRUE_PEAK_DBTP = -2.0


def audio_command(args, timeout=180):
    try:
        return subprocess.run(args, check=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, timeout=timeout)
    except subprocess.CalledProcessError:
        raise RuntimeError("A hang hangerő-kiegyenlítése nem sikerült.") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError("A hangfeldolgozás túllépte az időkorlátot.") from None


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
    measured = measure_audio(source)
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
    measured = measure_audio(path)
    actual_duration = float(probe(path)["format"]["duration"])
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
        # Local safe filenames only; no signed asset URLs or tokens in FFmpeg arguments.
        raise RuntimeError("Médiafeldolgozási hiba: " + exc.stderr[-2500:]) from None
    except subprocess.TimeoutExpired:
        raise RuntimeError("A médiafeldolgozás túllépte a futási időkorlátot.") from None


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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vitanna-", dir=output_path.parent) as temp:
        work = Path(temp)
        normalized = work / "normalized.wav"
        loudness = normalize_pcm(audio, normalized)
        lines = ["ffconcat version 1.0"]
        total_frames = math.ceil(duration * fps)
        basic_frames, extra_frames = divmod(total_frames, len(images))
        offset_frames = 0
        # Encode each still-image span as a bounded stream. Long sparse-image PTS gaps
        # through an fps filter can otherwise queue thousands of raw Full HD frames.
        for index, image in enumerate(images):
            filename = f"slide-{index:02}.png"
            run(["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe", "-i", str(image), "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x203A31,setsar=1", "-frames:v", "1", "-threads", "1", filename], cwd=work)
            frames = basic_frames + (1 if index < extra_frames else 0)
            start, end = offset_frames / fps, (offset_frames + frames) / fps
            segment_captions = [{"start": max(c["start"], start) - start, "end": min(c["end"], end) - start, "text": c["text"]} for c in captions if min(c["end"], end) - max(c["start"], start) >= 0.01]
            subtitle_file = f"captions-{index:02}.ass"
            write_ass(work / subtitle_file, segment_captions, job.get("title", ""), frames / fps, width, height)
            segment_file = f"segment-{index:02}.mp4"
            remaining = max(1, int(1800 - (time.monotonic() - began)))
            run(["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe", "-loop", "1", "-framerate", "25", "-i", filename, "-vf", f"ass={subtitle_file},format=yuv420p", "-frames:v", str(frames), "-an", "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "23", "-threads", "2", segment_file], cwd=work, timeout=remaining)
            lines.append(f"file '{segment_file}'")
            offset_frames += frames
        (work / "slides.ffconcat").write_text("\n".join(lines) + "\n", encoding="utf-8")
        # Video stream copy avoids another encode. Measured/limited PCM becomes AAC.
        remaining = max(1, int(1800 - (time.monotonic() - began)))
        run(["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe", "-safe", "1", "-f", "concat", "-i", "slides.ffconcat", "-protocol_whitelist", "file,pipe", "-i", str(normalized), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-t", f"{duration:.6f}", "-movflags", "+faststart", "-map_metadata", "-1", "result.mp4"], cwd=work, timeout=remaining)
        video = work / "result.mp4"
        info = probe(video)
        streams = {stream["codec_type"]: stream for stream in info["streams"]}
        v, a = streams.get("video", {}), streams.get("audio", {})
        if v.get("codec_name") != "h264" or a.get("codec_name") != "aac":
            raise RuntimeError("A kimenet nem H.264/AAC videó.")
        actual_duration = float(info["format"]["duration"])
        if abs(actual_duration - duration) > 0.30 or (v.get("width"), v.get("height")) != (width, height):
            raise RuntimeError("A kimenet hossza vagy mérete hibás.")
        if video.stat().st_size > 500 * 1024 * 1024:
            raise RuntimeError("A videó túl nagy a feltöltéshez.")
        loudness.update(check_normalized(video, duration))
        result = {"status": "ready", "duration_seconds": round(actual_duration, 3), "width": width, "height": height, "video_codec": "h264", "audio_codec": "aac", "image_count": len(images), "caption_count": len(captions), "bytes": video.stat().st_size, "sha256": sha256(video), "processing_seconds": round(time.monotonic() - began, 3), "source_audio_sha256": sha256(audio)}
        result["audio_loudness"] = loudness
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
