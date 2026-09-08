import fitz

doc = fitz.open()

# SIVU 1: Moderni raportti / esite
page1 = doc.new_page(width=595.3, height=841.9)  # A4

# Yläpalkki (koristeellinen grafiikka)
page1.draw_rect(fitz.Rect(0, 0, 595.3, 8), color=None, fill=(0.16, 0.50, 0.73))
page1.draw_rect(fitz.Rect(54, 40, 541.3, 42), color=(0.85, 0.85, 0.85), fill=(0.85, 0.85, 0.85))

# Pääotsikko
page1.insert_text((54, 80), "PDFwriter — Acrobat-tason Offline PDF-Editori", fontname="hebo", fontsize=20, color=(0.12, 0.23, 0.35))
# Alaotsikko
page1.insert_text((54, 102), "Täysiverinen typografian, kappaleiden ja vektoriasettelun muokkausympäristö", fontname="heit", fontsize=11, color=(0.45, 0.50, 0.55))

# Väliotsikko 1
page1.insert_text((54, 140), "1. Älykäs monirivinen kappaleenhallinta", fontname="hebo", fontsize=13, color=(0.16, 0.50, 0.73))

# Kappale 1 (Leipäteksti, täysi palsta)
p1_lines = [
    "Tämä dokumentti havainnollistaa PDFwriterin uutta älykästä kappaletilaa. Toisin kuin perinteiset",
    "työkalut, jotka pilkkovat tekstin yksittäisiksi irtonaisiksi riveille, PDFwriter tunnistaa kirjan ja artikkelin",
    "kappaleet yhtenäisinä kokonaisuuksina. Voit muokata tekstiä sujuvasti kuin tekstinkäsittelyohjelmassa,",
    "ilman että rivinvaihdot rikkovat typografista asettelua tai perusviivoja."
]
y = 162
for line in p1_lines:
    page1.insert_text((54, y), line, fontname="helv", fontsize=10, color=(0.15, 0.15, 0.15))
    y += 15

# Väliotsikko 2
page1.insert_text((54, 240), "2. Interaktiivinen tekstilaatikon koon säätö", fontname="hebo", fontsize=13, color=(0.16, 0.50, 0.73))

# Kappale 2
p2_lines = [
    "Kun valitset minkä tahansa kappaleen tai otsikon, voit tarttua hiirellä suoraan tekstilaatikon reunoihin",
    "ja kulmiin leventääksesi sitä. Laatikon leveyttä voi säätää myös suoraan sivupaneelista pisteen tarkkuudella",
    "tai painamalla painiketta Sovita palstaan. Tämä takaa, että pitkätkin otsikot mahtuvat siististi yhdelle riville",
    "eivätkä rivity ennenaikaisesti toiselle riville."
]
y = 262
for line in p2_lines:
    page1.insert_text((54, y), line, fontname="helv", fontsize=10, color=(0.15, 0.15, 0.15))
    y += 15

# Huomiolaatikko
box_rect = fitz.Rect(54, 340, 541.3, 420)
page1.draw_rect(box_rect, color=(0.70, 0.85, 0.95), fill=(0.94, 0.97, 1.0))
page1.insert_text((70, 365), "Vinkki tehokkaaseen muokkaukseen:", fontname="hebo", fontsize=11, color=(0.10, 0.35, 0.55))
page1.insert_text((70, 385), "• Voit vaihtaa Kappaletilan ja Rivitilan välillä ylävalikosta tai pikanäppäimillä.", fontname="helv", fontsize=9.5, color=(0.2, 0.2, 0.2))
page1.insert_text((70, 402), "• Pikanäppäin Ctrl + Enter hyväksyy tekstin in-place -muutoksen välittömästi.", fontname="helv", fontsize=9.5, color=(0.2, 0.2, 0.2))

# Alatunniste
page1.insert_text((54, 800), "PDFwriter Offline Architecture — Sivu 1 / 2", fontname="helv", fontsize=9, color=(0.6, 0.6, 0.6))

# SIVU 2: Typografia ja lisäominaisuudet
page2 = doc.new_page(width=595.3, height=841.9)
page2.draw_rect(fitz.Rect(0, 0, 595.3, 8), color=None, fill=(0.16, 0.50, 0.73))

page2.insert_text((54, 60), "Typografia, Kirjasimet ja Laadunvarmistus", fontname="hebo", fontsize=18, color=(0.12, 0.23, 0.35))
page2.insert_text((54, 80), "Acrobat-tason tarkkuus ja turvallinen offline-käyttö", fontname="heit", fontsize=11, color=(0.45, 0.50, 0.55))

page2.insert_text((54, 120), "Täysi kirjasintuki ja avoimet vastineet", fontname="hebo", fontsize=13, color=(0.16, 0.50, 0.73))

p3_lines = [
    "Dokumenttien kirjasimet tunnistetaan automaattisesti. Jos PDF sisältää osittain upotetun leikkauksen",
    "(subset) tai järjestelmästä puuttuvan fontin, sovellus ilmoittaa siitä selkeästi yläpalkissa.",
    "Voit tuoda oman fonttitiedostosi (.ttf / .otf) koneeltasi tai ladata luvallasi avoimen vastineen verkosta.",
    "Kaikki vektorit ja taustakuvat säilyvät täysin koskemattomina jokaisessa muokkauksessa."
]
y = 142
for line in p3_lines:
    page2.insert_text((54, y), line, fontname="helv", fontsize=10, color=(0.15, 0.15, 0.15))
    y += 15

# Alatunniste
page2.insert_text((54, 800), "PDFwriter Offline Architecture — Sivu 2 / 2", fontname="helv", fontsize=9, color=(0.6, 0.6, 0.6))

target_pdf = "/home/mika/Desktop/diudiu/PDFwriter/sample_document.pdf"
doc.save(target_pdf)
doc.close()
print(f"Uusi hieno sample_document.pdf luotu onnistuneesti: {target_pdf}")
