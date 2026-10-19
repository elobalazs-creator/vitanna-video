# A VitAnna napi folyamatának egyeztetett működése

Állapot: követelmények, 2026. október 19. Ezekhez a jelenlegi PHP-modulok alapján készül a bekötés.

## Cikk és hang

- Este 22:00-kor, magyar idő szerint a rendszer bekéri/előveszi a másnapi útravalót.
- Minden útravalóból ElevenLabs MP3 készüljön. A kész MP3 a VitAnna tárhelyén marad.
- A hírlevél küldése előtt a rendszer ellenőrizze a teljes MP3 sikeres elkészültét és elérhetőségét. Hiba esetén jelezzen és ütemezzen korlátozott újrapróbálkozást; hiányzó hanghoz ne küldjön működőnek mutatott gombot.
- A „Meghallgatom” gomb a VitAnna saját, mobilra igazított lejátszóoldalára vezessen. Háttérkép, cím, dátum, hangvezérlők és olvasható cikkszöveg jelenjen meg. A háttérképes MP3-lejátszóhoz nem kell videót gyártani.
- Az MP3 egyszer készül el, és ugyanazt használja a saját lejátszó és a videó. A videóhiba nem indít automatikusan új, fizetős TTS-generálást.
- Október végéig a cikkek a felhasználó szerint készen vannak. A 2026. november 1-jétől megjelenő új cikkek teljes felolvasott szövege kb. 4000–4300 karakter, célértéke 4200 karakter, szóközökkel és felolvasott címmel/kerettel együtt. Ez kb. ötperces hang célja, nem garantált 5:00. A próba referenciája 6786 karakter / kb. 8 perc.

## Videó

- Automatikus videókészítés alapból engedélyezve; az adminból általánosan szüneteltethető.
- Cikkenként „Videó kihagyása” kapcsoló. Egy kihagyás nem tiltja le a következő napi videót.
- „Videó készítése” kézi gomb a korábban kihagyott anyaghoz.
- Külön kapcsoló/állapot az elkészítésre és a közzétételre. A javasolt alap: automatikus előkészítés, kézi közzétételi jóváhagyás. Teljes automatikus közzétételt csak kifejezetten kiválasztott adminmódban szabad bekapcsolni.
- A videó kész MP3-ból, képből/képekből és a hanghoz tartozó valódi felirat-időzítésből készül.
- A hírlevélnek nem kell a videóra várnia. A „Megnézem YouTube-on” külön gomb csak már ténylegesen közzétett, érvényes YouTube-link esetén kerüljön a kiküldött levélbe. Később készülő videó linkje a weboldalon megjelenhet; a már kiküldött levél törzse utólag nem módosul.
- Az MP3 és videó megjelenés előtti hozzáférési szabályait a webes modul kezelje: ne kerüljenek ki idő előtt a másnapi cikkek vagy médiafájlok.

## Tartós állapot és ismételt futás

- A cikk-, hang- és videóállapot külön mező legyen. Egy videóhiba ne változtassa sikertelenre a kész MP3-at.
- Cikkazonosító + hang/kép/felirat-revízió alapján legfeljebb egy aktuális videófeladat készüljön.
- A feldolgozás közben megváltozott vagy kihagyott cikk régi videója ne váljon aktívvá.
- Foglalás és lejárati idő a VitAnna adatbázisában; a Render helyi lemeze nem állapottároló.
- A kész eredmény átvétele legyen ismételhető azonos ellenőrzőösszeggel, dupla feltöltésből vagy időtúllépésből ne keletkezzen második publikálás.
- Legfeljebb három automatikus hibapróba után adminban látható hiba és kézi újraindítás; a pontos időközök a meglévő időzítőhöz igazítandók.

## Függőben lévő ellenőrzések

PHP-fájlok és séma; meglévő időzítő; ElevenLabs válasz és tárolt időbélyegek; hangfájlok helye és jogosultsága; levélküldés pillanata; YouTube OAuth/kapcsolat és feltöltési lehetőség; hírlevél valódi linkjei; Render build és éles futási költség. Ezek egyike sem tekintendő ebben a csomagban már élesítettnek.
