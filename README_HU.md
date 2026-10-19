# VitAnna – Render-előkészítés

Készült: 2026. október 19. • Verzió: 0.1.0 • Állapot: helyben tesztelhető előkészítő csomag.

Ez a Renderhez való programcsomag. A benne lévő program egy meglévő hanganyagból, 1–12 háttérképből és időzített magyar feliratból készít MP4-et. A csomag előkészítése során nem hoztunk létre Render-szolgáltatást és nem indítottunk fizetős API-hívást.

**Elsőként nyisd meg a `START_ITT.html` fájlt.** Abban a rövid bemutató is lejátszható.

## Mi van készen?

- Önálló Python/FFmpeg videó-összeállító: 1920×1080 vagy 1280×720, H.264, AAC, 25 kép/másodperc.
- Egyetlen háttérkép vagy több, egyenlő ideig megjelenő kép. A képváltás ebben a változatban egyszerű vágás; áttűnés és kameramozgás nincs.
- Magyar cím és felirat, az eredeti ElevenLabs karakter-időzítéséből, SRT-ből vagy kész időzített feliratblokkokból.
- MP3-hosszhoz igazított videó; befejezéskor hossz-, képméret- és kodekellenőrzés.
- Dockerfile és Render Blueprint; a program alapbeállítása `RUN_MODE=disabled`.
- Feladatfoglaló és eredmény-visszaküldő kliens a később elkészítendő VitAnna-összekötőhöz.
- Futtatható próbaadatok és 12 másodperces bemutató. A hang halk, mesterséges jelzőhang, nem ElevenLabs-felolvasás.

## Mi vár a meglévő VitAnna-fájlokra?

A VitAnna-oldali összekötő, a jelenlegi adatbázishoz illő feladatsor, az admin kapcsolói, a hírlevélgombok és a YouTube-közzététel bekötése. Ezekhez a `napi-audio-engine.php`, `napi-audio.php` és `articles-media.php` aktuális változata szükséges; a pontos útvonalakat és további függőségeket ezekből kell megállapítani.

A `docs/INTEGRACIOS_SZABALYOK.md` megőrzi az eddig egyeztetett működést. A `docs/BRIDGE_SZERZODES.md` a kliens által várt, még megvalósítandó szerveroldali kapcsolatot írja le. Ez a csomag nem tartalmaz működő VitAnna-adatbázisadaptert.

## Helyi próba Python és FFmpeg mellett

A csomag gyökérkönyvtárában:

```bash
python3 -m unittest discover -s tests -v
python3 app/renderer.py --manifest demo/job.json --output output/proba.mp4
```

A második parancs új videót és `proba.report.json` jelentést készít. Létező MP4-et nem ír felül. A mellékelt `demo/vitanna-demo.mp4` már elkészült.

Új, például ötperces próbaadatok:

```bash
python3 app/make_demo.py --output work/otperc --seconds 300
python3 app/renderer.py --manifest work/otperc/job.json --output output/otperc.mp4
```

Csak a Python szabványkönyvtára szükséges. Rendszerprogramok: FFmpeg (libx264, AAC, libass), FFprobe, Fontconfig és DejaVu Sans betűkészlet. A Dockerfile ezeket telepíti. A Docker-képet az előkészítés környezetében nem lehetett felépíteni; a teszt az itteni Python/FFmpeg környezetben futott. A tényleges Render-build külön telepítési ellenőrzés lesz.

## Docker-próba

```bash
docker build -t vitanna-video .
docker run --rm vitanna-video
docker run --rm -e RUN_MODE=check vitanna-video
```

Az első futás `disabled`, a második `check_ok` üzenetet ad. Éles kapcsolati adat nélkül sem hírlevelet, sem videót nem publikál. A kész Docker-képben az `/app` a program, `/work` írható munkakönyvtár; a folyamat nem rendszergazdaként fut.

## Render-előkészítés

1. A forrás egy saját, lehetőleg privát Git-tárolóba kerül. A `Dockerfile` és a `render.yaml` a tároló gyökerében legyen. A szolgáltatás létrehozását az összekötő elkészülte után célszerű végezni.
2. A Render-kapcsolat a ChatGPT-ből elérhető külön Render-bővítménnyel is előkészíthető. A kapcsolat önmagában nem bizonyít telepítést. Alternatív telepítési út a Render felületén egy új Blueprint, a tároló kiválasztásával.
3. Beállítás: `Cron Job`, Docker, Frankfurt, `1c-2g` (1 CPU / 2 GB RAM). Automatikus újratelepítés kikapcsolva. A tényleges csomagelérhetőséget és árat létrehozáskor ellenőrizni kell.
4. A program `disabled` állapotban marad, amíg a VitAnna-kapcsolat nincs kész. **A fizetős Render-szolgáltatás létrehozása már számlázást indíthat; a program kikapcsolt módja nem számlázási szüneteltetés.**
5. Először `RUN_MODE=check`, kézi próbaindítás. Utána az összekötővel egy nem publikált tesztcikk. Végül `RUN_MODE=queue`, miután a szerveroldali foglalás, leállítás, feltöltés és duplikációvédelem is igazolt.

### Környezeti változók

| Név | Érték / cél |
| --- | --- |
| `RUN_MODE` | `disabled` / `check` / `queue`; alapból `disabled` |
| `TZ` | `Europe/Budapest` |
| `VITANNA_BRIDGE_URL` | A később telepített, saját VitAnna HTTPS-összekötő teljes címe, query string nélkül |
| `VITANNA_WORKER_TOKEN` | Külön, legalább 32 karakteres véletlen titok a két rendszer összekötéséhez |

A worker-token nem az OpenAI- vagy ElevenLabs-kulcs. Ebben a videó-összeállítóban egyik ilyen API-kulcs sem szükséges. Titkot a Render környezeti változói között kell megadni, a forrásba nem kerülhet.

### Miért 15 percenkénti ellenőrzés?

A 22:00-kor induló cikk/hang folyamat a VitAnna rendszerében marad. A Render legfeljebb 15 percenként kér egy már előkészített videófeladatot. Ha nincs kész MP3 és felirat, nincs feladat és a program kilép. Ez kezeli a hangkészítés változó idejét és a későbbi kézi kéréseket is. Egy futás legfeljebb egy videót készít.

A Render cron UTC időzítést használ; az összekötő dönti el, melyik cikk mikor jogosult feldolgozásra és megjelenésre, `Europe/Budapest` szerint. A 15 perces ellenőrzés nem függ a téli/nyári időszámítás váltásától. A Render kézi „Trigger Run” gombját már futó videókészítés közben ne indítsd: a Render dokumentációja szerint az aktív futás ilyenkor megszakad.

### Költség

A 2026. október 19-én ellenőrzött díj: `1c-2g` cron 0,00058 USD / futási perc, szolgáltatásonként legalább havi 1 USD. A számlázás az aktív futásra történik. Az üres ellenőrzések, videókészítések és feltöltések mind számítanak. Például 30 × 20 feldolgozási perc 0,348 USD számítási díj, így az 1 USD minimum érvényesülne; ez önmagában nem teljes havi számla vagy teljes rendszerköltség. Adók, adatforgalom és esetleges más Render-erőforrások külön jelentkezhetnek. A valódi használatot a Render naplója és számlázása mutatja majd.

Az ElevenLabs hangkészítése külön tétel. A worker a már meglevő MP3-at használja, nem készíti el újra. A képgenerálás és a YouTube-engedélyezés szintén külön folyamat.

## Helyi feladatleíró

Lásd `demo/job.json`. A `schema_version` értéke 1. A fájlok relatív útvonalak, a JSON könyvtárán belül. A szükséges mezők:

- `audio`: `{ "path": "hang.mp3" }`
- `images`: 1–12 `{ "path": "kep.jpg" }` objektum
- `title`: legfeljebb 180 karakter
- `require_captions`: alapból `true`
- egyetlen feliratforrás: `captions`, `srt` vagy `elevenlabs_alignment`

Példák alternatív feliratforrásokra:

```json
{ "srt": { "path": "felirat.srt" } }
```

```json
{ "elevenlabs_alignment": { "path": "idobelyegek.json" } }
```

Az ElevenLabs-fájl tartalmazhat `alignment` vagy `normalized_alignment` objektumot, illetve közvetlenül a `characters`, `character_start_times_seconds`, `character_end_times_seconds` listákat. Az időbélyegeknek ugyanahhoz a teljes MP3-hoz kell tartozniuk. Több TTS-részlet összefűzésekor a későbbi adapternek az időbélyegeket is el kell tolnia. Időzítés nélküli cikkből nem találunk ki feliratszinkront.

Az MP3 legfeljebb 15 perces és 100 MiB, egy kép legfeljebb 20 MiB és 40 megapixel, a kész MP4 legfeljebb 500 MiB lehet. A feliratos összeállításra 30 perc végrehajtási időkorlát van. A teljes hálózati futásnál a VitAnna-adapter 2 órás foglalást ad; a szervernek ezt verzióhoz és tokenhez kötve kell kezelnie.

## Ellenőrzés és támogatott kör

Lásd `docs/ELLENORZES.json`. A helyi teszt nem helyettesíti a Render buildet vagy a VitAnna/YouTube kapcsolat próbáját. A kész fájlok a Render ideiglenes lemezén csak átmenetileg maradnak; a kliens visszaigazoltan feltölti az MP4-et a majdani VitAnna-összekötőnek, és csak utána tekinti késznek.

## Hivatalos források

- Render cron működés és számlázás: https://render.com/docs/cronjobs
- Render árak: https://render.com/pricing
- Blueprint mezők és csomagnevek: https://render.com/docs/blueprint-spec
- Docker: https://render.com/docs/docker
- FFmpeg feliratok: https://ffmpeg.org/ffmpeg-filters.html#subtitles-1
