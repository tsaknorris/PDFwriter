import fitz
import re

doc = fitz.open("/mnt/data/Downloads/Videogame_Industry_Does_Not_Exist.pdf")
page = doc[65]
td = page.get_text("dict")
raw_blocks = [b for b in td["blocks"] if b.get("type") == 0]

lines = []
for b in raw_blocks:
    for l in b.get("lines", []):
        lines.append(l)

lines.sort(key=lambda l: (round(l["bbox"][1], 1), round(l["bbox"][0], 1)))

# 1. Yhdistetään samalla korkeudella olevat rivit (esim. header ja sivunumero)
merged_lines = []
for l in lines:
    if merged_lines and abs(merged_lines[-1]["bbox"][1] - l["bbox"][1]) < 3.0:
        prev_l = merged_lines[-1]
        prev_l["spans"].extend(l.get("spans", []))
        b1 = prev_l["bbox"]
        b2 = l["bbox"]
        prev_l["bbox"] = (min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3]))
    else:
        merged_lines.append(dict(l))

def get_line_text(line):
    return "".join(s.get("text", "") for s in line.get("spans", []))

def get_line_font_info(line):
    spans = line.get("spans", [])
    if not spans:
        return "", 10.0, False
    s = spans[0]
    fname = s.get("font", "")
    fsize = s.get("size", 10.0)
    is_bold = bool(re.search(r"bold|semibold|heavy|black", fname, re.I))
    clean_fam = re.sub(r"^[A-Z]{6}\+", "", fname)
    clean_fam = re.sub(r"-(Regular|Medium|Bold|Italic|MediumItal|Semibold|Oblique).*", "", clean_fam)
    return clean_fam, fsize, is_bold

paragraphs = []
cur_para = []

for l in merged_lines:
    if not cur_para:
        cur_para.append(l)
        continue
    
    prev = cur_para[-1]
    dy = l["bbox"][1] - prev["bbox"][1]
    
    fam_prev, size_prev, bold_prev = get_line_font_info(prev)
    fam_cur, size_cur, bold_cur = get_line_font_info(l)
    
    prev_text = get_line_text(prev).strip()
    dx_left = abs(l["bbox"][0] - prev["bbox"][0])
    
    same_family = (fam_prev == fam_cur) or (not fam_prev or not fam_cur)
    same_size = abs(size_prev - size_cur) < 0.5
    same_weight = (bold_prev == bold_cur)
    
    leading_ok = (size_prev * 0.9 <= dy <= size_prev * 2.2)
    left_ok = (dx_left < 4.0) or (5.0 <= dx_left <= 25.0 and len(cur_para) == 1)
    
    prev_w = prev["bbox"][2] - prev["bbox"][0]
    ends_sentence = prev_text.endswith((".", "!", "?", ":", "”", "\""))
    is_short_end = prev_w < 250.0 and ends_sentence
    
    is_same_para = leading_ok and same_size and same_family and same_weight and left_ok and not is_short_end
    
    if is_same_para:
        cur_para.append(l)
    else:
        paragraphs.append(cur_para)
        cur_para = [l]

if cur_para:
    paragraphs.append(cur_para)

print(f"Correctly grouped into {len(paragraphs)} paragraphs!")
for i, p in enumerate(paragraphs):
    ptxt = " ".join(get_line_text(l).strip() for l in p)
    y_start = p[0]["bbox"][1]
    y_end = p[-1]["bbox"][3]
    print(f"Para {i} ({len(p)} lines, y={y_start:.1f}..{y_end:.1f}): {repr(ptxt[:65])}...")
