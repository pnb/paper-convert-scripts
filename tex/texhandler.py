import re

import bs4

import shared_utils
from shared_utils import warn_tex as warn
from make4ht_utils import get_command_content


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
        may be imprecise for commands like \\maketitle that rely on many other lines.

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

    def find_image_line_num(self, starting_line_num: int, fname: str) -> int:
        """Find a LaTeX line number after a given line number that includes a specific image file
        (ignoring the extension which may differ due to conversion). Useful for cases where Make4ht
        does not provide the latest line number.

        Args:
            starting_line_num (int): Starting point, usually from `tex_line_num()`
            fname (str): Filename to look for (case insensitive)

        Returns:
            int: Line number, or starting line number if the image was not found
        """
        prefix = fname.lower()
        if '.' in prefix:
            prefix = prefix[:prefix.rfind('.')]
        for i in range(starting_line_num - 1, len(self.tex_lines)):
            curline = self.tex_lines[i].lower()
            if R'\includegraphics' in curline and '{' + prefix in curline:
                return i + 1
        return starting_line_num

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
            if h.name == 'p':  # Otherwise already handled (abstract, etc.)
                h['class'] = 'not-numbered'
                num_text = h_text.get_text().strip()
                if 'ptmb8t-x-x-120' in h_text['class']:
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
                elif 'ptmri8t-x-x-110' in h_text['class']:
                    h.name = 'h3'
        # Title
        title_first = self.soup.find('span', attrs={'class': 'phvb8t-x-x-180'})
        if title_first and '\\maketitle' in self.tex_line(title_first):
            title = title_first.parent
            title['class'] = 'Paper-Title'
            title.name = 'div'

    def merge_elements(self, elem_name: str = 'span') -> None:
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

    def add_alt_text(self, img_elem: bs4.Tag) -> str:
        """Find alt text (Description command) in LaTeX for an <img> and add it to the image.

        Args:
            img_elem (bs4.Tag): <img> element; e.g., soup.find('img')

        Returns:
            str: Text that was added as the alt text
        """
        env_start, env_end = self.get_tex_environment(self.tex_line_num(img_elem))
        tex_section = '\n'.join(self.tex_lines[env_start:env_end + 1])
        alts = get_command_content(tex_section, 'Description')
        img_i = img_elem.parent.find_all('img').index(img_elem)
        if img_elem.has_attr('alt'):  # Make4ht defaults to "PIC" which is not real alt text
            del img_elem['alt']
        if len(alts) > img_i:
            img_elem['alt'] = alts[img_i]
        shared_utils.validate_alt_text(img_elem, img_elem['src'], True)
        return img_elem['alt'] if img_elem.has_attr('alt') else None

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
            while el and (isinstance(el, bs4.NavigableString) or
                          el.sourceline == img.sourceline and el.name != 'a'):
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
        # Sometimes there is a leftover ":" element for some reason
        caption_remnant = caption.find('span', attrs={'class': ['caption', 'id']})
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
            if img['src'].startswith('tmp-make4ht'):  # Generated image
                if img.has_attr('class') and 'oalign' in img['class']:
                    img.decompose()  # Artifact of some LaTeX alignment function
                    continue
                elif img.has_attr('alt') and 'Algorithm' in img['alt']:
                    continue  # Skip over images generated of algorithm listings
            if img.parent.has_attr('class') and 'centerline' in img.parent['class']:
                img.parent.unwrap()  # Remove extra div added if somebody uses \centerline
            # Repair double // in img src that happens when using a trailing / with \graphicspath
            img['src'] = img['src'].replace('//', '/')
            # Handle alt text and caption
            self.add_alt_text(img)
            img_text_line_num = self.tex_line_num(img)
            img_text_line_num = self.find_image_line_num(img_text_line_num, img['src'])
            env_start, _ = self.get_tex_environment(img_text_line_num)
            parent = img.parent
            subfigure_wrapper = img.find_parent('div', attrs={'class': 'subfigure'})
            if 'subfigure' in self.tex_lines[env_start] or subfigure_wrapper:
                if subfigure_wrapper:
                    for wrapper in subfigure_wrapper.find_all(['table', 'tr', 'td']):
                        wrapper.unwrap()
                img['class'] = 'subfigure'
                parent = img.find_parent(['div', 'figure'])
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
            if 'scale=' in self.tex_lines[img_text_line_num - 1] and img.has_attr('width'):
                del img['width']  # Using scale= leads to tiny width, so we just have to skip it
            width_in = 3  # Assume medium-ish for "figure" environment
            if img.has_attr('width'):
                width_in = int(img['width']) / 72
                del img['width']
                if 'subfigure' in self.tex_lines[env_start] or subfigure_wrapper:
                    width_in = width_in * .8  # Assume subfigures should be a bit smaller
            if 'figure*' in self.tex_lines[env_start] and len(parent.find_all('img')) == 1:
                width_in = 5  # Assume large for a "figure*" environment with 1 image
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
            for elem in eq.find_all('mo'):
                if all(isinstance(c, bs4.Tag) and c.name == 'mtr' for c in elem.contents):
                    elem.unwrap()  # Extraneous <mo> surrounding <mtr> elements
                elif re.match(r'[a-zA-Z]', elem.get_text(strip=True)):
                    elem.name = 'mi'  # Identifier, not operator (e.g., first letter in MSE)

    def fix_fonts(self) -> None:
        """Insert HTML elements where needed to mark up typeface and font options specified by class
        by make4ht. This relies on specific abbreviations for fonts (e.g., "aeb10") and is probably
        very brittle.
        """
        class_elem_map = {
            'aeb10-': 'strong',
            'aeti9-': 'em',
            'aeti7-': 'em',
            'phvbo8t-': 'em',  # Title oblique
            'aett9-': 'code',
            'ectt-': 'code',
            'ectc-': 'code',
            'aebxti-': ['strong', 'em'],
            'aer-7': None,  # Unwrap; not a good/necessary style to keep (tiny text)
        }
        for prefix, name in class_elem_map.items():
            for elem in self.soup.find_all('span',
                                           attrs={'class': lambda x: x and x.startswith(prefix)}):
                if not name:
                    elem.unwrap()
                elif isinstance(name, str):
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
        new_ref_regex = re.compile(r'\[\d+\]\s*')
        ref_section = self.soup.new_tag('ol', attrs={'class': 'references'})
        biber_section = ref_header.find_next('dl')
        if biber_section:  # Biber style
            for elem in reversed(biber_section.find_all('dd')):
                if elem.find('p'):
                    elem.p.unwrap()
                ref_section.append(elem)
                elem.name = 'li'
                doi = elem.find('a')
                if doi and doi.has_attr('href') and not doi['href'].startswith('http'):
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

    def get_tex_environment(self, tex_line_num: int) -> "tuple[int, int]":
        """Get the LaTeX environment that contains a specified line number, assuming the environment
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
