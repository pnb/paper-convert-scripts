import re
import zipfile
import os

import bs4

import shared_utils
from shared_utils import warn_tex as warn


def get_raw_tex_contents(source_zip_path: str, extracted_dir: str) -> str:
    """Return the LaTeX contents of a source zip file as a string. Assumes there is only 1 .tex file
    in the zip file root, or that there is a file called main.tex in the zip file root.

    Args:
        source_zip_path (str): Path to LaTeX .zip file
        extracted_dir (str): Path to a directory where the zip file should be extracted

    Returns:
        str: LaTeX contents
    """
    def _load_tex_str(source_tex_filename: str):
        with open(source_tex_filename, errors='replace') as infile:
            raw_tex = infile.read()
        # Remove lines starting with %; replace with single % to avoid introducing a <p>
        raw_tex = re.sub(r'([^\\]%).*$', r'\1', raw_tex, flags=re.MULTILINE)
        # Remove \titlenote{}, which make4ht handles poorly so far
        raw_tex = re.sub(r'([^\\]|^)\\titlenote\{[^\}]*\}', r'\1', raw_tex, flags=re.MULTILINE)
        return raw_tex

    with zipfile.ZipFile(source_zip_path, 'r') as inzip:
        inzip.extractall(extracted_dir)
    tex_files = [f for f in os.listdir(extracted_dir) if f.endswith('.tex') and f != 'tmp.tex']
    if len(tex_files) == 1:
        tex_fname = tex_files[0]
    elif 'main.tex' in tex_files:
        tex_fname = 'main.tex'
    elif len(tex_files):
        tex_fname = tex_files[0]
        warn('ambiguous_tex_file', 'Using first file: ' + tex_fname)
    else:
        warn('tex_file_missing')
        exit()

    # Load tex file and any \input files
    tex_str = _load_tex_str(os.path.join(extracted_dir, tex_fname))
    input_regex = re.compile(r'\\input\s*\{\s*(\S+)\s*\}')
    for _ in range(25):  # Limit \input to prevent a recursive self-include bomb
        match = input_regex.search(tex_str)
        if not match:
            break
        print('Including \\input file:', match.group(1) + '.tex')
        extra_tex_str = _load_tex_str(os.path.join(extracted_dir, match.group(1) + '.tex'))
        tex_str = tex_str[:match.start()] + extra_tex_str + tex_str[match.end():]

    # Check for known issues in the raw tex
    match = re.search(r'\\end\{algorithmic\}[ \t]*\n[ \t]*[a-zA-Z]{1,20}', tex_str, re.MULTILINE)
    if match:
        warn('no_newline_after_algorithmic', match.group(0))
    return tex_str


def get_bib_backend(tex_str: str) -> str:
    """Try to determine what bibliography backend a paper uses. Assumes bibtex if it can't find the
    backend.

    Args:
        tex_str (str): LaTeX document source code

    Returns:
        str: Name of backend command to use for compiling the document (e.g., biber, bibtex)
    """
    bib_regex = re.compile(r'^\s*\\usepackage\s*\[.*backend=(\w+).*\]\s*\{\s*biblatex\s*\}',
                           re.MULTILINE)
    match = bib_regex.search(tex_str)
    if match:
        return match.group(1)
    return 'bibtex'


class TeXHandler:
    def __init__(self, tex_str: str, soup: bs4.BeautifulSoup) -> None:
        """Create an instance of a class with a set of functions useful for postprocessing a
        document BeautifulSoup object given its source LaTeX string. Some functions need to be
        called before others.

        Args:
            tex_str (str): LaTeX document source code
            soup (bs4.BeautifulSoup): BeautifulSoup document object
        """
        self.tex_lines = tex_str.split('\n')
        self.soup = soup
        self.env_start_regex = re.compile(r'(^|[^\\])\\begin\{(.+)\}')
        self.env_end_regex = re.compile(r'(^|[^\\])\\end\{')

        # Remove <hr>s added all over the place
        for hr in soup.find_all('hr'):
            hr.decompose()

        # Remove random PICT thing it adds; later should delete all empty <p>
        pict_img = soup.find('img', attrs={'alt': 'PICT'})
        if pict_img and '0x.' in pict_img['src']:
            top_parent = pict_img
            cur_elem = pict_img.parent
            while cur_elem.parent:
                if cur_elem.name == 'p':
                    top_parent = cur_elem
                cur_elem = cur_elem.parent
            top_parent.decompose()

    def tex_line_num(self, soup_elem: bs4.Tag) -> int:
        """Get the line number of LaTeX code corresponding to a BeautifulSoup element (1-indexed).
        This works by using the comments make4ht adds to the soup, which are usually accurate but
        may be imprecise for commands like \maketitle that rely on many other lines.

        Args:
            soup_elem (bs4.Tag or bs4.NavigableString): Something selected, e.g., soup.find('div')

        Returns:
            int: Line number (1-indexed) or 0 if no make4ht comment could be found
        """
        comment = soup_elem
        while comment:
            comment = comment.find_previous(string=lambda x: isinstance(x, bs4.Comment))
            if comment and comment.strip().startswith('l. '):
                return int(comment.strip().split(' ')[-1])
        return 0

    def tex_line(self, soup_elem: bs4.Tag) -> str:
        """Get the line of LaTeX code corresponding to a BeautifulSoup element. See
        `tex_line_num()` documentation.

        Args:
            soup_elem (bs4.Tag or bs4.NavigableString): Something selected, e.g., soup.find('div')

        Returns:
            str: Line of LaTeX code or '' if no make4ht comment could be found
        """
        line_num = self.tex_line_num(soup_elem)
        if line_num:
            return self.tex_lines[line_num - 1]
        return ''

    def add_headers(self) -> None:
        """Add <h1>, <h2>, etc. headers to the soup based on clues such as font names left by
        make4ht.
        """
        # (Sub)section headers
        header_fonts = ['ptmb8t-x-x-120', 'ptmri8t-x-x-110']
        for h_text in self.soup.find_all('span', attrs={'class': header_fonts}):
            h = h_text.parent
            if h.name == 'p':  # Otherwise already handled
                h['class'] = 'not-numbered'
                number = h.find('span')
                num_text = number.get_text().strip()
                if 'ptmb8t-x-x-120' in number['class']:
                    if num_text.endswith('.') or '.' not in num_text:
                        h.name = 'h1'
                        if h.get_text().lower().strip() == 'abstract':
                            h['class'] = h['class'] + ' AbstractHeading'
                        elif h.get_text().lower().strip() == 'keywords':
                            h['class'] = h['class'] + ' KeywordsHeading'
                            h.find_next('p')['class'] = 'Keywords'
                            h.find_next('p').name = 'div'
                    else:
                        h.name = 'h2'
                elif 'ptmri8t-x-x-110' in number['class']:
                    h.name = 'h3'
        # Title
        title_first = self.soup.find('span', attrs={'class': 'phvb8t-x-x-180'})
        if title_first and '\\maketitle' in self.tex_line(title_first):
            title = title_first.parent
            title['class'] = 'Paper-Title'
            title.name = 'div'

    def add_authors(self) -> None:
        """Parse author information and format the HTML soup a bit to add semantic information
        regarding author names, email addresses, and affiliations.
        """
        meta_section = self.soup.find('div', attrs={'class': 'center'})
        if not meta_section or not meta_section.find('div', attrs={'class': 'tabular'}):
            warn('author_data_missing')
            return
        for tabular in meta_section.find_all('div', attrs={'class': 'tabular'}):
            if not tabular.get_text().strip():
                tabular.decompose()
            else:
                for i, elem in enumerate(tabular.find_all('span')):
                    elem.name = 'div'
                    if i == 0:
                        elem['class'] = 'Author'
                    elif '@' in elem.get_text():
                        elem['class'] = 'E-Mail'
                    else:
                        elem['class'] = 'Affiliations'
                    tabular.insert_before(elem)
                tabular.decompose()

    def merge_elements(self, elem_name: str='span') -> None:
        """Merge consecutive elements that share the same class and (optionally) style; make4ht adds
        many of these.

        Args:
            elem_name (str, optional): Tag name to process. Defaults to 'span'.
        """
        for elem in self.soup.find_all(elem_name, attrs={'class': True}):
            prev = elem.previous_sibling
            if prev and prev.name == elem_name:
                class1 = prev['class'] if prev.has_attr('class') else ''
                class2 = elem['class'] if elem.has_attr('class') else ''
                style1 = prev['style'] if prev.has_attr('style') else ''
                style2 = elem['style'] if elem.has_attr('style') else ''
                if class1 == class2 and style1 == style2:
                    elem.insert(0, prev)
                    prev.unwrap()

    def format_tables(self) -> None:
        """Find table captions, piece them together if needed, and make other table adjustments for
        accessibility and simplicity. Assumes the table header is defined either by an \\hline or
        the first row of the table is the header if it is not clear from \\hline.
        """
        table_tex_regex = re.compile(r'(^|[^\\])\\begin\s*\{table')
        for caption_start in self.soup.find_all(string=re.compile(r'Table\s+\d+:')):
            # Check previous lines for a table environment
            line_num = self.tex_line_num(caption_start)
            for i in range(line_num, 0, -1):
                if table_tex_regex.search(self.tex_lines[i]):
                    break
            else:
                continue
            # Combine all sub-sections (e.g., bold) into one caption
            table_name = caption_start.get_text().strip().split(':')[0]
            while caption_start.parent.name != 'div':  # Rewind to beginning of table container
                caption_start = caption_start.parent
            while caption_start.previous_sibling:
                caption_start = caption_start.previous_sibling  # Usually an anchor at this point
                if isinstance(caption_start, bs4.Tag) and caption_start.find('table'):
                    warn('table_caption_distance', table_name)  # Caption below table
                    break
            caption = self.soup.new_tag('caption')
            caption_start.insert_before(caption)
            while caption.next_sibling and (isinstance(caption.next_sibling, bs4.NavigableString) or
                                            caption.next_sibling.name not in ['div', 'table']):
                caption.append(caption.next_sibling)
            table = caption.find_next('table')  # Move into <table> where it belongs
            if not table:
                continue  # Something went pretty wrong, like caption below table
            table.insert(0, caption)
            # Remove <p>s from table rows
            for p in table.find_all('p'):
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
                thead = self.soup.new_tag('thead')
                if table.find('tr'):
                    table.find('tr').insert_before(thead)
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
            data_tr = [tr for tr in table.find_all('tr') if not tr.find('th') and
                       tr.get_text().strip()]
            hline_tr = table.find_all('tr', attrs={'class': 'hline'})
            if len(data_tr) > len(hline_tr):  # Not \hline every row
                for tr in data_tr[1:]:
                    if tr.previous_sibling and tr.previous_sibling in hline_tr:
                        tr['class'] = 'border-above'
            for tr in table.find_all('tr'):
                if not tr.get_text().strip():
                    tr.decompose()  # Remove remaining decorative rows (bad for accessibility)

    def add_alt_text(self, img_elem: bs4.Tag) -> str:
        """Find alt text (Description command) in LaTeX for an <img> and add it to the image.

        Args:
            img_elem (bs4.Tag): <img> element; e.g., soup.find('img')

        Returns:
            str: Text that was added as the alt text
        """
        alt = None
        env_start, env_end = self.get_tex_environment(self.tex_line_num(img_elem))
        img_elem['alt'] = ''
        for line in self.tex_lines[env_start:env_end + 1]:
            alt = self.get_command_content(line, 'Description')
            if alt:
                img_elem['alt'] = alt[0]
                break
        shared_utils.validate_alt_text(img_elem, img_elem['src'], True)
        return alt[0] if alt else None

    def _fix_figure_text(self, figure: bs4.Tag) -> None:
        # Sometimes part of the image filename or alt text might get included on the <img> line
        for img in figure.find_all('img'):
            el = img.previous_sibling
            while el and (isinstance(el, bs4.NavigableString) or el.sourceline == img.sourceline):
                next_el = el.previous_sibling
                if isinstance(el, bs4.NavigableString) and el.strip():
                    el.replace_with('')
                el = next_el
            el = img.next_sibling
            while el and (isinstance(el, bs4.NavigableString) or el.sourceline == img.sourceline):
                next_el = el.next_sibling
                if isinstance(el, bs4.NavigableString) and el.strip():
                    el.replace_with('')
                el = next_el
        # Move everything non-<img> into the caption
        for p in figure.find_all('p'):
            if p.has_attr('id'):
                anchor = self.soup.new_tag('a', attrs={'id': p['id']})
                p.insert_before(anchor)
            p.unwrap()
        for div in figure.find_all('div'):
            div.name = 'span'  # Change these to spans so we know when we're done (no divs left)
        caption = self.soup.new_tag('figcaption')
        for elem in reversed(figure.contents):
            if isinstance(elem, bs4.NavigableString) or (elem.name != 'figure' and
                                                         elem.name != 'img'):
                caption.insert(0, elem)
        figure.append(caption)
        # Sometomes there is a leftover ":" element for some reason
        caption_remnant = caption.find('span', attrs={'class': 'caption'})
        if caption_remnant and caption_remnant.get_text().strip() == ':':
            caption_remnant.decompose()

    def format_figures(self) -> None:
        """Parse alt text from LaTeX and add it to figures, merge subfigures into a parent <figure>
        element, set image sizes, and do any other minor adjustments needed for figures.
        """
        # First convert any <object>s introduced by SVG conversion to <img>
        width_regex = re.compile(r'width="(\d+)"')
        for obj in self.soup.find_all('object', attrs={'class': 'graphics'}):
            comment = obj.find_next(string=lambda x: isinstance(x, bs4.Comment))
            if comment:
                w = width_regex.search(comment)
                if w:
                    obj['width'] = int(w.group(1))
            obj.name = 'img'
            obj['src'] = obj['data']
            del obj['name']
        for img in self.soup.find_all('img'):
            # Repair double // in img src that happens when using a trailing / with \graphicspath
            img['src'] = img['src'].replace('//', '/')
            # Handle alt text and caption
            alt = self.add_alt_text(img)
            env_start, _ = self.get_tex_environment(self.tex_line_num(img))
            parent = img.parent
            if 'subfigure' in self.tex_lines[env_start]:
                img['class'] = 'subfigure'
                while parent.name != 'div' and parent.name != 'figure':
                    parent = parent.parent
                parent.name = 'figure'
                self._fix_figure_text(parent)  # Handle subfigure caption
                parent = parent.parent  # Go up to next level to handle containing <figure>
            while parent.name != 'div' and parent.name != 'figure':
                parent = parent.parent
            parent.name = 'figure'
            if not parent.find('div'):  # No (more) subfigures to worry about
                if 'subfigure' in self.tex_lines[env_start]:
                    parent['class'] = 'has-subfigures'
                self._fix_figure_text(parent)  # Handle figure caption

            # Set image size class
            if img.has_attr('height'):
                del img['height']  # Fixes wrong width/height proportions; width is more important
            width_in = 3  # Assume medium-ish for "figure" environment
            if img.has_attr('width'):
                width_in = int(img['width']) / 72
                del img['width']
            if 'figure*' in self.tex_lines[env_start]:
                width_in = 5  # Assume large for a "figure*" environment
            shared_utils.set_img_class(img, width_in)

    def format_equations(self) -> None:
        """Replace <table> wrappers for equations with <span> that can by styled with CSS. Tables
        should not be used for layout since an equation is not tabular data.
        """
        # Replace table wrappers for equations, since they are not real tables
        for eq_table in self.soup.find_all('table', attrs={'class': ['equation', 'equation-star']}):
            eq = eq_table.find('td')
            num = eq.next_sibling
            eq_table.insert_before(eq)
            eq.name = 'span'
            eq['class'] = 'math display'
            if num:
                eq.append(num)
                num.name = 'span'
                num['class'] = 'equation-number'
            eq_table.decompose()
            # Repair occasional MathML generation errors (very specific to TexLive version)
            for elem in eq.find_all(['mrow', 'mstyle', 'mtd']):
                for child in elem.contents:
                    if isinstance(child, bs4.NavigableString) and \
                            not isinstance(child, bs4.Comment) and child.strip():
                        if re.match(r'\d.*', child.strip()):
                            child.wrap(self.soup.new_tag('mn'))  # Number
                        elif re.match(r'[\+\-\*\/=><&\|%!\^\(\)\?]', child.strip()):
                            child.wrap(self.soup.new_tag('mo'))  # Operator
                        else:
                            child.wrap(self.soup.new_tag('mi'))  # Identifier

    def fix_fonts(self) -> None:
        """Insert HTML elements where needed to mark up typeface and font options specified by class
        by make4ht. This relies on specific abbreviations for fonts (e.g., "aeb10") and is probably
        very brittle.
        """
        class_elem_map = {
            'aeb10-': 'strong',
            'aeti9-': 'em',
            'phvbo8t-': 'em',  # Title oblique
            'aett9-': 'code',
            'aebxti-': ['strong', 'em'],
        }
        for prefix, name in class_elem_map.items():
            for elem in self.soup.find_all('span',
                                           attrs={'class': lambda x: x and x.startswith(prefix)}):
                if isinstance(name, str):
                    elem.name = name
                else:
                    elem.name = name[-1]
                    for nested in reversed(name[:-1]):
                        wrapper = self.soup.new_tag(nested)
                        elem.insert_before(wrapper)
                        wrapper.append(elem)
                        elem = wrapper
        # Unnecessary styles
        for caption in self.soup.find_all(['caption', 'figcaption']):
            for elem in caption.find_all('strong'):
                elem.unwrap()

    def fix_references(self) -> None:
        """Format the references section. Requires that fonts have already been fixed to make
        finding the references section easier.
        """
        ref_header = shared_utils.get_elem_containing_text(self.soup, 'h1', 'references')
        if not ref_header:
            return  # Already going to warn about this in style check
        new_ref_regex = re.compile(r'\[\d+\]\s*$')
        ref_section = self.soup.new_tag('ol', attrs={'class': 'references'})
        biber_section = ref_header.find_next('dl')
        if biber_section:  # Biber style
            for elem in reversed(biber_section.find_all('dd')):
                if elem.find('p'):
                    elem.p.unwrap()
                ref_section.append(elem)
                elem.name = 'li'
                doi = elem.find('a')
                if doi and not doi['href'].startswith('http'):
                    doi['href'] = 'https://doi.org/' + doi['href']
            biber_section.decompose()
        else:  # Bibtex style
            cur_li = self.soup.new_tag('li')
            ref_section.append(cur_li)
            for elem in reversed(ref_header.find_next('p').contents):
                if isinstance(elem, bs4.NavigableString) and new_ref_regex.search(elem):
                    new_str = new_ref_regex.sub('', elem)
                    if new_str.strip():
                        cur_li.insert(0, new_ref_regex.sub('', elem))
                    elem.replace_with('')
                else:
                    cur_li.insert(0, elem)
                if not isinstance(elem, bs4.NavigableString) and elem.name == 'a' \
                        and not elem.get_text():
                    cur_li = self.soup.new_tag('li')
                    ref_section.insert(0, cur_li)
            # Remove first empty ref number added
            ref_section.find('li').decompose()
        ref_header.insert_after(ref_section)

    def remove_unused_ids(self) -> None:
        """Remove any leftover `id` attributes that are never referenced by `href` values. This must
        be done only *after* we are sure the id attributes are not needed; for example, after CSS
        has been inlined.
        """
        used_ids = [a['href'].replace('#', '')
                    for a in self.soup.find_all('a') if a.has_attr('href')]
        for elem in self.soup.find_all(attrs={'id': lambda x: x and x not in used_ids}):
            del elem['id']
            if elem.name == 'a' and not elem.has_attr('href'):
                elem.decompose()  # Remove unused anchors

    def get_command_content(self, tex_str: str, cmd_name: str) -> list:
        """Find the contents of all occurrences of a LaTeX command, such as "label" or "textbf".
        Does not support commands with [xx] arguments (yet).

        Args:
            tex_str (str): LaTeX code
            cmd_names (str): Command to search for (without preceding slash)

        Returns:
            list of str: content of command{content} for each occurrence of command
        """
        start_regex = re.compile(r'([^\\]|^)\\(' + cmd_name + r')\{')
        cmds = []
        for match in start_regex.finditer(tex_str):
            bracket_depth = 0
            for match_end in range(match.end() - 1, len(tex_str)):
                if tex_str[match_end] == '{':
                    bracket_depth += 1
                elif tex_str[match_end] == '}':
                    bracket_depth -= 1
                    if bracket_depth == 0:
                        break
            cmds.append(tex_str[match.end():match_end])
        return cmds

    def get_tex_environment(self, tex_line_num: int) -> tuple[int, int]:
        """Get the LaTeX environmemt that contains a specified line number, assuming the environment
        consists of a \\begin{something} and \\end{something} pair. If the line number corresponds
        to a begin or end command, that will the environment returned (rather than its parent).

        It will handle nested environments (e.g., for subfigures) by counting the number of begin
        and end commands encountered.

        Args:
            tex_line_num (int): Line number

        Returns:
            tuple[int, int]: Tuple of (begin, end) line numbers
        """
        env_depth = 1
        for start_line_num in range(tex_line_num, -1, -1):
            if self.env_end_regex.search(self.tex_lines[start_line_num]):
                env_depth += 1
            if self.env_start_regex.search(self.tex_lines[start_line_num]):
                env_depth -= 1
                if env_depth == 0:
                    break
        else:
            warn('tex_env_parse_fail', tex_line_num)
        for end_line_num in range(start_line_num, len(self.tex_lines)):
            if self.env_start_regex.search(self.tex_lines[end_line_num]):
                env_depth += 1
            if self.env_end_regex.search(self.tex_lines[end_line_num]):
                env_depth -= 1
                if env_depth == 0:
                    break
        else:
            warn('tex_env_parse_fail', tex_line_num)
        return (start_line_num, end_line_num)
