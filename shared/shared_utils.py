import csv
import os
import json
import re

import bs4


main_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..")
with open(os.path.join(main_dir, "config.json")) as infile:
    CONFIG = json.load(infile)
    CONFIG["utils_dir"] = main_dir
with open(os.path.join(main_dir, "messages.json")) as infile:
    messages_txt = json.load(infile)
    WARNING_DEFS = messages_txt["warnings"]


def warn(warning_name: str, extra_info: str = "", tex: bool = False) -> None:
    """Display and record a warning, as defined in messages.json. If `tex` is True, any
    keys/values in the "tex" key of the warning in messages.json will overwrite the
    default message; see warn_tex().

    Extra information may be provided to help fix this specific instance of the warning;
    for example, to include a line number or table number.

    Args:
        warning_name (str): Key from the "warnings" object in messages.json
        extra_info (str, optional): Information useful for debugging this warning.
        Defaults to "".
        tex (bool, optional): Use LaTeX key/value, if it exists. Defaults to False.

    Raises:
        NotImplementedError: Indicates warning_name is not defined in messages.json's
        "warnings"
    """
    if not hasattr(warn, "output_filename"):
        raise KeyError("warn.output_filename must be set to a CSV file path")
    if warning_name not in WARNING_DEFS.keys():
        raise NotImplementedError(
            warning_name, "is not implemented; check spelling or implement"
        )
    if not os.path.exists(warn.output_filename):
        with open(warn.output_filename, "w", encoding="utf8") as ofile:
            ofile.write("warning_name,extra_info,is_tex\n")
    with open(warn.output_filename, "a", encoding="utf8") as ofile:
        writer = csv.writer(ofile, lineterminator="\n")
        writer.writerow([warning_name, extra_info, int(tex)])
    message = WARNING_DEFS[warning_name]["message"]
    if (
        tex
        and "tex" in WARNING_DEFS[warning_name].keys()
        and "message" in WARNING_DEFS[warning_name]["tex"]
    ):
        message = WARNING_DEFS[warning_name]["tex"]["message"]
    if extra_info:
        extra_info = "\n    └> " + str(extra_info)
    print("Conversion warning:", message, extra_info)


def warn_tex(warning_name: str, extra_info: str = "") -> None:
    """Run warn() with `tex = True`. This is useful for shorthand, e.g., `import
    warn_tex as warn`. See warn() documentation for full description.

    Args:
        warning_name (str): Key from the "warnings" object in messages.json
        extra_info (str, optional): Information useful for debugging this warning.
        Defaults to ''.
    """
    warn(warning_name, extra_info, True)


def get_elem_containing_text(
    soup: bs4.BeautifulSoup, tagname: str, text: str, last: bool = False
) -> bs4.Tag:
    """Find a BeautifulSoup element containing some specific text. For example, one
    could find the "References" h1 element. Text matching is case insensitive.
    Whitespace, numbers, and punctuation at the beginning/end of the element's text will
    be ignored to make headings easier to match.

    Args:
        soup (bs4.BeautifulSoup): Soup or Tag to search within
        tagname (str): Name of tag, e.g., h1, div to look for
        text (str): Text to search for (case insensitive); can be a regex
        last (bool, optional): Search in reverse order to find the last occurrence

    Returns:
        bs4.Tag: Element containing the specified text, or None if not found
    """
    regex = re.compile(r"[\s.0-9]*" + text + r"[\s.0-9]*", re.IGNORECASE)
    candidates = soup.find_all(tagname)
    if last:
        candidates = reversed(candidates)
    for elem in candidates:
        if regex.match(elem.get_text()):
            return elem
    return None


def check_styles(
    soup: bs4.BeautifulSoup, output_dir: str, input_template: str, tex: bool = False
) -> None:
    """Check the `soup` object to see if it has most of the expected elements with the
    appropriate styles, and trigger warnings if not. This is intended as one of the last
    steps, after postprocessing.

    Args:
        soup (bs4.BeautifulSoup): Processed paper
        output_dir (str): Output folder, needed to store temporary files
        input_template (str): Expected document format name (e.g., JEDM)
        tex (bool, optional): Generate warnings flagged as LaTeX warnings
    """
    # Check for <img> with figure "caption" with wrong style (mostly a DOCX problem)
    for img in soup.find_all("img"):
        if (
            isinstance(img.next_sibling, bs4.Tag)
            and img.next_sibling.get_text().strip().startswith("Figure ")
            and img.next_sibling.name != "figcaption"
            and not img.next_sibling.find("figcaption")
        ):
            warn(
                "figure_caption_unstyled",
                img.next_sibling.get_text(strip=True)[:20] + "...",
                tex,
            )

    # Check metadata-related styles
    if not soup.find("div", attrs={"class": lambda x: x and "Paper-Title" in x}):
        warn("style_paper_title", tex=tex)
    if not soup.find("h1", attrs={"class": lambda x: x and "KeywordsHeading" in x}):
        warn("style_keywords_heading", tex=tex)
    if not soup.find("div", attrs={"class": lambda x: x and "Keywords" in x}):
        warn("style_keywords", tex=tex)
    if not soup.find("h1", attrs={"class": lambda x: x and "AbstractHeading" in x}):
        warn("style_abstract_heading", tex=tex)
    authors = soup.find_all("div", attrs={"class": lambda x: x and "Author" in x})
    num_affil = len(
        soup.find_all("div", attrs={"class": lambda x: x and "Affiliations" in x})
    )
    emails = soup.find_all("div", attrs={"class": lambda x: x and "E-Mail" in x})
    if not len(authors):
        warn("style_author", tex=tex)
    else:
        for author in authors:
            if "@" in author.get_text():
                warn("style_email_in_author", author.get_text().strip(), tex)
    if not num_affil:
        warn("style_affiliations", tex=tex)
    if not len(emails):
        warn("style_email", tex=tex)
    else:
        for email in emails:
            if "@" not in email.get_text().strip().split()[-1]:
                warn("style_space_in_email", email.get_text().strip(), tex)
    # Check headings
    if not get_elem_containing_text(soup, "h1", "introduction"):
        warn("style_no_intro", tex=tex)
    if not get_elem_containing_text(soup, "h1", "references"):
        warn("style_no_refs", tex=tex)
    for hx in soup.find_all(["h1", "h2", "h3", "h4"]):
        if len(hx.get_text(strip=True)) > 200:
            warn("style_long_heading", hx.get_text(strip=True), tex)
    # Check for broken equation number references
    for broken_ref in soup.find_all(
        string=["??", "Error! Reference source not found."]
    ):
        warn("broken_internal_ref", 'Text: "' + broken_ref + '"', tex)
    # Check URL schemas
    for a in soup.find_all("a"):
        schemas = ["#", "http://", "https://"]
        if a.has_attr("href") and not any(a["href"].startswith(x) for x in schemas):
            warn("url_schema", a["href"])
    # Check typography
    for quotedir_match in re.finditer(r"(\s”\w|\w“\s)", soup.get_text()):
        snip_start = max(0, quotedir_match.start() - 20)
        snip_end = quotedir_match.end() + 20
        warn("quote_direction", soup.get_text()[snip_start:snip_end].replace("\n", " "))


def check_alt_text_duplicates(soup: bs4.BeautifulSoup, tex: bool = False) -> None:
    """Check if all alt texts in the given document are unique, which they should be for
    both semantic and practical reasons (because DOCX conversion uses alt text as an
    identifier). Duplicate alt text is only ignored for the same image filename, which
    can occur for decorative images or other small repeated images (e.g., emojis).

    Args:
        soup (bs4.BeautifulSoup): Soup for document to check
        tex (bool): Whether or not to trigger LaTeX warnings, if there are any warnings
    """
    alt_texts = {}  # Filename -> alt text
    for img in soup.find_all("img"):
        if img.has_attr("alt") and img["alt"]:
            if img["alt"] in alt_texts.values():  # Duplicate alt text
                if alt_texts.get(img["src"]) != img["alt"]:  # And not for same filename
                    warn("alt_text_duplicate", 'Alt text: "' + img["alt"] + '"', tex)
            alt_texts[img["src"]] = img["alt"]


def validate_alt_text(
    img_elem: bs4.Tag, identifying_text: str, tex: bool = False
) -> bool:
    """Check if the alt text for this <img> element meets expectations. Triggers
    warnings if not.

    Args:
        img_elem (bs4.Tag): An <img> element to check, e.g., from `soup.find('img')`
        identifying_text (str): Some helpful information to help identify this image
        tex (bool): Whether or not to trigger LaTeX warnings, if there are any warnings

    Returns:
        bool: True if the alt text seems OK, False if some serious issue was found
    """
    if not img_elem.has_attr("alt") or not img_elem["alt"]:
        warn("alt_text_missing", identifying_text, tex)
        return False
    elif len(img_elem["alt"]) > 2000:
        warn("alt_text_long", img_elem["alt"], tex)
        return True  # Not a deal breaker, so don't stop processing the image
    return True


def set_img_class(img_elem: bs4.Tag, width_inches: float) -> None:
    """Set the size of an <img> element using a CSS class, unless it is very small in
    which case the exact size will be used.

    Args:
        img_elem (bs4.Tag): <img> element; e.g., `soup.find('img')`
        width_inches (float): Image width in inches
    """
    cur_class = img_elem["class"] if img_elem.has_attr("class") else ""
    if isinstance(cur_class, list):
        cur_class = " ".join(cur_class)
    if width_inches < 1:  # Very small image; just use exact size
        img_elem["style"] = "width:" + str(width_inches) + "in;"
    elif width_inches < 2:
        img_elem["class"] = cur_class + " img-small"
    elif width_inches < 4:
        img_elem["class"] = cur_class + " img-medium"
    else:
        img_elem["class"] = cur_class + " img-large"


def position_figures_tables(soup: bs4.BeautifulSoup) -> None:
    """Move tables and figures to the end of the next (sub)section, unless they are
    subfigures (as identified with the data-subfigure=1 property) or have
    data-position-here=1 set. Moving figures and tables may be necessary for two-column
    docx objects that occur in the XML before their position in the layout or for LaTeX
    figures/tables that are also typically layed out after their position in the source.

    Args:
        soup (bs4.BeautifulSoup): Paper soup with h1/h2/etc. headings for sections
    """
    for elem in soup.find_all(
        ["table", "figure"],
        attrs={"data-subfigure": False, "data-position-here": False},
    ):
        next_heading = elem.find_next(["h1", "h2", "h3", "h4", "h5", "h6"])
        if next_heading:
            next_heading.insert_before(elem)
        else:  # This will almost never happen, and isn't necessarily worth warning
            print("Info: Could not move table/figure to end of section")


def wrap_author_divs(soup: bs4.BeautifulSoup) -> None:
    """Wrap each author (or author group) in a div so they can be displayed side-by-side
    if space permits.

    Args:
        soup (bs4.BeautifulSoup): Paper soup with author/affiliation info already parsed
    """
    all_authors_wrapper = soup.new_tag("div", attrs={"class": "all-authors"})
    inserted = False
    for auth_start_elem in soup.find_all("div", attrs={"class": "Author"}):
        wrapper = soup.new_tag("div", attrs={"class": "author-chunk"})
        auth_start_elem.insert_before(wrapper)
        wrapper.append(auth_start_elem)
        while wrapper.next_sibling and (
            isinstance(wrapper.next_sibling, bs4.Tag)
            and wrapper.next_sibling.has_attr("class")
            and (
                "Affiliations" in wrapper.next_sibling["class"]
                or "E-Mail" in wrapper.next_sibling["class"]
            )
        ):
            if "E-Mail" in wrapper.next_sibling["class"]:
                for a in wrapper.next_sibling.find_all("a"):
                    a.unwrap()  # Remove occasional mailto: for consistency
            wrapper.append(wrapper.next_sibling)
        if not inserted:
            wrapper.insert_before(all_authors_wrapper)
            inserted = True
        all_authors_wrapper.append(wrapper)


def fix_table_gaps(soup: bs4.BeautifulSoup) -> None:
    """Fix blank cells in table where needed, which is especially needed for having
    accessible headers.

    Args:
        soup (bs4.BeautifulSoup): Paper soup
    """
    for th in soup.find_all("th"):
        if not th.get_text(strip=True):
            th.name = "td"  # Convert empty header cells to <td> which is more correct


def prettify_soup(soup: bs4.BeautifulSoup) -> str:
    """Generate an HTML string of a BeautifulSoup paper document that is slightly more
    readable than simply calling str(soup).

    Args:
        soup (bs4.BeautifulSoup): Paper soup

    Returns:
        str: HTML (UTF-8 encoded)
    """
    # Only insert newlines where it is safe to do so (not going to add semantic space)
    html = soup.encode_contents(formatter="html").decode("utf8")
    html = re.sub(r"\n\n+", "\n", html)
    html = (
        html.replace(chr(0x1F86A), "&rarr;")
        .replace(chr(0x1F868), "&larr;")
        .replace("&hyphen;", "-")
    )
    return html


def save_soup(soup: bs4.BeautifulSoup, output_filename: str) -> None:
    """Add header/footer to a BeautifulSoup object or Tag object and save to a file as
    UTF-8 HTML.

    Args:
        soup (bs4.BeautifulSoup or bs4.Tag): Soup to save to file
        output_filename (str): Output filename (probably ending with .html)
    """
    paper_title = soup.find("div", attrs={"class": "Paper-Title"})
    paper_title = paper_title.get_text() if paper_title else "Paper"
    header = (
        """<!doctype html>
<html lang="en-US">
    <head>
        <title>"""
        + paper_title
        + """</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta charset="UTF-8">
        <link rel="stylesheet" type="text/css" href="../iedms.css" />
        <script src="../table_sizer.js" defer></script>
        <script>
            MathJax = {
                loader: {
                    load: ['[tex]/textmacros', '[tex]/mathtools']
                },
                tex: {
                    tags: 'ams',
                    macros: {
                        textsc: [
                            '\\\\style{font-variant-caps: small-caps}{\\\\text{#1}}', 1
                        ],
                        relax: ''
                    },
                    packages: {'[+]': ['textmacros', 'mathtools']}
                }
            }
        </script>
        <script id="MathJax-script" async
            src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
    </head>
    <body>
        <main role="main" class="paper-contents">
    """
    )
    footer = """
        </main>
    </body>
</html>
"""
    with open(output_filename, "w", encoding="utf8") as outfile:
        outfile.write(header)
        outfile.write(prettify_soup(soup))
        outfile.write(footer)
