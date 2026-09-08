# PDFwriter - Acrobat-tason Offline PDF-Editori (Linux / NixOS)

Itsenäinen, 100 % offline-tilassa toimiva PDF-tekstieditori Linuxille. Sovellus kykenee muokkaamaan olemassa olevaa tekstiä säilyttäen alkuperäiset fontit, asettelut, värit ja metriikat identtisinä Adoben Acrobat Pro -standardin mukaisesti.

---

## Gauntlet Loop -arkkitehtuuri ja sokeat kriitikot

Jokainen komponentti on toteutettu ja auditoitu Gauntlet Loop -silmukalla:

| Erikoisalue | Rakennekomponentti | Sokea kriitikko & Laaturima | Toteutettu ratkaisu |
| :--- | :--- | :--- | :--- |
| **Kirjasimet & Enkoodaus** | `FontconfigResolver`, `FontMatchResult` | Hylkää tofu/laatikot ja oletukset. Vaatii todisteen glyyfikattavuudesta. | Purkaa `[A-Z]{6}+` -subsetit, analysoi upotetun kirjasimen `cmap`-taulun `fontTools`-kirjastolla. Mikäli merkkejä puuttuu, hakee Linuxin Fontconfig (`fc-match`) -järjestelmästä täyden vastaavan lokaalin TTF/OTF-tiedoston. |
| **Asettelu & Geometria** | `LayoutEngine`, `OverflowReport` | Vaatii alle 0.1 pt perusviivapoikkeamaa. Hylkää ylivalunnat ilman varoitusta. Säilyttää grafiikkatilan. | Kohdistaa tekstin kastepisteen suoraan `span["origin"]` -perusviivalle (mitattu drift: 0.0000 pt). Laskee reaaliaikaisen leveyden ($\Delta$ pt / %) ja tarjoaa sovitusstrategiat (Natural, Auto-Fit, Reflow). Vektoriredaktio (`images=0, graphics=0`) säilyttää taustagrafiikat. |
| **PDF-Rakenne & Eristys** | `PDFDocumentModel`, `GauntletValidator` | 100 % offline ilman verkkoa tai telemetriaa. Virheetön XRef-rakenne. | Pakotettu offline-tila (`QT_NO_NETWORK=1`). Inkrementaalinen ja deflatoitu tallennus (`garbage=3, clean=True, deflate=True`). Sisäänrakennettu monivaiheinen auditointi (`Ctrl+G`). |

---

## NixOS & Flake -ympäristö

Tämä järjestelmä toimii NixOS-ympäristössä hyödyntäen emohakemiston `/home/mika/Desktop/diudiu/flake.nix` ja virtuaaliympäristön `/home/mika/Desktop/diudiu/.venv` kirjastoja.

- **Käynnistys yhdellä komennolla:**
  ```bash
  ./run.sh [tiedosto.pdf]
  ```
- **Käynnistys komentoriviltä:**
  ```bash
  bash -c 'source /home/mika/Desktop/diudiu/.direnv/flake-profile-*.rc 2>/dev/null; export QT_NO_NETWORK=1; /home/mika/Desktop/diudiu/.venv/bin/python app.py sample_document.pdf'
  ```

---

## Ominaisuudet

1. **Interaktiivinen HiDPI-piirtoalusta:**
   - Sulava zoomaus (`Ctrl + rulla`, `Ctrl++`, `Ctrl+-`, `Ctrl+0`).
   - Visuaalinen kursorin hover-tunnistus ja korostus.
   - Vihreä **perusviivaindikaattori** näyttää tarkan baseline-kohdistuksen reaaliajassa.
2. **In-Place Tekstieditori:**
   - Valitse mikä tahansa teksti klikkaamalla sitä sivulla.
   - Reaaliaikainen pituus- ja ylivaluntaseuranta (Live Overflow Badge: Vihreä, Keltainen, Punainen).
   - Fonttikoon hienosäätö 0.1 pt:n askeleella.
   - Värivalitsin ja alkuperäisen RGB-värin automaattinen tunnistus.
   - Kolme sovitusstrategiaa:
     * **Luonnollinen (Natural):** Säilyttää kirjasinkoon sellaisenaan.
     * **Automaattinen sovitus (Auto-Fit):** Skaalaa fonttikokoa hienovaraisesti mahtumaan vanhaan laatikkoon.
     * **Rivin juoksutus (Reflow):** Huomioi rivin seuraavat elementit.
3. **Syvätarkastelija (Inspector Panel):**
   - PDF-fonttisanakirjan analyysi (subset-status, CMap, upotetun kirjasimen purku).
   - Paikallisen järjestelmäfontin polku ja perhe.
   - Tarkat koordinaatit (`origin`, `bbox`, `size`).
4. **Monisivuinen navigointi ja täydet sivumuokkaukset:**
   - **Sivupysyvyys:** Muokkausten tekeminen pitää näkymän aina kyseisellä sivulla ilman hyppyjä.
   - **Drag & Drop -siirto:** Järjestä sivut uudelleen raahaamalla pikkukuvia hiirellä.
   - **Toisen PDF:n liittäminen (Insert PDF):** Pudota ulkoinen `.pdf`-tiedosto tiedostonhallinnasta suoraan sivupalkkiin tai valitse *Sivu -> Lisää sivuja tiedostosta...* (`Ctrl+Shift+I`).
   - **Kontekstivalikko (hiiren oikea painike sivupalkissa):**
     * 📄 *Lisää sivuja toisesta PDF-tiedostosta tähän väliin...*
     * ➕ *Lisää tyhjä sivu tähän* (`Ctrl+Shift+N`)
     * 📋 *Monista tämä sivu* (`Ctrl+Shift+D`)
     * 🔄 *Kierrä 90° myötäpäivään* (`Ctrl+R`)
     * 🗑️ *Poista sivu* (`Ctrl+Delete`)
5. **Täysi Undo / Redo -pino:**
   - Kaikki toimenpiteet (tekstinmuokkaukset, sivusiirrot, PDF-liitokset, poistot, kierrot) voi kumota (`Ctrl+Z`) ja tehdä uudelleen (`Ctrl+Y`).
6. **Gauntlet Loop -laadunvarmistus:**
   - Aja milloin tahansa painamalla `Ctrl+G` tai työkalupalkista.
   - Näyttää selkeän raportin kaikista kolmesta sokeasta kriitikosta.

---

## Testit

Kaikki 10 yksikkö- ja kierrostestiä suoritetaan komennolla:
```bash
bash -c 'source /home/mika/Desktop/diudiu/.direnv/flake-profile-*.rc 2>/dev/null; export QT_NO_NETWORK=1; /home/mika/Desktop/diudiu/.venv/bin/python -m unittest discover -s tests'
```
# PDFwriter
