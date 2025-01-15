import argparse
import os

from PIL import Image

import shared

ap = argparse.ArgumentParser(description="Check a PDF for any known issues")
ap.add_argument("pdf_path", help="PDF file path")
args = ap.parse_args()


def count_nonblank_pixels(img: Image, x1: int, y1: int, x2: int, y2: int) -> int:
    """Return the number of non-blank pixels in the given rectangle. Assumes image is
    in grayscale via `img.convert("L")`."""
    img = img.crop((x1, y1, x2, y2))
    return sum(1 for pixel in img.getdata() if pixel < 255)


curdir = os.path.dirname(args.pdf_path)
retcode = shared.exec_grouping_subprocesses(
    "convert -density 100 -background white -alpha remove -alpha off "
    + os.path.basename(args.pdf_path)
    + " page-%d.png",
    shell=True,
    cwd=curdir,
)
if retcode != 0:
    exit(retcode)

# Count non-blank pixels in margin to see if margins are correctly empty
for fname in os.listdir(curdir):
    if fname.startswith("page-"):
        page_num = int(fname.split("-")[1].split(".")[0]) + 1
        with Image.open(os.path.join(curdir, fname)) as img:
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
            if count_nonblank_pixels(img, 0, 0, 65, 1100) > 0:
                print("margins: Page", page_num, "has content in left margin")
            if count_nonblank_pixels(img, 785, 0, 850, 1100) > 0:
                print("margins: Page", page_num, "has content in right margin")
            if count_nonblank_pixels(img, 0, 0, 850, 75) > 0:
                print("margins: Page", page_num, "has content in top margin")
            if count_nonblank_pixels(img, 0, 1025, 850, 1100) > 0:
                print("margins: Page", page_num, "has content in bottom margin")
            # Check copyright block on first page is blank (working around instructions
            # text that is present for MSWord version)
            if page_num == 1 and (
                count_nonblank_pixels(img, 0, 880, 420, 908) > 0
                or count_nonblank_pixels(img, 0, 945, 420, 1005) > 0
            ):
                print("copyright block: The copyright block has unexpected content")
