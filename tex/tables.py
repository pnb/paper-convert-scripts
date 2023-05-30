import re

import bs4

from shared_utils import warn_tex as warn
from . import TeXHandler


def format_tables(texer: TeXHandler) -> None:
    """Find table captions, piece them together if needed, and make other table adjustments for
    accessibility and simplicity. Assumes the table header is defined either by an \\hline or
    the first row of the table is the header if it is not clear from \\hline.
    """
    for adjustbox in texer.soup.find_all('div', attrs={'class': 'adjustbox'}):
        adjustbox.unwrap()  # Remove any unused size adjustment wrappers

    table_tex_regex = re.compile(r'(^|[^\\])\\begin\s*\{table')
    for caption_start in texer.soup.find_all(string=re.compile(r'Table\s+\d+:')):
        # Check previous lines for a table environment
        line_num = texer.tex_line_num(caption_start)
        for i in range(line_num, 0, -1):
            if table_tex_regex.search(texer.tex_lines[i]):
                break
        else:
            continue
        # Find beginning of table container where caption should be inserted
        table_name = caption_start.get_text().strip().split(':')[0]
        while caption_start.parent.name != 'div':  # Rewind to beginning of table container
            caption_start = caption_start.parent
        while caption_start.previous_sibling:
            caption_start = caption_start.previous_sibling  # Usually an anchor at this point
            if isinstance(caption_start, bs4.Tag) and caption_start.find('table'):
                warn('table_caption_distance', table_name)  # Caption below table
                break
        caption = texer.soup.new_tag('caption')
        caption_start.insert_before(caption)
        # Sometimes a <figure> wraps the table for no reason, and causes problems; remove it
        for figure in caption_start.parent.find_all('figure', recursive=False):
            figure.unwrap()  # Direct descendants only (recursive=False)
        # Combine all sub-sections (e.g., bold) into one caption
        while caption.next_sibling and (isinstance(caption.next_sibling, bs4.NavigableString) or
                                        caption.next_sibling.name not in ['div', 'table']):
            caption.append(caption.next_sibling)
        table = caption.find_next('table')  # Move into <table> where it belongs
        if not table:
            continue  # Something went pretty wrong, like caption below table
        table.insert(0, caption)
        # There may be multiple tabular environments within one table, so we'll now back up to the
        # parent and find each <table>
        container = table
        while container.parent.name != 'body' and not (container.has_attr('class') and 'float' in
                                                       container['class']):
            container = container.parent
        for onetable in container.find_all('table'):
            if not onetable.find_parent('table'):  # Not a nested table
                format_one_table(texer, onetable)
    add_tablenotes(texer)


def format_one_table(texer: TeXHandler, table: bs4.Tag) -> None:
    # Remove <p>s from table rows
    for p in table.find_all('p', limit=1000):
        p.unwrap()
    # Check for colspan/rowspan nested tables
    for subtable in table.find_all('table'):
        parent = subtable.parent
        while parent.name not in ['td', 'th']:
            parent = parent.parent
        for td in subtable.find_all('td'):
            td.name = 'p'
            parent.append(td)
        for wrapper in parent.find_all(['div', 'table']):
            wrapper.decompose()
    # Find or create semantic <thead>
    thead = table.find('thead')
    if not thead:
        thead = texer.soup.new_tag('thead')
        if table.find('tr'):
            table.find('tr').insert_before(thead)
    for partial_line in table.find_all('tr', attrs={'class': 'cline'}):
        partial_line.decompose()
    # Try to figure out what the header is based on \hline, if provided
    first_hline = table.find('tr', attrs={'class': 'hline'})
    if first_hline and first_hline is table.find('tr'):
        first_hline.decompose()  # Line at very top of table
    next_hline = table.find('tr', attrs={'class': 'hline'})
    if next_hline and next_hline is not table.find_all('tr')[-1]:
        for header_row in table.find_all('tr'):
            if header_row is next_hline:
                break
            thead.append(header_row)
            for td in header_row.find_all('td'):
                td.name = 'th'
    else:  # Assume header is first row
        header_row = table.find('tr')
        if header_row:
            thead.append(header_row)
            for td in header_row.find_all('td'):
                td.name = 'th'
    # Add CSS classes for horizontal borders as long it isn't every row
    data_tr = [tr for tr in table.find_all('tr') if not tr.find('th') and tr.get_text().strip()]
    hline_tr = table.find_all('tr', attrs={'class': 'hline'})
    if len(data_tr) > len(hline_tr):  # Not \hline every row
        for tr in data_tr[1:]:
            if tr.previous_sibling and tr.previous_sibling in hline_tr:
                tr['class'] = 'border-above'
    for tr in table.find_all('tr'):
        if not tr.get_text().strip():
            tr.decompose()  # Remove remaining decorative rows (bad for accessibility)
    # Check if there are too many colgroups
    example_row = table.find('tr')
    if example_row:
        col_count = len(example_row.find_all(['th', 'td']))
        colgroups = table.find_all('colgroup')
        if len(colgroups) >= col_count:  # Vertical lines every column (remove them)
            for cg in colgroups:
                cg.decompose()
        else:
            cols = table.find_all('col')  # Marker inside <colgroup>
            if len(cols) > col_count:  # Extra vertical line at end of table
                if len(cols[-1].parent.find_all('col')) == 1:
                    cols[-1].parent.decompose()  # Sole <col> inside <colgroup>
                else:
                    cols[-1].decompose()  # One of 2+ cols, keep the colgroup
    # Check for lone content not in cells
    for elem in table.find_all('div'):
        if not elem.find_parent(['th', 'td']):  # Not in a cell
            prev_cell = elem.find_previous_sibling(['th', 'td'])
            if prev_cell:
                prev_cell.append(elem)


def add_tablenotes(texer: TeXHandler) -> None:
    # If tablenotes exist, integrate them semantically into the table as <tfoot>
    for tablenotes in texer.soup.find_all('div', attrs={'class': 'tablenotes'}):
        tablenotes.name = 'td'
        tablenotes['colspan'] = 1000
        row_wrap = texer.soup.new_tag('tr')
        tfoot_wrap = texer.soup.new_tag('tfoot')
        tablenotes.wrap(row_wrap)
        row_wrap.wrap(tfoot_wrap)

        table = tablenotes.find_previous('table')
        thead = table.find('thead')
        if thead:
            thead.insert_after(tfoot_wrap)
        else:
            tbody = table.find('tbody')
            if tbody:
                tbody.insert_before(tfoot_wrap)
            else:
                table.find('tr').insert_before(tfoot_wrap)
