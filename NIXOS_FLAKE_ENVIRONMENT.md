# NixOS & Flake.nix Ympäristöohje (PDFwriter)

Tämä projekti toimii **NixOS**-käyttöjärjestelmässä.

## Ympäristön Rakenne
- **Emohakemisto:** `/home/mika/Desktop/diudiu`
- **Flake-määrittely:** `/home/mika/Desktop/diudiu/flake.nix` ja `flake.lock`
- **Virtuaaliympäristö:** `/home/mika/Desktop/diudiu/.venv`
- **Python-tulkki:** `/home/mika/Desktop/diudiu/.venv/bin/python` (Python 3.11.14)
- **Valmiiksi asennetut paketit:**
  * `PyMuPDF` (fitz 1.27.2.3)
  * `PyQt6` (Qt 6.x GUI ja XCB/Wayland -rajapinnat)
  * `fontTools` (4.62.1 fonttien ja glyyfitaulukoiden käsittelyyn)
  * `Pillow` (PIL 12.1.1)
  * `fontconfig`, `freetype`, `harfbuzz`
- **Kirjastopolut (LD_LIBRARY_PATH):**
  Asetetaan automaattisesti lataamalla direnv flake-profiili:
  `source /home/mika/Desktop/diudiu/.direnv/flake-profile-*.rc`

## Komentojen ja sovelluksen ajaminen:
Kaikki ajot ja testit tulee suorittaa joko:
1. Käyttämällä mukana toimitettavaa käynnistysskriptiä: `./run.sh`
2. Tai suoraan komentoriviltä:
   ```bash
   bash -c 'source /home/mika/Desktop/diudiu/.direnv/flake-profile-*.rc 2>/dev/null; /home/mika/Desktop/diudiu/.venv/bin/python <skripti.py>'
   ```
3. Vaihtoehtoisesti `nix develop /home/mika/Desktop/diudiu --command ...`

## Säännöt:
- Älä koskaan yritä kutsua globaalia `python` tai `python3` -komentoa suoraan ilman ympäristöä.
- Älä tee verkkokutsuja (`QT_NO_NETWORK=1`, 100 % offline-toiminta).
- Kaikki fontit ja riippuvuudet ratkaistaan paikallisesti.
