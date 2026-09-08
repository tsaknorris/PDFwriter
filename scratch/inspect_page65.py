import fitz
from pdf_engine.pdf_document import PDFDocumentModel

model = PDFDocumentModel()
model.open("/mnt/data/Downloads/Videogame_Industry_Does_Not_Exist.pdf")
blocks = model.get_blocks_for_page(65)
print("Total blocks detected on page 65:", len(blocks))
for i, b in enumerate(blocks):
    first_line = b["text"].split("\n")[0] if b.get("text") else ""
    bbox = [round(x, 1) for x in b.get("bbox", [])]
    lc = b.get("line_count")
    f = b.get("font")
    s = b.get("size")
    print(f"Block {i}: bbox={bbox} lines={lc} font={f} size={s} text={repr(first_line[:50])}")

print("\n--- Detailed inspect of block with 'The Other Game Industry' ---")
for i, b in enumerate(blocks):
    if "The Other Game Industry" in b.get("text", ""):
        print(f"Index {i}:")
        print("text:", repr(b.get("text")))
        print("bbox:", b.get("bbox"))
        print("max_width:", b.get("max_width"))
        print("original_lines:", b.get("original_lines"))
        print("line_bboxes:", b.get("line_bboxes"))
        print("line_origins:", b.get("line_origins"))
        print("line_leadings:", b.get("line_leadings"))
        print("spans:", b.get("spans"))
