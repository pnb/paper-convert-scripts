import bs4

from . import TeXHandler


def parse_description_lists(texer: TeXHandler) -> None:
    for p in texer.soup.find_all("p", attrs={"class": "description-env"}):
        if p.find("dl"):
            continue  # Already parsed OK
        p.name = "dl"
        for br in p.find_all("br"):
            # \\ and \hfill in LaTeX, which is often default HTML styling anyway
            br.decompose()
        for item in p.find_all(attrs={"class": "aeb10-x-x-90"}):
            item.name = "dt"
            item.insert_after(texer.soup.new_tag("dd"))
        for dd in p.find_all("dd"):
            # Find the definitions, which might include styles
            while dd.next_sibling and (
                not isinstance(dd.next_sibling, bs4.Tag) or dd.next_sibling.name != "dt"
            ):
                dd.append(dd.next_sibling)
