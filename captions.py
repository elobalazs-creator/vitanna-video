"""Timed captions only: do not guess timing from an untimed transcript."""
import html
import math
import re
import textwrap


def clean_text(value):
    if not isinstance(value, str):
        raise ValueError("A felirat szövege nem szöveg.")
    value = html.unescape(re.sub(r"<[^>]*>", "", value))
    value = value.replace("\\", "/").replace("{", "(").replace("}", ")")
    return " ".join(value.split())


def validate_captions(items, duration):
    if not isinstance(items, list) or len(items) > 2000:
        raise ValueError("Hibás vagy túl sok felirat.")
    result = []
    previous_end = 0.0
    for item in items:
        start, end = float(item["start"]), float(item["end"])
        text = clean_text(item["text"])
        if not all(math.isfinite(n) for n in (start, end)):
            raise ValueError("Érvénytelen feliratidő.")
        if start < previous_end - 0.01 or end <= start or start < 0 or end > duration + 0.25:
            raise ValueError("Átfedő vagy a hang hosszán kívüli felirat.")
        if not text or len(text) > 160:
            raise ValueError("Üres vagy túl hosszú feliratblokk (legfeljebb 160 karakter).")
        result.append({"start": start, "end": min(end, duration), "text": text})
        previous_end = end
    return result


def parse_srt(text):
    pattern = re.compile(r"(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})")
    items = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "").strip()):
        if not block.strip():
            continue
        lines = block.splitlines()
        index = 1 if lines[0].strip().isdigit() else 0
        if index >= len(lines):
            raise ValueError("Hibás SRT felirat.")
        match = pattern.fullmatch(lines[index].strip())
        if not match:
            raise ValueError("Hibás SRT időzítés.")
        nums = list(map(int, match.groups()))
        if any(nums[i] >= 60 for i in (1, 2, 5, 6)):
            raise ValueError("Hibás SRT perc/másodperc.")
        start = nums[0] * 3600 + nums[1] * 60 + nums[2] + nums[3] / 1000
        end = nums[4] * 3600 + nums[5] * 60 + nums[6] + nums[7] / 1000
        items.append({"start": start, "end": end, "text": " ".join(lines[index + 1:])})
    return items


def from_alignment(data):
    alignment = data.get("normalized_alignment") or data.get("alignment") or data
    chars = alignment.get("characters")
    starts = alignment.get("character_start_times_seconds")
    ends = alignment.get("character_end_times_seconds")
    if not all(isinstance(v, list) for v in (chars, starts, ends)) or not (len(chars) == len(starts) == len(ends)):
        raise ValueError("Hibás ElevenLabs karakter-időzítés.")
    if not chars or len(chars) > 50000:
        raise ValueError("Üres vagy túl hosszú ElevenLabs időzítés.")
    words, word, start, end, previous_start = [], "", None, 0.0, 0.0
    for char, s, e in zip(chars, starts, ends):
        s, e = float(s), float(e)
        if not isinstance(char, str) or len(char) != 1 or not math.isfinite(s) or not math.isfinite(e) or s < previous_start or s < 0 or e < s:
            raise ValueError("Hibás karakter vagy idő az ElevenLabs-időzítésben.")
        previous_start = s
        if char.isspace():
            if word:
                words.append((word, start, end))
                word, start = "", None
        else:
            if start is None:
                start = s
            word += char
            end = e
    if word:
        words.append((word, start, end))
    result, group = [], []
    for word in words:
        new_length = len(" ".join(w[0] for w in group + [word]))
        if group and (new_length > 82 or word[2] - group[0][1] > 5.5):
            result.append({"start": group[0][1], "end": group[-1][2], "text": " ".join(w[0] for w in group)})
            group = []
        group.append(word)
        if word[0].endswith((".", "!", "?", ";")) and len(" ".join(w[0] for w in group)) >= 30:
            result.append({"start": group[0][1], "end": group[-1][2], "text": " ".join(w[0] for w in group)})
            group = []
    if group:
        result.append({"start": group[0][1], "end": group[-1][2], "text": " ".join(w[0] for w in group)})
    return result


def stamp(seconds):
    hundredths = round(seconds * 100)
    h, hundredths = divmod(hundredths, 360000)
    m, hundredths = divmod(hundredths, 6000)
    s, cs = divmod(hundredths, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def write_ass(path, captions, title, duration, width, height):
    scale = height / 1080
    title = clean_text(title)
    if len(title) > 180:
        raise ValueError("A cím legfeljebb 180 karakter lehet.")
    def wrap(text, length):
        return r"\N".join(textwrap.wrap(text, width=length, break_long_words=True, break_on_hyphens=False))
    styles = [
        f"Style: Brand,DejaVu Sans,{round(28*scale)},&H00E4DFCE,&H00FFFFFF,&H002E3028,&H99302C24,0,0,0,0,100,100,0,0,1,1,0,8,{round(90*scale)},{round(90*scale)},{round(34*scale)},1",
        f"Style: Title,DejaVu Sans,{round(44*scale)},&H00FFFFFF,&H00FFFFFF,&H002A3028,&H99302C24,-1,0,0,0,100,100,0,0,1,2,1,8,{round(120*scale)},{round(120*scale)},{round(83*scale)},1",
        f"Style: Caption,DejaVu Sans,{round(46*scale)},&H00FFFFFF,&H00FFFFFF,&H002A3028,&HC0222923,0,0,0,0,100,100,0,0,3,3,0,2,{round(110*scale)},{round(110*scale)},{round(80*scale)},1",
    ]
    rows = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]", "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding", *styles, "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    rows.append(f"Dialogue: 0,0:00:00.00,{stamp(duration)},Brand,,0,0,0,,VitAnna · Napi útravaló")
    if title:
        rows.append(f"Dialogue: 0,0:00:00.00,{stamp(duration)},Title,,0,0,0,,{wrap(title, 62)}")
    for caption in captions:
        rows.append(f"Dialogue: 1,{stamp(caption['start'])},{stamp(caption['end'])},Caption,,0,0,0,,{wrap(caption['text'], 49)}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
