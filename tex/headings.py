from . import TeXHandler


def add_headings(texer: TeXHandler) -> None:
    """Add <h1>, <h2>, etc. headings to the soup based on clues such as font names left
    by make4ht.
    """
    # (Sub)section headings
    heading_fonts = ["ptmb8t-x-x-120", "ptmri8t-x-x-110"]
    for h_text in texer.soup.find_all("span", attrs={"class": heading_fonts}):
        h = h_text.parent
        if h.name == "p":  # Otherwise already handled (abstract, etc.)
            h["class"] = "not-numbered"
            num_text = h_text.get_text().strip()
            if "ptmb8t-x-x-120" in h_text["class"]:
                if num_text.endswith(".") or "." not in num_text:
                    h.name = "h1"
                    if h.get_text().lower().strip() == "abstract":
                        h["class"] = h["class"] + " AbstractHeading"
                    elif h.get_text().lower().strip() == "keywords":
                        h["class"] = h["class"] + " KeywordsHeading"
                        h.find_next("p")["class"] = "Keywords"
                        h.find_next("p").name = "div"
                else:
                    h.name = "h2"
            elif "ptmri8t-x-x-110" in h_text["class"]:
                h.name = "h3"
            # Remove any line breaks caused by \\ in the heading in LaTeX
            for br in h.find_all("br"):
                br.decompose()
    # Title
    title_first = texer.soup.find("span", attrs={"class": "phvb8t-x-x-180"})
    if title_first and "\\maketitle" in texer.tex_line(title_first):
        title = title_first.parent
        title["class"] = "Paper-Title"
        title.name = "div"
