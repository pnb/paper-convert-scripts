import bs4

from . import TeXHandler


def add_headings(texer: TeXHandler) -> None:
    """Add <h1>, <h2>, etc. headings to the soup based on clues such as font names left
    by make4ht.
    """
    # Title
    title_first = texer.soup.select_one(
        "span.phvb8t-x-x-180, span.phvr7t-x-x-248, span.phvr8t-x-x-248"
    )
    if title_first and "\\maketitle" in texer.tex_line(title_first):
        title = title_first.parent
        title["class"] = "Paper-Title"
        title.name = "div"
    if texer.input_template == "JEDM":
        # JEDM line-delimited abstract (not really a heading)
        for abstract_candidate in texer.soup.select(
            "span.ptmr7t-x-x-109, span.ptmr8t-x-x-109"
        ):
            if (
                abstract_candidate.parent.name == "p"
                and abstract_candidate.parent.has_attr("class")
                and "indent" in abstract_candidate.parent["class"]
            ):
                abstract_candidate = abstract_candidate.parent  # Wrapped in <p>
            for line_elem in abstract_candidate.parent.contents:
                if line_elem.get_text(strip=True).startswith("_" * 87):
                    abstract_heading = texer.soup.new_tag(
                        "h1", attrs={"class": ["AbstractHeading", "not-numbered"]}
                    )
                    abstract_heading.string = "Abstract"
                    line_elem.insert_before(abstract_heading)
                    line_elem.extract()
                    break
            if texer.soup.select("h1.AbstractHeading"):
                break  # Finished finding abstract
        # JEDM keywords
        for keywords_candidate in texer.soup.select(
            "span.ptmb7t-x-x-109, span.ptmri7t-x-x-109, span.ptmb8t-x-x-109"
        ):
            if keywords_candidate.get_text(strip=True).startswith("Keywords"):
                keywords_candidate.name = "h1"
                keywords_candidate["class"] = ["KeywordsHeading", "not-numbered"]
                keywords_candidate.string.replace_with("Keywords")
                content = keywords_candidate.find_next_sibling("span")
                content["class"] = "Keywords"
                content.name = "div"
                if content.get_text(strip=True).startswith(":"):
                    trimmed = content.get_text(strip=True)[1:].strip()
                    content.string.replace_with(trimmed)
                hline = content.parent
                for _ in range(5):  # Remove the line at the end of the abstract
                    hline = hline.find_next_sibling("p")
                    if not hline:
                        break
                    if hline.get_text(strip=True).startswith("_" * 87):
                        hline.decompose()
                        break
                break
    # (Sub)section headings
    heading_fonts = [
        "ptmb8t-x-x-120",
        "ptmri8t-x-x-110",
        "phvrc7t-x-x-144",
        "phvrc7t-x-x-120",
        "phvr7t-x-x-120",
    ]
    if texer.input_template == "JEDM":
        heading_fonts += ["phvrc8t-x-x-144", "phvrc8t-x-x-120", "phvr8t-x-x-120"]
    for h_text in texer.soup.find_all("span", attrs={"class": heading_fonts}):
        h = h_text.parent
        if h.name == "p":  # Otherwise already handled (abstract, etc.)
            h["class"] = "not-numbered"
            num_text = h_text.get_text().strip().split()[0]
            if (
                "ptmb8t-x-x-120" in h_text["class"]
                or "phvrc7t-x-x-144" in h_text["class"]
                or "phvrc7t-x-x-120" in h_text["class"]
                or "phvrc8t-x-x-144" in h_text["class"]
                or "phvrc8t-x-x-120" in h_text["class"]
            ):
                if (num_text.endswith(".") or "." not in num_text) and num_text.count(
                    "."
                ) < 2:
                    h.name = "h1"
                    if h.get_text().lower().strip() == "abstract":
                        h["class"] = h["class"] + " AbstractHeading"
                    elif h.get_text().lower().strip() == "keywords":
                        h["class"] = h["class"] + " KeywordsHeading"
                        h.find_next("p")["class"] = "Keywords"
                        h.find_next("p").name = "div"
                else:
                    h.name = "h2"
            elif (
                "ptmri8t-x-x-110" in h_text["class"]
                or "phvr7t-x-x-120" in h_text["class"]
                or "phvr8t-x-x-120" in h_text["class"]
            ):
                h.name = "h3"
            # Remove any line breaks caused by \\ in the heading in LaTeX
            for br in h.find_all("br"):
                br.decompose()
    # Subheadings made via \paragraph
    for phead in texer.soup.select("span.paragraph, span.subparagraph"):
        parent = phead.parent
        if parent.name == "p" and len(parent.find_all()) == 1:
            next_p = parent.next_sibling
            while next_p and not isinstance(next_p, bs4.Tag):
                next_p = next_p.next_sibling
            if next_p:
                next_p.insert(0, phead)
                parent.decompose()
        phead["role"] = "heading"  # Accessibility role
        phead["aria-level"] = "4" if "paragraph" in phead["class"] else "5"  # A guess
        if texer.input_template == "JEDM" and "paragraph" in phead["class"]:
            phead["class"].append("small-caps")
