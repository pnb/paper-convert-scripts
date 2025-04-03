import re

import bs4


def add_pandoc_bullets(
    pandoc_soup: bs4.BeautifulSoup, mammoth_soup: bs4.BeautifulSoup
) -> None:
    # Find <ul> tags in Pandoc soup and add them to Mammoth soup if they don't exist
    for ul in pandoc_soup.select("ul"):
        # First, check if all <p> in this <ul> also exist in Mammoth soup
        lis = ul.select("li")
        if len(lis) == 0:
            continue  # No <li> in this <ul> (shouldn't happen I expect, but who knows)
        first_li_text = re.sub(r"\s+", " ", lis[0].get_text(strip=True))
        for p in mammoth_soup.select("p"):
            if re.sub(r"\s+", " ", p.get_text(strip=True)) == first_li_text:
                cur_p = p
                for li in lis[1:]:
                    cur_p = cur_p.find_next_sibling("p")
                    if not cur_p or re.sub(
                        r"\s+", " ", cur_p.get_text(strip=True)
                    ) != re.sub(r"\s+", " ", li.get_text(strip=True)):
                        break
                else:  # Successful match; everything from p through cur_p
                    new_ul = mammoth_soup.new_tag("ul")
                    p.insert_before(new_ul)
                    while True:
                        new_li = mammoth_soup.new_tag("li")
                        new_ul.append(new_li)
                        if new_ul.next_sibling == cur_p:
                            new_li.append(new_ul.next_sibling)
                            break
                        new_li.append(new_ul.next_sibling)
                    break  # On to next <ul>
