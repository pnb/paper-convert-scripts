import os

import bs4
import PIL

from shared.shared_utils import validate_alt_text
from . import MammothParser


def one_to_one_alt_text_map(mp: MammothParser) -> None:
    """If Mammoth hasn't successfully found alt text for all images, this will try to
    do a one-to-one mapping of <pic:cNvPr desc="alt text"> to images in the document,
    which can sometimes work (but only if the author has actually included alt text for
    all images)."""
    # Check if alt text was already found for all images
    imgs = mp.soup.find_all("img")
    for img in imgs:
        if not img.has_attr("alt"):
            break
    else:
        return  # No missing alt texts
    print("Mammoth did not find all alt texts; attempting 1-to-1 mapping")
    docx_soup = bs4.BeautifulSoup(mp.xml_txt, "lxml-xml")
    xml_pics = docx_soup.find_all("pic:cNvPr", attrs={"descr": True})
    if len(imgs) != len(xml_pics):
        print("1-to-1 mapping not possible")
        return
    for img, xml_pic in zip(imgs, xml_pics):
        if img.has_attr("alt") and img["alt"] != xml_pic["descr"]:
            print("1-to-1 mapping failed (mismatch between existing alt texts)")
            return
        elif not img.has_attr("alt"):
            img["alt"] = xml_pic["descr"]
    print("1-to-1 mapping complete")


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
