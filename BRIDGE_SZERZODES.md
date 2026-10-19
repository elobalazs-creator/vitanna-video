# A későbbi VitAnna-összekötő szerződése

Az `app/worker.py` ezt a felületet várja. Az összekötő még nincs telepítve és nincs benne ebben a csomagban: a jelenlegi PHP-fájlok és adatbázis ismeretében kell megírni.

## Hitelesítés és tárhely

Egy konfigurált HTTPS-végpont, query string nélkül. Minden kérés `Authorization: Bearer <VITANNA_WORKER_TOKEN>` fejlécet kap. A PHP-oldal időálló összehasonlítással ellenőrizze a legalább 32 karakteres véletlen titkot. A tokent ne naplózza és ne adja át URL-ben.

A média-URL-ek az összekötővel azonos HTTPS-hoston és porton legyenek. A worker ezekhez is ugyanazt a Bearer fejlécet adja. Nincs automatikus átirányítás. Ha a tárhely `www`-s és `www` nélküli címei között átirányítás van, már a végleges hostot kell megadni. A tárolt médiához védett letöltési végpontot kell használni; a másnapi anyagot ne tegyük nyilvánossá a worker kedvéért.

## 1. Foglalás – POST JSON

```json
{"action":"claim","worker_id":"egy-futashoz-tartozo-uuid","lease_seconds":7200}
```

A szerver csak kész MP3-mal és a kért felirattal rendelkező, esedékes, engedélyezett, még nem kész feladatot adhat ki. A választ és a foglalást tranzakcióban kell létrehozni. Szerveroldalon érvényesüljön a magyar idő, a globális kapcsoló, a cikkenkénti kihagyás és a próbák felső határa. Üres sor esetén HTTP 200:

```json
{"job":null}
```

Feladat esetén HTTP 200:

```json
{
  "job": {
    "job_id": "cikk-123-v1",
    "revision": 1,
    "lease_token": "kulon-veletlen-32-vagy-tobb-karakteres-foglalasi-token",
    "manifest": {
      "schema_version": 1,
      "title": "Az útravaló címe",
      "audio": {"url":"https://vitanna.example/vedett/hang","sha256":"a-valos-fajl-64-karakteres-kisbetus-sha256-erteke"},
      "images": [{"url":"https://vitanna.example/vedett/kep","sha256":"a-valos-fajl-64-karakteres-kisbetus-sha256-erteke"}],
      "elevenlabs_alignment": {"url":"https://vitanna.example/vedett/idozites","sha256":"a-valos-fajl-64-karakteres-kisbetus-sha256-erteke"},
      "require_captions": true,
      "video": {"width":1920,"height":1080}
    }
  }
}
```

Az `.example` domainek és a hash-szövegek szemléltető helykitöltők, nem működő beállítások. A feladat nem adhat helyi fájlutat. A `captions` közvetlen listája vagy egy `srt` fájl is használható az ElevenLabs-időzítés helyett; egyszerre pontosan egy feliratforrás.

A lease-token csak ASCII betűt, számot, aláhúzást vagy kötőjelet tartalmazhat, 32–160 karakter. A job_id 1–80 ilyen karakter. A revision pozitív egész szám. A letöltések maximális méretét a README írja le.

## 2. Kész MP4 átvétele – POST bináris

A konfigurált végpontnak `?action=complete&job_id=<azonosito>&revision=<verzio>` paraméterekkel:

- `Content-Type: video/mp4`
- `Content-Length`: teljes fájlméret
- `Authorization`: a worker-token
- `X-Vitanna-Lease`: az adott foglalás tokenje
- `X-Content-SHA256`: a teljes MP4 ellenőrzőösszege

A törzs maga az MP4, nem multipart és nem Base64. PHP-ban folyamatosan olvasandó a `php://input`; a teljes fájlt ne töltsük memóriába. A célfájl nevét a szerver válassza, a kérés ne adjon fájlutat. Méretkorlát: 500 MiB. A tényleges Forpsi-kérésméret és időkorlát külön ellenőrizendő.

Szerveroldalon: hitelesítés, aktuális revision és lease ellenőrzése, privát ideiglenes fájlba írás, fájlméret/SHA-256 ellenőrzés, alap MP4-konténerellenőrzés, atomi véglegesítés. Ellenőrizni kell azt is, hogy időközben nem kapcsolták-e ki vagy nem jelölték-e kihagyásra az adott feladatot. Eltérő/stale verzió vagy kihagyott feladat: HTTP 409, a kész eredmény nem aktiválható.

Sikeres válasz:

```json
{"ok":true,"job_id":"cikk-123-v1","status":"ready","sha256":"a-teljes-mp4-tenyleges-64-karakteres-hash-erteke"}
```

A `ready` a videófájl átvételét jelenti, nem YouTube-publikálást. Azonos job_id, revision és hash ismételt beérkezése ugyanilyen sikeres választ adjon, új fájl/publikálás létrehozása nélkül. Az átvétel után megszakadt hálózati kapcsolat miatt érkező későbbi hibajelzés nem írhatja felül a már kész állapotot.

## 3. Hibajelzés vagy kihagyás – POST JSON

```json
{"action":"failed","job_id":"cikk-123-v1","revision":1,"lease_token":"a-foglalasi-token","error_code":"ValueError"}
```

A szerver a még aktív és egyező foglalást jelölje hibásnak, kezelje a próbák számát és a következő engedélyezett időpontot. Soha ne állítsa vissza a kész vagy másik verzióval feldolgozott feladatot. Elveszett kapcsolat vagy megszakadt Render-futás esetén a foglalás lejárta után legyen visszavehető a feladat, a próbálkozásszám emelésével.

`action: skipped` esetén azonos mezők kellenek az `error_code` kivételével. Válasz: `{"ok":true}`. A claim általában eleve ne adjon ki kihagyott feladatot; a kliens ezt védelemként kezeli.

## Publikálás

A Render-kliens nem kap YouTube-, ElevenLabs- vagy OpenAI-kulcsot, és nem publikál önállóan. A VitAnna-oldali, külön engedélyezett lépés a `ready` videót a közzétételi mód és időpont szerint kezelheti. YouTube-link csak a sikeres, visszaellenőrzött publikálás után kerülhet a weboldalra vagy a következő hírlevélbe.
