"""Reproducible sample assets. Synthetic tone, not an ElevenLabs or OpenAI call."""
import argparse
import json
from pathlib import Path
from renderer import run


def make_demo(folder, seconds=12):
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    colors = ["0x264B40", "0x4B5C50", "0x203B35"]
    extensions = ["png", "jpg", "webp"]
    names = []
    for index, (color, extension) in enumerate(zip(colors, extensions)):
        name = f"background-{index+1}.{extension}"
        names.append(name)
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=1280x720", "-vf", "drawbox=x=0:y=0:w=iw:h=165:color=black@0.18:t=fill,drawbox=x=150:y=320:w=980:h=2:color=0xC8B889@0.7:t=fill", "-frames:v", "1", "-threads", "1", str(folder / name)])
    run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=48000:duration={seconds}", "-af", "volume=0.02", "-c:a", "libmp3lame", "-b:a", "128k", str(folder / "demo-audio.mp3")])
    texts = ["Ez technikai próba: halk jelzőhang, nem valódi útravaló.", "Magyar ékezetpróba: á, é, í, ó, ö, ő, ú, ü, ű.", "A háttérképek váltakoznak; az eredeti hang végig megmarad."]
    captions = [{"start": i * seconds / 3 + 0.2, "end": (i+1) * seconds / 3 - 0.2, "text": text} for i, text in enumerate(texts)]
    job = {"schema_version": 1, "title": "Bemutató · a napi útravaló videója", "audio": {"path": "demo-audio.mp3"}, "images": [{"path": name} for name in names], "require_captions": True, "captions": captions, "video": {"width": 1920, "height": 1080}}
    (folder / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return folder / "job.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--seconds", type=int, default=12)
    args = parser.parse_args()
    if not 6 <= args.seconds <= 900:
        parser.error("A hossz 6–900 másodperc lehet.")
    print(make_demo(args.output, args.seconds))
