import argparse
import os
import tempfile
import shlex
import shutil
import re

from PIL import Image
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer, LTChar, LTTextLineHorizontal
import numpy as np

import shared

ap = argparse.ArgumentParser(description="Check a PDF for any known issues")
ap.add_argument("pdf_path", help="PDF file path")
ap.add_argument("--max-preref-pages", type=int, help="Max allowed pages before refs")
args = ap.parse_args()


def count_nonblank_pixels(img: Image, x1: int, y1: int, x2: int, y2: int) -> int:
    """Return the number of non-blank pixels in the given rectangle. Assumes image is
    in grayscale via `img.convert("L")`."""
    img = img.crop((x1, y1, x2, y2))
    return sum(1 for pixel in img.getdata() if pixel < 255)


tmpdir = tempfile.mkdtemp()
shutil.copyfile(args.pdf_path, os.path.join(tmpdir, os.path.basename(args.pdf_path)))
retcode = shared.exec_grouping_subprocesses(
    "convert -density 100 -background white -alpha remove -alpha off "
    + shlex.quote(os.path.basename(args.pdf_path))
    + " page-%d.png",
    shell=True,
    cwd=tmpdir,
)
if retcode != 0:
    exit(retcode)

# Count non-blank pixels in margin to see if margins are correctly empty
for fname in os.listdir(tmpdir):
    if fname.startswith("page-"):
        page_num = int(fname.split("-")[1].split(".")[0]) + 1
        with Image.open(os.path.join(tmpdir, fname)) as img:
            img = img.convert("L")
            if img.size != (850, 1100):
                print(
                    "page size: Page",
                    page_num,
                    "is the wrong size; should be 8.5 × 11 inches, found",
                    img.size[0] / 100,
                    "×",
                    img.size[1] / 100,
                )
                continue  # If page is wrong size, nothing else can be checked well
            if count_nonblank_pixels(img, 0, 0, 65, 1100) > 20:
                print("margins: Page", page_num, "has content in left margin")
            if (
                count_nonblank_pixels(img, 785, 0, 850, 1100) > 20
                or count_nonblank_pixels(img, 790, 0, 850, 1100) > 0
            ):
                print("margins: Page", page_num, "has content in right margin")
            if count_nonblank_pixels(img, 0, 0, 850, 70) > 0:
                print("margins: Page", page_num, "has content in top margin")
            if count_nonblank_pixels(img, 0, 1030, 850, 1100) > 0:
                print("margins: Page", page_num, "has content in bottom margin")
            # Check copyright block on first page is blank (working around instructions
            # text that is present for MSWord version)
            if page_num == 1 and (
                count_nonblank_pixels(img, 0, 880, 420, 908) > 0
                or count_nonblank_pixels(img, 0, 945, 420, 1005) > 0
            ):
                print("copyright block: The copyright block has unexpected content")

# Check text of the PDF to extract things like title, headings (e.g., References), and
# fonts for additional checks
preref_page_count = 0  # Count of pages before references
appendix_before_refs = False
char_font_sizes = []
title_chars = []
title = ""
for page_i, page_layout in enumerate(extract_pages(args.pdf_path)):
    chars_in_page = 0
    cur_heading = []
    text_containers = [x for x in page_layout if isinstance(x, LTTextContainer)]
    for element in text_containers:
        text_lines = [x for x in element if isinstance(x, LTTextLineHorizontal)]
        for text_line in text_lines:
            chars = [x for x in text_line if isinstance(x, LTChar)]
            for character in chars:
                if not title and character.size > 17:
                    title_chars.append(character.get_text().replace("\n", " "))
                elif not title:
                    title = "".join(title_chars).strip()
                if character.size > 11.9 and character.size < 12.1:
                    cur_heading.append(character.get_text())
                    heading_str = "".join(cur_heading).lower()
                    if re.match(r"(\d*|[a-z])\.?\s*references", heading_str):
                        preref_page_count = page_i  # Don't count this page
                        if chars_in_page > len(cur_heading):  # Unless mid-page
                            preref_page_count = page_i + 1  # Then do count this page
                    if re.match(r"\d*\.?\s*appendi(x|ces)", heading_str):
                        if preref_page_count == 0:
                            appendix_before_refs = True
                else:
                    cur_heading.clear()
                chars_in_page += 1
                char_font_sizes.append(character.size)

print("info: title=" + title)  # Not an error, just a way to get the title for later
if appendix_before_refs:
    print("appendix location: Appendices should be after the references, not before")
if args.max_preref_pages and preref_page_count > args.max_preref_pages:
    print(
        "page limit: The paper has content on",
        preref_page_count,
        "pages before references, which is more than the maximum of",
        args.max_preref_pages,
    )
mdn_font_size = np.median(char_font_sizes)
if mdn_font_size < 8.75 or mdn_font_size > 9.25:
    print("font size: The median font size is", mdn_font_size, "pt (should be 9)")
