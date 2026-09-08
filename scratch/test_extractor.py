import fitz
import re

def extract_paragraphs_from_page(page, page_idx):
    text_dict = page.get_text("dict")
    raw_blocks = [b for b in text_dict.get("blocks", []) if b.get("type") == 0]
    if not raw_blocks:
        return []

    # 1. Kerätään kaikki rivit
    lines = []
    for b in raw_blocks:
        for l in b.get("lines", []):
            spans = [s for s in l.get("spans", []) if s.get("text", "").strip()]
            if spans:
                lines.append(l)

    if not lines:
        return []

    lines.sort(key=lambda l: (round(l["bbox"][1], 1), round(l["bbox"][0], 1)))

    # 2. Yhdistetään samalla perusviivalla/korkeudella olevat rivinjaksot
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
            return "", 10.0, False, 0
        s = spans[0]
        fname = s.get("font", "")
        fsize = s.get("size", 10.0)
        fcolor = s.get("color", 0)
        is_bold = bool(re.search(r"bold|semibold|heavy|black", fname, re.I))
        clean_fam = re.sub(r"^[A-Z]{6}\+", "", fname)
        clean_fam = re.sub(r"-(Regular|Medium|Bold|Italic|MediumItal|Semibold|Oblique).*", "", clean_fam)
        return clean_fam, fsize, is_bold, fcolor

    # Selvitetään sivun palstan oikea reuna (maksimi x1 leipätekstiriveille)
    page_max_x1 = max(l["bbox"][2] for l in merged_lines)
    page_min_x0 = min(l["bbox"][0] for l in merged_lines)
    typical_line_w = max(l["bbox"][2] - l["bbox"][0] for l in merged_lines)

    paragraphs = []
    cur_para = []

    for l in merged_lines:
        if not cur_para:
            cur_para.append(l)
            continue
        
        prev = cur_para[-1]
        dy = l["bbox"][1] - prev["bbox"][1]
        
        fam_prev, size_prev, bold_prev, color_prev = get_line_font_info(prev)
        fam_cur, size_cur, bold_cur, color_cur = get_line_font_info(l)
        
        prev_text = get_line_text(prev).strip()
        dx_left = abs(l["bbox"][0] - prev["bbox"][0])
        
        same_family = (fam_prev == fam_cur) or (not fam_prev or not fam_cur)
        same_size = abs(size_prev - size_cur) < 0.8
        same_weight = (bold_prev == bold_cur)
        same_color = (color_prev == color_cur)
        
        # Riviväli (leading) toleranssi: tyypillisesti 1.0 - 1.8 kertaa fonttikoko
        leading_ok = (size_prev * 0.75 <= dy <= size_prev * 2.2)
        
        # Linjaus vasempaan reunaan tai kappaleen aloitussisennys
        left_ok = (dx_left < 4.0) or (5.0 <= dx_left <= 30.0 and len(cur_para) == 1)
        
        # Jos edellinen rivi loppui selvästi ennen palstan reunaa ja virkkeen lopetusmerkkiin, kappale päättyi
        prev_w = prev["bbox"][2] - prev["bbox"][0]
        ends_sentence = prev_text.endswith((".", "!", "?", ":", "”", "\""))
        is_short_end = (prev_w < typical_line_w * 0.82) and ends_sentence
        
        is_same_para = leading_ok and same_size and same_family and same_weight and same_color and left_ok and not is_short_end
        
        if is_same_para:
            cur_para.append(l)
        else:
            paragraphs.append(cur_para)
            cur_para = [l]

    if cur_para:
        paragraphs.append(cur_para)

    # Muodostetaan rikastetut lohkot
    blocks = []
    for p_idx, lines_in_p in enumerate(paragraphs):
        all_spans = []
        for l in lines_in_p:
            all_spans.extend(l.get("spans", []))

        prim_font, prim_size, prim_bold, prim_color = get_line_font_info(lines_in_p[0])
        
        # Bounding box
        min_x = min(l["bbox"][0] for l in lines_in_p)
        min_y = min(l["bbox"][1] for l in lines_in_p)
        max_x = max(l["bbox"][2] for l in lines_in_p)
        max_y = max(l["bbox"][3] for l in lines_in_p)
        bbox = (min_x, min_y, max_x, max_y)

        # Baselines
        line_origins = []
        line_bboxes = []
        line_spans = []
        for line in lines_in_p:
            line_bboxes.append(line.get("bbox", [0, 0, 0, 0]))
            line_spans.append([dict(s) for s in line.get("spans", [])])
            l_orig = None
            for s in line.get("spans", []):
                if s.get("origin"):
                    l_orig = (float(s["origin"][0]), float(s["origin"][1]))
                    break
            if not l_orig:
                l_box = line.get("bbox", [0, 0, 0, 0])
                l_orig = (float(l_box[0]), float(l_box[1] + prim_size * 0.85))
            line_origins.append(l_orig)

        first_origin = fitz.Point(line_origins[0][0], line_origins[0][1])

        line_leadings = []
        if len(line_origins) > 1:
            for idx in range(len(line_origins) - 1):
                dy = line_origins[idx + 1][1] - line_origins[idx][1]
                line_leadings.append(dy)
            leading = sum(line_leadings) / len(line_leadings)
        else:
            line_h = lines_in_p[0].get("bbox", [0, 0, 0, 0])[3] - lines_in_p[0].get("bbox", [0, 0, 0, 0])[1]
            leading = line_h if line_h > 5.0 else prim_size * 1.35

        # Tekstin yhdistäminen
        text_parts = []
        for l_idx, line in enumerate(lines_in_p):
            line_str = "".join(s.get("text", "") for s in line.get("spans", []))
            if l_idx == len(lines_in_p) - 1:
                text_parts.append(line_str)
                break
            if line_str.endswith("-"):
                text_parts.append(line_str[:-1])
            elif line_str.endswith(" "):
                text_parts.append(line_str)
            else:
                text_parts.append(line_str + " ")

        full_text = "".join(text_parts)
        max_w = max_x - first_origin.x
        if max_w < 20.0:
            max_w = max(50.0, max_x - min_x)

        # Palstakohtainen tila
        avail_w = max(max_w, page_max_x1 - first_origin.x)

        block_data = {
            "block_id": f"p{page_idx}_para{p_idx}",
            "page_idx": page_idx,
            "type": 0,
            "bbox": bbox,
            "text": full_text,
            "font": lines_in_p[0]["spans"][0].get("font", "Helvetica") if lines_in_p[0].get("spans") else "Helvetica",
            "size": prim_size,
            "color": prim_color,
            "flags": lines_in_p[0]["spans"][0].get("flags", 0) if lines_in_p[0].get("spans") else 0,
            "line_count": len(lines_in_p),
            "first_origin": (first_origin.x, first_origin.y),
            "line_origins": line_origins,
            "line_leadings": line_leadings,
            "line_bboxes": line_bboxes,
            "line_spans": line_spans,
            "leading": leading,
            "max_width": max_w,
            "available_width": avail_w,
            "original_lines": [
                "".join(s.get("text", "") for s in l.get("spans", []))
                for l in lines_in_p
            ]
        }
        blocks.append(block_data)

    return blocks


doc = fitz.open("/mnt/data/Downloads/Videogame_Industry_Does_Not_Exist.pdf")
print("=== Testing on Page 66 (index 65) ===")
p65_blocks = extract_paragraphs_from_page(doc[65], 65)
print(f"Total paragraphs extracted: {len(p65_blocks)}")
for i, b in enumerate(p65_blocks):
    print(f"[{i}] {b['line_count']} lines | bbox={[round(x,1) for x in b['bbox']]} | max_w={b['max_width']:.1f} pt | avail_w={b['available_width']:.1f} pt")
    print(f"    Text: {repr(b['text'][:60])}...")

print("\n=== Testing on Sample Document (sample_document.pdf) ===")
doc_sample = fitz.open("/home/mika/Desktop/diudiu/PDFwriter/sample_document.pdf")
s_blocks = extract_paragraphs_from_page(doc_sample[0], 0)
print(f"Total paragraphs in sample doc: {len(s_blocks)}")
for i, b in enumerate(s_blocks):
    print(f"[{i}] {b['line_count']} lines | bbox={[round(x,1) for x in b['bbox']]} | text={repr(b['text'][:50])}")
