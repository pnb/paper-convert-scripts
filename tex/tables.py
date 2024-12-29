import re

import bs4

from shared.shared_utils import warn_tex as warn
from . import TeXHandler


def format_tables(texer: TeXHandler) -> None:
    """Find table captions, piece them together if needed, and make other table
    adjustments for accessibility and simplicity. Assumes the table header is defined
    either by an \\hline or the first row of the table is the header if it is not clear
    from \\hline.
    """
    for adjustbox in texer.soup.find_all("div", attrs={"class": "adjustbox"}):
        adjustbox.unwrap()  # Remove any unused size adjustment wrappers

    table_tex_regex = re.compile(r"(^|[^\\])\\begin\s*\{((long)?table|minipage)")
    for table in texer.soup.find_all("table"):
        # Check previous lines for a table environment
        line_num = texer.tex_line_num(table)
        for i in range(line_num, 0, -1):
            if table_tex_regex.search(texer.tex_lines[i]):
                break
        else:
            continue  # No table environment found; skip this caption
        if table.find("caption"):  # Caption already almost correct (probs a longtable)
            caption_parent = table.find("caption").parent
            table.insert(0, table.find("caption"))
            if caption_parent.name == "td":
                caption_parent.parent.decompose()  # Get rid of empty <tr>
            format_one_table(texer, table)
            continue
        # Iterate backward through the soup to find caption parts
        cur_caption_candidate = table
        caption_parts = []
        while cur_caption_candidate.parent.name != "body":
            if cur_caption_candidate.previous_sibling:
                cur_caption_candidate = cur_caption_candidate.previous_sibling
            else:
                cur_caption_candidate = cur_caption_candidate.parent
                continue  # We already got the relevant children from this new parent
            if isinstance(cur_caption_candidate, bs4.Tag):
                if cur_caption_candidate.find("table") not in [None, table]:
                    break  # Found a previous subtable so we should stop
            # Mark as subcaption part if it seems like it is one
            if isinstance(cur_caption_candidate, bs4.Tag):
                for cls in ["minipage", "subfigure"]:
                    if cur_caption_candidate.find_parent("div", attrs={"class": cls}):
                        scap_re = re.compile(r"\s*\([a-zA-Z1-9]{1,2}\)")
                        scap_match = cur_caption_candidate.find(string=scap_re)
                        if scap_match:
                            scap_match.parent["class"] = "subcaption"
                            scap_match.parent.name = "span"
                        break
            caption_parts.append(cur_caption_candidate)
        # Sometimes a <figure> wraps the table for no reason; remove it
        if len(caption_parts):
            for figure in caption_parts[-1].parent.find_all("figure", recursive=False):
                figure.unwrap()  # Direct descendants only (recursive=False)
        # Put all the caption parts together into a <caption>
        caption = texer.soup.new_tag("caption")
        for part in reversed(caption_parts):
            if part.get_text(strip=True) == ":":
                part.decompose()  # Remove stray ":" sometimes inserted
                continue
            if isinstance(part, bs4.NavigableString) and re.search(
                r"(\s|^)width=([\d\.]+|$)", part
            ):  # Check for stray \adjustbox params, rendered for some reason
                new_part = bs4.NavigableString(
                    re.sub(r"((\smax)?\s|^)width=([\d\.]+|$)", "", part)
                )
                part.replace_with(new_part)
                part = new_part
                # After this, caption_parts can no longer be trusted because it has the
                # old `part` and replace_with works in a surprising way:
                # https://stackoverflow.com/questions/63424180
            caption.append(part)
        table.insert(0, caption)
        if not caption.get_text(strip=True):
            warn("table_caption_distance", table.get_text(strip=True)[:30] + "...")
        format_one_table(texer, table)
    add_tablenotes(texer)


def format_one_table(texer: TeXHandler, table: bs4.Tag) -> None:
    # Remove <p>s from table rows
    for p in table.find_all("p", limit=1000):
        p.unwrap()
    # Check for colspan/rowspan nested tables
    for subtable in table.find_all("table"):
        parent = subtable.parent
        while parent.name not in ["td", "th"]:
            parent = parent.parent
        for td in subtable.find_all("td"):
            td.name = "p"
            parent.append(td)
        for wrapper in parent.find_all(["div", "table"]):
            wrapper.decompose()
    # Find or create semantic <thead>
    thead = table.find("thead")
    if not thead:
        thead = texer.soup.new_tag("thead")
        if table.find("tr"):
            table.find("tr").insert_before(thead)
    for partial_line in table.find_all("tr", attrs={"class": "cline"}):
        partial_line.decompose()
    # Try to figure out what the header is based on \hline, if provided
    first_hline = table.find("tr", attrs={"class": "hline"})
    if first_hline and first_hline is table.find("tr"):
        first_hline.decompose()  # Line at very top of table
    next_hline = table.find("tr", attrs={"class": "hline"})
    if next_hline and next_hline is not table.find_all("tr")[-1]:
        for header_row in table.find_all("tr"):
            all_numbers = re.match(r"[\d.][\d\s.]+$", header_row.get_text(strip=True))
            if header_row is next_hline or all_numbers:
                break
            thead.append(header_row)
            for td in header_row.find_all("td"):
                td.name = "th"
    else:  # Assume header is first row
        header_row = table.find("tr")
        if header_row:
            thead.append(header_row)
            for td in header_row.find_all("td"):
                td.name = "th"
    # Add CSS classes for horizontal borders as long it isn't every row
    data_tr = [
        tr for tr in table.find_all("tr") if not tr.find("th") and tr.get_text().strip()
    ]
    hline_tr = table.find_all("tr", attrs={"class": "hline"})
    for tr in data_tr[1:]:
        if tr.previous_sibling and tr.previous_sibling in hline_tr:
            tr["class"] = "border-above"
    if len(table.select("tr.border-above")) == len(data_tr) - 1:  # \hline every row
        for tr in table.select("tr.border-above"):
            tr["class"] = ""
    for tr in table.find_all("tr"):
        if not tr.get_text().strip():
            tr.decompose()  # Remove remaining decorative rows (bad for accessibility)
    # Check if there are too many colgroups
    col_count = 0
    if table.find_all("tr"):
        col_count = max([len(tr.find_all(["th", "td"])) for tr in table.find_all("tr")])
    if col_count:
        colgroups = table.find_all("colgroup")
        if len(colgroups) >= col_count:  # Vertical lines every column (remove them)
            for cg in colgroups:
                cg.decompose()
        else:
            cols = table.find_all("col")  # Marker inside <colgroup>
            if len(cols) > col_count:  # Extra vertical line at end of table
                if len(cols[-1].parent.find_all("col")) == 1:
                    cols[-1].parent.decompose()  # Sole <col> inside <colgroup>
                else:
                    cols[-1].decompose()  # One of 2+ cols, keep the colgroup
    # Check for lone content not in cells
    for elem in table.find_all("div"):
        if not elem.find_parent(["th", "td"]):  # Not in a cell
            prev_cell = elem.find_previous_sibling(["th", "td"])
            if prev_cell:
                prev_cell.append(elem)
    # Check if we're left with one row, which should not be a header
    final_rows = table.find_all("tr")
    if len(final_rows) == 1 and final_rows[0].parent.name == "thead":
        final_rows[0].parent.unwrap()
        for th in final_rows[0].find_all("th"):
            th.name = "td"
    # Remove blank lines at the end of <pre> in tables
    for pre in table.find_all("pre"):
        for content in reversed(pre.contents):
            if not content.get_text(strip=True):
                content.replace_with("")
            else:
                break  # Reached real content
    # Check for partial \hhline stuff that turns into rows of _* incorrectly
    for tr in table.find_all("tr"):
        if re.match(r"^_+$", tr.get_text(strip=True)):
            tr.decompose()


def add_tablenotes(texer: TeXHandler) -> None:
    # If tablenotes exist, integrate them semantically into the table as <tfoot>
    for tablenotes in texer.soup.find_all("div", attrs={"class": "tablenotes"}):
        tablenotes.name = "td"
        tablenotes["colspan"] = 1000
        row_wrap = texer.soup.new_tag("tr")
        tfoot_wrap = texer.soup.new_tag("tfoot")
        tablenotes.wrap(row_wrap)
        row_wrap.wrap(tfoot_wrap)

        table = tablenotes.find_previous("table")
        thead = table.find("thead")
        if thead:
            thead.insert_after(tfoot_wrap)
        else:
            tbody = table.find("tbody")
            if tbody:
                tbody.insert_before(tfoot_wrap)
            else:
                table.find("tr").insert_before(tfoot_wrap)
