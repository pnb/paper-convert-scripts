import re

import bs4

from . import MammothParser
from shared.shared_utils import warn


def process_captions(mp: MammothParser) -> None:
    """Find captions, check that they match expectations for figures and tables, and
    move the caption elements inside the <table> or <figure> element where they should
    be.
    """
    caption_regex = re.compile(r"^\s*(Figure|Fig\.|Table)\s+(\d+)?")
    figure_counter = 0
    table_counter = 0
    for elem in mp.soup.find_all("caption"):
        match = re.match(caption_regex, elem.get_text())
        # Assign the appropriate HTML tag depending on whether it is a figure or table
        if not match:  # Caption text doesn't match expectations
            caption_text = (
                '"' + elem.get_text() + '"' if elem.get_text(strip=True) else "BLANK"
            )
            if caption_text == "BLANK":
                prev_text = ""
                for prev_elem in elem.previous_elements:
                    prev_text = prev_elem.get_text(strip=True)
                    if prev_text:
                        break
                next_text = ""
                for next_elem in elem.next_elements:
                    next_text = next_elem.get_text(strip=True)
                    if next_text:
                        break
                caption_text += '; text before: "' + prev_text
                caption_text += '" after: "' + next_text + '"'
            warn("unknown_caption_type", "Caption text: " + caption_text)
        elif match.group(1) == "Table":  # Already a <caption> (for tables)
            table_counter += 1
            new_num = table_counter
            # Check that this <table> immediate follows the caption; otherwise they
            # might have done something like used an image of a table, put the caption
            # below the table, or put the caption inside the table
            check_in_table = elem.parent
            while check_in_table:
                if check_in_table.name == "tr":
                    warn("caption_in_table", 'Caption text: "' + elem.get_text() + '"')
                check_in_table = check_in_table.parent
            table = elem.find_next("table")
            if not table or table.sourceline - elem.sourceline > 2:
                warn(
                    "table_caption_distance", 'Caption text: "' + elem.get_text() + '"'
                )
            elif table:
                table.insert(0, elem)  # Move <caption> inside <table> where it belongs
            if (
                isinstance(elem.next_sibling, bs4.Tag)
                and elem.next_sibling.name == "img"
            ):
                warn("image_as_table", 'Caption text: "' + elem.get_text() + '"')
        else:  # Change to <figcaption> for figures
            elem.name = "figcaption"
            figure_counter += 1
            new_num = figure_counter
            # Move <figcaption> inside a new <figure> containing the <img>(s)
            new_fig = mp.soup.new_tag("figure")
            elem.insert_after(new_fig)
            if elem.find_parent("tr"):
                warn("caption_in_table", 'Caption text: "' + elem.get_text() + '"')
            for img in elem.find_all("img"):  # Images in the same "Caption" paragraph
                new_fig.append(img)
            img = elem.previous_sibling
            while img and (
                (isinstance(img, bs4.NavigableString) and not img.strip())
                or img.name == "img"
                or img.name == "a"
                or (img.name == "p" and img.find("img"))
            ):
                next_img = img.previous_sibling
                new_fig.insert(0, img)
                img = next_img
            # Unwrap images from <p> and other containers if needed
            for wrapper in new_fig.find_all(["p", "em", "strong"]):
                wrapper.unwrap()
            for br in new_fig.find_all("br"):
                br.decompose()
            new_fig.append(elem)
        # Number figures and tables if the numbers have gotten dropped
        if match and not match.group(2):
            txt = elem.find(string=caption_regex)
            numbered_txt = re.sub(caption_regex, r"\1 " + str(new_num), txt, count=1)
            txt.replace_with(numbered_txt)
        elif match:
            punc = ":" if mp.input_template == "JEDM" else "."
            if elem.get_text()[match.end(0)] != punc:
                warn("no_caption_number_period", match.group(0))
