"""Timed captions only: do not guess timing from an untimed transcript."""
import html
import math
import re
import textwrap
from datetime import date
from functools import lru_cache

from PIL import ImageFont

INTRO_SECONDS = 5.0
MONTHS_HU = ("január", "február", "március", "április", "május", "június",
             "július", "augusztus", "szeptember", "október", "november", "december")


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


def publication_label(value):
    if value is None or value == "":
        return ""  # Older bridge versions remain usable; never invent a date.
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("A cikk megjelenési dátuma ÉÉÉÉ-HH-NN formátumú legyen.")
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise ValueError("A cikk megjelenési dátuma érvénytelen.") from None
    return f"{day.year}. {MONTHS_HU[day.month - 1]} {day.day}."


@lru_cache(maxsize=96)
def title_font(size, serif):
    filename = "DejaVuSerif.ttf" if serif else "DejaVuSans-Bold.ttf"
    return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/" + filename, size)


def title_lines(text, max_width, max_size, min_size, max_lines, serif=True, max_height=None):
    """Measure actual Hungarian glyphs, including ő/ű, and fit without truncation."""
    for size in range(max_size, min_size - 1, -1):
        font = title_font(size, serif)
        lines, current = [], ""
        for word in text.split():
            candidate = (current + " " + word).strip()
            if font.getlength(candidate) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            current = ""
            # Extremely long single words are split safely, rather than clipped.
            for char in word:
                if current and font.getlength(current + char) > max_width:
                    lines.append(current)
                    current = ""
                current += char
        if current:
            lines.append(current)
        # Keep short Hungarian articles/conjunctions with the following phrase.
        for index in range(len(lines) - 1):
            head, separator, tail = lines[index].rpartition(" ")
            if separator and tail.lower() in {"a", "az", "egy", "és", "vagy", "hogy"}:
                following = tail + " " + lines[index + 1]
                if font.getlength(following) <= max_width:
                    lines[index], lines[index + 1] = head, following
        if len(lines) <= max_lines and (max_height is None or len(lines) * round(size * 1.25) <= max_height):
            return size, lines
    raise ValueError("A cím nem fér el olvashatóan a nyitóképen.")


def write_ass(path, captions, title, duration, width, height, title_top=190,
              publication_date="", segment_start=0.0, intro_duration=INTRO_SECONDS):
    scale = height / 1080
    title = clean_text(title)
    if len(title) > 180:
        raise ValueError("A cím legfeljebb 180 karakter lehet.")
    date_label = publication_label(publication_date)
    def wrap(text, length):
        return r"\N".join(textwrap.wrap(text, width=length, break_long_words=True, break_on_hyphens=False))
    styles = [
        f"Style: Brand,DejaVu Sans,{round(24*scale)},&H00AFCCDD,&H00FFFFFF,&H002E3028,&H99302C24,0,0,0,0,100,100,{3*scale:.2f},0,1,0.5,0,9,{round(56*scale)},{round(56*scale)},{round(64*scale)},1",
        f"Style: Title,DejaVu Sans,{round(44*scale)},&H00FFFFFF,&H00FFFFFF,&H002A3028,&H99302C24,-1,0,0,0,100,100,0,0,1,2,1,7,{round(56*scale)},{round(56*scale)},{round(title_top*scale)},1",
        "Style: Intro,DejaVu Serif,72,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        f"Style: Date,DejaVu Sans,{round(30*scale)},&H00AFCCDD,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        f"Style: Website,DejaVu Sans,{round(23*scale)},&H00FFFFFF,&H00FFFFFF,&H002A3028,&H99302C24,0,0,0,0,100,100,0,0,1,0.5,0,3,{round(56*scale)},{round(56*scale)},{round(32*scale)},1",
        f"Style: Caption,DejaVu Sans,{round(46*scale)},&H00FFFFFF,&H00FFFFFF,&H002A3028,&HC0222923,0,0,0,0,100,100,0,0,3,3,0,2,{round(110*scale)},{round(110*scale)},{round(80*scale)},1",
    ]
    rows = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]", "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding", *styles, "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    rows.append(f"Dialogue: 0,0:00:00.00,{stamp(duration)},Brand,,0,0,0,,NAPI ÚTRAVALÓ")
    rows.append(f"Dialogue: 0,0:00:00.00,{stamp(duration)},Website,,0,0,0,,vitanna.eu")
    if title:
        # Segment-relative times keep the title card on the GLOBAL first five
        # seconds only, even if a slide boundary happens during the opening.
        intro_end = max(0.0, min(duration, intro_duration - segment_start))
        if intro_end > 0:
            y = max(280, title_top)
            x0, y0, panel_w, panel_h = 0, round(y*scale), round(1300*scale), round(430*scale)
            panel = (f"{{\\an7\\pos({x0},{y0})\\p1\\bord0\\shad0"
                     f"\\1c&H383C0D&\\1a&H38&}}m 0 0 l {panel_w} 0 "
                     f"l {panel_w} {panel_h} l 0 {panel_h}{{\\p0}}")
            rows.append(f"Dialogue: 0,0:00:00.00,{stamp(intro_end)},Intro,,0,0,0,,{panel}")
            size, lines = title_lines(title, 1120, 72, 28, 6, max_height=270)
            pitch = round(size * 1.25)
            title_y = y + 70
            for index, line in enumerate(lines):
                position = f"{{\\q2\\an7\\pos({round(80*scale)},{round((title_y+index*pitch)*scale)})\\fs{round(size*scale)}}}"
                rows.append(f"Dialogue: 1,0:00:00.00,{stamp(intro_end)},Intro,,0,0,0,,{position}{line}")
            if date_label:
                position = f"{{\\q2\\an7\\pos({round(82*scale)},{round((title_y+len(lines)*pitch+18)*scale)})}}"
                rows.append(f"Dialogue: 1,0:00:00.00,{stamp(intro_end)},Date,,0,0,0,,{position}{date_label}")
        if intro_end < duration:
            size, lines = title_lines(title, 1610, 44, 30, 4, serif=False)
            for index, line in enumerate(lines):
                position = f"{{\\q2\\an7\\pos({round(56*scale)},{round((title_top+index*size*1.25)*scale)})\\fs{round(size*scale)}}}"
                rows.append(f"Dialogue: 0,{stamp(intro_end)},{stamp(duration)},Title,,0,0,0,,{position}{line}")
    for caption in captions:
        rows.append(f"Dialogue: 2,{stamp(caption['start'])},{stamp(caption['end'])},Caption,,0,0,0,,{wrap(caption['text'], 49)}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
