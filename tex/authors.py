import bs4

from shared.shared_utils import warn_tex as warn
from . import TeXHandler


def add_authors(texer: TeXHandler) -> None:
    """Parse author information and format the HTML soup a bit to add semantic
    information regarding author names, email addresses, and affiliations.
    """
    if texer.input_template == "JEDM":
        author_containers = []
        for email_candidate in texer.soup.select("span.phvr7t-x-x-109"):
            if "@" in email_candidate.get_text():
                author_containers.append(
                    email_candidate.find_parent("div", attrs={"class": "tabular"})
                )
        if len(author_containers):
            container = texer.soup.new_tag("div", attrs={"class": "center"})
            author_containers[0].insert_before(container)
            for author_container in author_containers:
                container.append(author_container)

    meta_section = texer.soup.find("div", attrs={"class": "center"})
    if not meta_section or not meta_section.find("div", attrs={"class": "tabular"}):
        warn("author_data_missing")
        return
    for tabular in meta_section.find_all("div", attrs={"class": "tabular"}):
        if not tabular.get_text().strip():
            tabular.decompose()
            continue
        format_author_superscripts(texer, tabular)
        # Combine/format parts of author info
        beyond_author_name = False  # Assume first thing is author name
        newline_after = False  # Track breaks after lines of multi-line affiliations
        for elem in tabular.find_all("span"):
            elem.name = "div"
            if (
                beyond_author_name
                or "@" in elem.get_text()
                or (
                    "phvr8t-x-x-120" not in elem["class"]
                    and "phvr7t-x-x-144" not in elem["class"]
                )
            ):
                beyond_author_name = True  # Evidence we are past the author name part
                if "@" in elem.get_text():
                    elem["class"] = "E-Mail"
                else:
                    elem["class"] = "Affiliations"
            else:
                elem["class"] = "Author"

            next_tag = elem.find_next_sibling(["span", "br"])
            if (
                not newline_after
                and isinstance(tabular.previous_sibling, bs4.Tag)
                and tabular.previous_sibling.has_attr("class")
                and elem["class"] in tabular.previous_sibling["class"]
            ):
                tabular.previous_sibling.append(elem)  # Combine consecutive parts
                elem.unwrap()
                if tabular.previous_sibling["class"] == "E-Mail":
                    for txt in tabular.previous_sibling.contents:
                        if type(txt) == bs4.NavigableString:
                            txt.replace_with(txt.strip())  # Remove space from emails
            else:
                if elem.next_sibling and isinstance(
                    elem.next_sibling, bs4.NavigableString
                ):
                    elem.append(texer.soup.new_string(" "))  # In case of concatenation
                tabular.insert_before(elem)  # New author chunk
            newline_after = not next_tag or next_tag.name == "br"
        tabular.decompose()
    format_author_footnotes(texer)


def format_author_superscripts(texer: TeXHandler, tabular: bs4.Tag) -> None:
    """Handle superscripts for affiliations."""
    for math_sup in tabular.find_all("math"):  # MathML conversion only, I believe
        if len(math_sup.contents) == 1:
            math_sup.name = "sup"
            math_sup.contents[0].replace_with(
                texer.soup.new_string(math_sup.get_text())
            )
        else:
            warn("unexpected", "Affiliation superscript format not understood")
    fnmark_seq = ["*", "*", "†", "‡", "d", "e", "f", "g", "h", "i"]
    for fnmark in tabular.find_all("span", attrs={"class": "footnote-mark"}):
        fnmark.name = "sup"
        if fnmark.find("a"):  # New (not same) footnote
            fnmark["class"].append("fresh-author-footnote")
        fnmark_i = len(
            texer.soup.find_all("sup", attrs={"class": "fresh-author-footnote"})
        )
        fnmark.string = fnmark_seq[fnmark_i]
    for sup in tabular.find_all("sup"):
        for span in sup.find_all("span"):
            span.unwrap()
        if (
            isinstance(sup.previous_sibling, bs4.Tag)
            and sup.previous_sibling.name == "span"
            or (
                isinstance(sup.previous_sibling, bs4.Comment)
                and sup.find_previous_sibling("span")
            )
        ):
            sup.find_previous_sibling("span").append(sup)
            # Insert space after the superscript unless it is followed by punctuation
            if (
                not isinstance(sup.parent.next_sibling, bs4.Tag)
                or (sup.parent.next_sibling.get_text() + " ")[0] not in ",.;"
            ):
                sup.insert_after(texer.soup.new_string(" "))
        elif sup.find_next_sibling("span"):  # Prepend instead
            sup.find_next_sibling("span").insert(0, sup)
        else:
            warn("unexpected", "Could not format affiliation superscript")


def format_author_footnotes(texer: TeXHandler) -> None:
    """Format the footnotes that result from author affiliation superscripts."""
    for fnstart in texer.soup.find_all("span", attrs={"class": "tcrm-0900"}):
        if fnstart.parent.name == "p":
            prev_elem = fnstart.parent.previous_sibling
            while not isinstance(prev_elem, bs4.Tag):
                prev_elem = prev_elem.previous_sibling
            if prev_elem.find("div", attrs={"class": "Author"}):
                # fnstart right after the authors
                fnstart["class"].append("author-footnote-content")
