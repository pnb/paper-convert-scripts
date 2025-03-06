import re

import bs4

from . import MammothParser


def add_pandoc_blockquotes(
    pandoc_soup: bs4.BeautifulSoup, mammoth_soup: bs4.BeautifulSoup
) -> None:
    # Find <blockquote> tags in Pandoc soup
    for bq in pandoc_soup.select("blockquote"):
        # First, find all matching <p> (by text) for the first <p> in bq
        # For each one of those, find if the next p also matches and break if not, else
        # keep going and if they all do then we have a match
        bqps = bq.select("p")
        if len(bqps) == 0:
            continue
        first_p_text = re.sub(r"\s+", " ", bqps[0].get_text(strip=True))
        for p in mammoth_soup.select("p"):
            if re.sub(r"\s+", " ", p.get_text(strip=True)) == first_p_text:
                cur_p = p
                for bqp in bqps[1:]:
                    cur_p = cur_p.find_next_sibling("p")
                    if not cur_p or re.sub(
                        r"\s+", " ", cur_p.get_text(strip=True)
                    ) != re.sub(r"\s+", " ", bqp.get_text(strip=True)):
                        break
                else:  # Successful match; everything from p through cur_p
                    new_bq = mammoth_soup.new_tag("blockquote")
                    p.insert_before(new_bq)
                    while True:
                        if new_bq.next_sibling == cur_p:
                            new_bq.append(new_bq.next_sibling)
                            break
                        new_bq.append(new_bq.next_sibling)
                    break  # On to next bq
