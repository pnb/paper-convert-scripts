from . import MammothParser


def fix_jedm_frontmatter(mp: MammothParser) -> None:
    """Abstract/keyword headings and some stray <hr> elements need cleaning up in JEDM
    papers due to some semantic issues in the template (to be fixed)."""
    if mp.input_template == "JEDM":
        abstract = mp.soup.select_one("p.Abstract")
        if abstract.previous_sibling.name == "hr":
            abstract.previous_sibling.decompose()
        if abstract.next_sibling.name == "hr":
            abstract.next_sibling.decompose()
        abstract_heading = mp.soup.new_tag(
            "h1", attrs={"class": ["AbstractHeading", "not-numbered"]}
        )
        abstract_heading.string = "Abstract"
        abstract.insert_before(abstract_heading)
        # Extract keywords
        for keywords_candidate in abstract.select("strong"):
            if keywords_candidate.get_text(strip=True).startswith("Keywords:"):
                keywords_heading = mp.soup.new_tag(
                    "h1", attrs={"class": ["KeywordsHeading", "not-numbered"]}
                )
                keywords_heading.string = "Keywords"
                abstract.insert_after(keywords_heading)
                keywords = mp.soup.new_tag("div", attrs={"class": ["Keywords"]})
                keywords.string = keywords_candidate.get_text(strip=True).replace(
                    "Keywords:", ""
                )
                content = keywords_candidate.next_sibling
                while content:
                    next_content = content.next_sibling
                    keywords.append(content)
                    content = next_content
                keywords_heading.insert_after(keywords)
                keywords_candidate.decompose()
                break
