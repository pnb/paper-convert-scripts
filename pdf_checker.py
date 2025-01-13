import argparse
import os
import subprocess

import shared

ap = argparse.ArgumentParser(description="Check a PDF for any known issues")
ap.add_argument("pdf_path", help="PDF file path")
args = ap.parse_args()


def get_image_size(fname):
    try:
        stdout = subprocess.check_output(
            "identify -format '%w %h' " + os.path.basename(fname),
            shell=True,
            cwd=os.path.dirname(args.pdf_path),
        )
    except subprocess.CalledProcessError:
        exit(1)
    width, height = stdout.decode("utf-8").strip().split(" ")
    return int(width), int(height)


retcode = shared.exec_grouping_subprocesses(
    "convert -density 100 " + os.path.basename(args.pdf_path) + " -trim crop-%d.png",
    shell=True,
    cwd=os.path.dirname(args.pdf_path),
)
if retcode != 0:
    exit(retcode)

# Check the size of each page after cropping to see if it is out of margins
for fname in os.listdir(os.path.dirname(args.pdf_path)):
    if fname.startswith("crop-"):
        width, height = get_image_size(fname)
        page_num = int(fname.split("-")[1].split(".")[0]) + 1
        if width > 710:
            print(
                "margins: Page",
                page_num,
                "exceeds horizontal margin; expected 7 inches of text width between "
                "margins, found %.2f" % (width / 100),
            )
        if height > 935:  # Should be 11 - 1 - 0.75 = 9.25 inches
            print(
                "margins: Page",
                page_num,
                "exceeds vertical margin; expected 9.25 inches of text height between "
                "margins, found %.2f" % (height / 100),
            )

# Now check the size of the pages without cropping
retcode = shared.exec_grouping_subprocesses(
    "convert -density 100 " + os.path.basename(args.pdf_path) + " nocrop-%d.png",
    shell=True,
    cwd=os.path.dirname(args.pdf_path),
)
if retcode != 0:
    exit(retcode)

for fname in os.listdir(os.path.dirname(args.pdf_path)):
    if fname.startswith("nocrop-"):
        width, height = get_image_size(fname)
        page_num = int(fname.split("-")[1].split(".")[0]) + 1
        if width != 850 or height != 1100:
            print(
                "page size: Page",
                page_num,
                "is the wrong size; expected 8.5 × 11 inches, found",
                width / 100,
                "×",
                height / 100,
                "inches",
            )
