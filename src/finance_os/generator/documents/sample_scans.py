"""Sample vendor bills with no text layer, for testing OCR in the chat (python -m finance_os.generator.documents.sample_scans).

Writes to data/samples/:
- annotate_photo.png    a "phone photo" of an Annotate Co bill in a layout the system has never seen
                        (handwritten-style header, rotated, gray paper). Should read cleanly and pass the checks
                        except whatever the PO balance says.
- fedsec_scan.pdf       a scanned FedSec bill (image only, no text) reusing an invoice number that is already
                        posted, so the duplicate check must catch it.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from finance_os.paths import ROOT

OUT = ROOT / "data" / "samples"


def _font(size, bold=False):
    for name in (("arialbd.ttf" if bold else "arial.ttf"), "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _bill_image(vendor, lines, header, total_label, paper=(246, 244, 238), angle=0.0):
    img = Image.new("RGB", (1240, 1600), paper)
    d = ImageDraw.Draw(img)
    d.text((80, 70), vendor, font=_font(54, True), fill=(30, 30, 30))
    d.text((80, 140), "Remit to: PO Box 4410, Austin TX", font=_font(26), fill=(90, 90, 90))
    y = 230
    for k, v in header:
        d.text((80, y), k, font=_font(30, True), fill=(40, 40, 40))
        d.text((420, y), v, font=_font(30), fill=(40, 40, 40))
        y += 50
    y += 40
    d.line((80, y, 1160, y), fill=(60, 60, 60), width=3)
    d.text((80, y + 12), "Item", font=_font(28, True), fill=(40, 40, 40))
    d.text((900, y + 12), "Amount (USD)", font=_font(28, True), fill=(40, 40, 40))
    y += 70
    for desc, amount in lines:
        d.text((80, y), desc, font=_font(28), fill=(40, 40, 40))
        d.text((900, y), amount, font=_font(28), fill=(40, 40, 40))
        y += 50
    d.line((80, y + 10, 1160, y + 10), fill=(60, 60, 60), width=3)
    d.text((80, y + 30), total_label, font=_font(32, True), fill=(20, 20, 20))
    return img, y + 30  # caller prints the total as the vendor wrote it


def build():
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. Phone photo of an Annotate Co bill (new layout).
    lines = [("Medical transcript relabeling - batch 7", "1,250.00"), ("QA review hours (10 h @ 75.00)", "750.00")]
    img, ty = _bill_image("ANNOTATE CO.", lines,
                          [("Invoice ref.", "AC-2026-0099"), ("Invoice date", "2026-09-28"), ("Your PO", "PO00002")],
                          "TOTAL DUE")
    ImageDraw.Draw(img).text((900, ty), "2,000.00", font=_font(32, True), fill=(20, 20, 20))
    img = img.rotate(2.2, expand=True, fillcolor=(120, 120, 120)).filter(ImageFilter.GaussianBlur(0.8))
    img.save(OUT / "annotate_photo.png")

    # 2. Scanned FedSec bill (image only) reusing an invoice number already posted: a duplicate.
    lines = [("FedRAMP compliance support - January", "2,222.22")]
    img, ty = _bill_image("FedSec Partners LLC", lines,
                          [("Invoice No", "FSP-2026-0007"), ("Dated", "2026-01-31"), ("Customer PO", "PO00003")],
                          "Balance Due", paper=(250, 250, 250))
    ImageDraw.Draw(img).text((900, ty), "2,222.22", font=_font(32, True), fill=(20, 20, 20))
    png = OUT / "_fedsec_scan_page.png"
    img.convert("L").save(png)
    c = canvas.Canvas(str(OUT / "fedsec_scan.pdf"), pagesize=LETTER)
    w, h = LETTER
    c.drawImage(str(png), 30, 30, width=w - 60, height=h - 60, preserveAspectRatio=True)
    c.save()
    png.unlink()
    return [OUT / "annotate_photo.png", OUT / "fedsec_scan.pdf"]


if __name__ == "__main__":
    for p in build():
        print(p)
