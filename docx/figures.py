import os

import bs4
import PIL

from shared.shared_utils import validate_alt_text
from . import MammothParser


def crop_images(mp: MammothParser) -> None:
    """Crop images, if needed, and check that each one has a valid alt text set."""
    docx_soup = bs4.BeautifulSoup(mp.xml_txt, "lxml-xml")  # To get crop info from
    for img in mp.soup.find_all("img"):
        if img["src"][-4:] in [".jpg", ".png", ".gif"]:  # Load and check image
            fname = os.path.join(mp.output_dir, img["src"])
            pil_image = PIL.Image.open(fname)
            width, height = pil_image.size
            if width / height > 200:
                print("Replacing wide, thin image (x / y > 200) with horizontal rule")
                del img["src"]
                img.name = "hr"
                continue
        if not validate_alt_text(img, img["src"]):
            continue
        # Crop images if needed, where possible
        # (find them based on alt text -- sort of hacky)
        xml_elem = docx_soup.find("pic:cNvPr", attrs={"descr": img["alt"]})
        if not xml_elem:
            continue  # Happens in strange cases, might indicate alt-text problem?
        drawing = xml_elem.find_parent("drawing")  # Find parent <w:drawing> element
        crop = drawing.find("a:srcRect")  # Find crop element if it exists
        # Crop coordinates are given as proportions * 100k
        t = int(crop["t"]) / 100000 if crop and crop.has_attr("t") else 0
        r = int(crop["r"]) / 100000 if crop and crop.has_attr("r") else 0
        b = int(crop["b"]) / 100000 if crop and crop.has_attr("b") else 0
        l = int(crop["l"]) / 100000 if crop and crop.has_attr("l") else 0
        if t + r + b + l:  # Crop may be missing/empty, so check if it's even needed
            if img["src"][-4:] in [".jpg", ".png", ".gif"]:  # Crop image itself
                crop_box = (
                    l * width,
                    t * height,
                    width - r * width,
                    height - b * height,
                )
                print("Cropping image file:", img["src"], "LTRB:", crop_box)
                pil_image = pil_image.crop(box=crop_box)
                pil_image.save(fname)
            else:  # Do crop with an HTML element (for SVG)
                pass
