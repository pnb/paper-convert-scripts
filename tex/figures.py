import re

import bs4

from . import TeXHandler, tables
from make4ht_utils import get_command_content
from shared import validate_alt_text, set_img_class


def add_alt_text(texer: TeXHandler, img_elem: bs4.Tag) -> str:
    """Find alt text (Description command) in LaTeX for an <img> and add it to the
    image.

    Args:
        texer (TeXHandler): LaTeX handler containing soup and tools to modify it
        img_elem (bs4.Tag): <img> element; e.g., soup.find('img')

    Returns:
        str: Text that was added as the alt text
    """
    line_num_start = texer.tex_line_num(img_elem)
    img_line_num = texer.find_image_line_num(line_num_start, img_elem["src"])
    env_start, env_end = texer.get_tex_environment(img_line_num)
    tex_section = "\n".join(texer.tex_lines[env_start : env_end + 1])
    alts = get_command_content(tex_section, "Description")
    img_i = img_elem.parent.find_all("img").index(img_elem)
    if img_elem.has_attr("alt"):  # Make4ht defaults to "PIC" which is not real alt text
        del img_elem["alt"]
    if len(alts) > img_i:
        img_elem["alt"] = alts[img_i]
    validate_alt_text(img_elem, img_elem["src"], True)
    return img_elem["alt"] if img_elem.has_attr("alt") else None


def _fix_figure_text(texer: TeXHandler, figure: bs4.Tag) -> None:
    # Sometimes part of the image filename or alt text gets included on the <img> line
    for img in figure.find_all("img"):
        el = img.previous_sibling
        while el and (
            isinstance(el, bs4.NavigableString) or el.sourceline == img.sourceline
        ):
            next_el = el.previous_sibling
            if isinstance(el, bs4.NavigableString) and el.strip():
                el.replace_with("")
            el = next_el
        el = img.next_sibling
        while el and (
            isinstance(el, bs4.NavigableString)
            or el.sourceline == img.sourceline
            and el.name != "a"
        ):
            next_el = el.next_sibling
            if isinstance(el, bs4.NavigableString) and el.strip():
                el.replace_with("")
            el = next_el
    # Move everything non-<img> into the caption
    for p in figure.find_all("p"):
        if p.has_attr("id"):
            anchor = texer.soup.new_tag("a", attrs={"id": p["id"]})
            p.insert_before(anchor)
        p.unwrap()
    for div in figure.find_all("div"):
        div.name = "span"  # Change to spans so we know when we're done (no divs left)
    caption = texer.soup.new_tag("figcaption")
    for elem in reversed(figure.contents):
        if isinstance(elem, bs4.NavigableString) or (
            elem.name != "figure"
            and elem.name != "img"
            and (elem.name != "span" or "fbox" not in elem.get("class", []))
        ):
            caption.insert(0, elem)
    figure.append(caption)
    # Sometimes there is a leftover ":" element for some reason
    caption_remnant = caption.find("span", attrs={"class": ["caption", "id"]})
    if caption_remnant and caption_remnant.get_text().strip() == ":":
        caption_remnant.decompose()


def _format_tabular_figures(texer: TeXHandler) -> None:
    """Handle cases with \\begin{figure}\\begin{tabular}..."""
    for tabular in texer.soup.select("div.figure > div.tabular"):
        for table in tabular.find_all("table"):
            tables.format_one_table(texer, table)
        tabular.parent.name = "figure"
        tabular.parent["class"] = ["table-as-figure"]
        caption = tabular.parent.find("span", string=re.compile(r"Figure\s+\d+[:\.].*"))
        if caption:
            caption.name = "figcaption"


def format_figures(texer: TeXHandler) -> None:
    """Parse alt text from LaTeX and add it to figures, merge subfigures into a parent
    <figure> element, set image sizes, and do any other minor adjustments needed for
    figures.

    Args:
        texer (TeXHandler): LaTeX handler containing soup and tools to modify it
    """
    # First convert any <object>s introduced by SVG conversion to <img>
    width_regex = re.compile(r'width="(\d+)"')
    for obj in texer.soup.find_all("object", attrs={"class": "graphics"}):
        comment = obj.find_next(string=lambda x: isinstance(x, bs4.Comment))
        if comment:
            w = width_regex.search(comment)
            if w:
                obj["width"] = int(w.group(1))
        obj.name = "img"
        obj["src"] = obj["data"]
        del obj["name"]
    for img in texer.soup.find_all("img"):
        if img["src"].startswith("tmp-make4ht"):  # Generated image
            if img.has_attr("class") and "oalign" in img["class"]:
                img.decompose()  # Artifact of some LaTeX alignment function
                continue
            elif img.has_attr("alt") and "Algorithm" in img["alt"]:
                continue  # Skip over images generated of algorithm listings
        if img.parent.has_attr("class") and "centerline" in img.parent["class"]:
            img.parent.unwrap()  # Remove extra div added if somebody uses \centerline
        # Repair double // in img src when using a trailing / with \graphicspath
        img["src"] = img["src"].replace("//", "/")
        # Handle alt text and caption
        add_alt_text(texer, img)
        img_text_line_num = texer.tex_line_num(img)
        img_text_line_num = texer.find_image_line_num(img_text_line_num, img["src"])
        env_start, _ = texer.get_tex_environment(img_text_line_num)
        parent = img.parent
        subfigure_wrapper = img.find_parent("div", attrs={"class": "subfigure"})
        if "subfigure" in texer.tex_lines[env_start] or subfigure_wrapper:
            if subfigure_wrapper:
                for wrapper in subfigure_wrapper.find_all(["table", "tr", "td"]):
                    wrapper.unwrap()
            img["class"] = "subfigure"
            parent = img.find_parent(["div", "figure"])
            parent.name = "figure"
            _fix_figure_text(texer, parent)  # Handle subfigure caption
            parent = parent.parent  # Go up to next level to handle containing <figure>
        while parent.name != "div" and parent.name != "figure":
            parent = parent.parent
        parent.name = "figure"
        if not parent.find("div"):  # No (more) subfigures to worry about
            if "subfigure" in texer.tex_lines[env_start] or subfigure_wrapper:
                parent["class"] = "has-subfigures"
            _fix_figure_text(texer, parent)  # Handle figure caption

        # Set image size class
        if img.has_attr("height"):
            del img["height"]  # Fixes width/height proportions; width is more important
        if img.has_attr("width") and (
            "scale=" in texer.tex_lines[img_text_line_num - 1]
            or "\\unitlength" in texer.tex_lines[img_text_line_num - 1]
        ):
            del img["width"]  # Some things lead to tiny width, so we have to skip it
        width_in = 3  # Assume medium-ish for "figure" environment
        if img.has_attr("width"):
            width_in = int(img["width"]) / 72
            del img["width"]
            if "subfigure" in texer.tex_lines[env_start] or subfigure_wrapper:
                width_in = width_in * 0.8  # Assume subfigures should be a bit smaller
        if "figure*" in texer.tex_lines[env_start] and len(parent.find_all("img")) == 1:
            width_in = 5  # Assume large for a "figure*" environment with 1 image
        set_img_class(img, width_in)

    _format_tabular_figures(texer)


def format_listings(texer: TeXHandler) -> None:
    for pre in texer.soup.select("pre.lstlisting"):
        container = pre.parent
        container["class"] = "listing"
        container.name = "figure"

        # Move everything after the code into the caption
        caption = texer.soup.new_tag("figcaption")
        pre.insert_after(caption)
        while caption.next_sibling:
            if isinstance(caption.next_sibling, bs4.NavigableString):
                label = re.match(r"\s*Listing\s+\d+(.)", str(caption.next_sibling))
                if label and label.group(1) not in ":.":
                    newlabel = re.sub(
                        r"\s*Listing\s+(\d+)",
                        r"Listing \1: ",
                        str(caption.next_sibling),
                    )
                    caption.next_sibling.replace_with(newlabel)
            caption.append(caption.next_sibling)

        # Fix the fact that tex4ht adds line breaks inside \textbf{two words}*
        # This assumes nobody would do a multiline \textbf, which may not be right
        for elem in pre.select("span.ptmb7t-x-x-120"):
            for content in elem.contents:
                if isinstance(content, bs4.NavigableString):
                    content.replace_with(str(content).replace("\n", ""))
