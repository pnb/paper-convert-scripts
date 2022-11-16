# Functionality specific to docx conversion with Mammoth
import subprocess
import os
import zipfile
import re
import uuid
import copy

import bs4
import mammoth
import PIL.Image

from shared_utils import CONFIG, warn, validate_alt_text, set_img_class, get_elem_containing_text


class MammothParser:
    def __init__(self, docx_path: str, output_dir: str) -> None:
        """Loads a .docx file and provides a number of parsing and processing functions that can be
        used to convert the document to nicer HTML.

        Args:
            docx_path (str): Path to the source .docx file
            output_dir (str): Output directory (must already exist)
        """
        self.docx_path = docx_path
        self.output_dir = output_dir
        self.converted_image_count = 0

        print('Preprocessing docx')
        self.eq_placeholders = self._add_equation_placeholders(docx_path)

        # Load the XML just of the document.xml file, which we will use throughout for finding
        # things that aren't parsed well
        with zipfile.ZipFile(docx_path) as infile:
            self.xml_txt = infile.read('word/document.xml').decode('utf8')

        xml_soup = bs4.BeautifulSoup(self.xml_txt, 'lxml-xml')
        for wingdings_tag in xml_soup.find_all('w:rFonts', attrs={'w:ascii': 'Wingdings'}):
            run = wingdings_tag.parent
            while run and run.name != 'r':
                run = run.parent
            if run:
                warn('wingdings', run.get_text(strip=True))

        print('Loading via Mammoth')
        with open(os.path.join(CONFIG['utils_dir'], 'mammoth_style_map.txt')) as infile:
            style_map = infile.read()
        self.soup = self._load_docx_soup(style_map)

    def _add_equation_placeholders(self, docx_path: str) -> list:
        """Replace equations in document.xml part of a .docx file with randomly generated UUIDs.
        This is necessary because Mammoth does not parse equations and drops them, so this way they
        can be easily found in order by UUID and replaced with correctly parsed equations (e.g.,
        from Pandoc). The result will be saved to tmp.docx in the output directory.

        Args:
            docx_path (str): Path to .docx file

        Returns:
            list: UUIDs in order of where the equations occurred in the XML
        """
        placeholders = []
        # Regex from https://github.com/zlqm/docx-equation/blob/master/docx_equation/docx.py
        omath_pattern = re.compile(
            r'(<m:oMathPara[^<>]*>.+?</m:oMathPara>|<m:oMath[^<>]*>.+?</m:oMath>)', flags=re.DOTALL)
        with zipfile.ZipFile(docx_path) as infile:
            with zipfile.ZipFile(os.path.join(self.output_dir, 'tmp.docx'), 'w') as outfile:
                outfile.comment = infile.comment
                for f in infile.infolist():
                    xml = infile.read(f)
                    if f.filename in ['word/document.xml', 'word/footnotes.xml']:
                        txt = xml.decode('utf8')
                        while re.search(omath_pattern, txt):
                            placeholders.append(str(uuid.uuid4()).replace('-', ''))
                            placeholder = '<w:r><w:t>' + placeholders[-1] + '</w:t></w:r>'
                            txt = re.sub(omath_pattern, placeholder, txt, count=1)
                        xml = txt.encode('utf8')
                    outfile.writestr(f, xml)
        return placeholders

    def _load_docx_soup(self, style_map: str) -> bs4.BeautifulSoup:
        """Use Mammoth to convert the current .docx file for this parser (after preprocessing is
        done) to HTML and load into a BeautifulSoup object.

        Args:
            style_map (str): Style map to use (see Mammoth docs for what this is)

        Returns:
            bs4.BeautifulSoup: Soup of the converted HTML document (body only; no <head>, etc.)
        """
        with open(os.path.join(self.output_dir, 'tmp.docx'), 'rb') as infile:
            result = mammoth.convert_to_html(
                infile, style_map=style_map,
                transform_document=mammoth.transforms.paragraph(self._transform_paragraph),
                convert_image=mammoth.images.img_element(self._convert_image))
            if len(result.messages):
                print('\n'.join(m.message for m in result.messages))
            soup = bs4.BeautifulSoup(result.value, 'html.parser')

        # Unwrap <p><img></p> into <img> to make navigating through images easier
        for img in soup.find_all('img'):
            if img.parent.name == 'p' and all(c.name == 'img' for c in img.parent.find_all()):
                img.parent.unwrap()

        return soup

    def _transform_paragraph(self, paragraph: mammoth.transforms.documents.Paragraph) -> \
            mammoth.transforms.documents.Paragraph:
        """Internal function used for transforming text as it is loaded with Mammoth. Currently
        handles adding <code> tags.

        Args:
            paragraph (mammoth.transforms.documents.Paragraph): Text to transform

        Returns:
            mammoth.transforms.documents.Paragraph: Transformed text
        """
        monospace_fonts = set(["consolas", "courier", "courier new"])
        runs = mammoth.transforms.get_descendants_of_type(paragraph, mammoth.documents.Run)
        if runs and all(run.font and run.font.lower() in monospace_fonts for run in runs):
            return paragraph.copy(style_id="code", style_name="Code")
        return paragraph

    def _convert_image(self, image: mammoth.transforms.documents.Image) -> dict:
        """Process an image by converting the format if needed and saving to a file. This is
        intended to be used as a processing function for mammoth.images.img_element().

        Args:
            image (mammoth.transforms.documents.Image): Image to convert/save

        Returns:
            dict: <img> attributes as expected by img_element(), usually {'src': filename}
        """
        self.converted_image_count += 1
        num = str(self.converted_image_count)
        ok_formats = {
            'image/jpeg': '.jpg',
            'image/png': '.png',
            'image/gif': '.gif',
            'image/svg+xml': '.svg',  # Mammoth may choose embedded PNG preview version anyway :(
        }
        with image.open() as image_bytes:
            if image.content_type in ['image/tiff', 'image/bmp']:
                PIL.Image.open(image_bytes).save(os.path.join(self.output_dir, num + '.png'))
                image.content_type = 'image/png'
                return {'src': num + '.png'}
            if image.content_type in ok_formats.keys():
                fname = num + ok_formats[image.content_type]
                with open(os.path.join(self.output_dir, fname), 'wb') as ofile:
                    ofile.write(image_bytes.read())
                return {'src': fname}
            if image.content_type in ['image/x-emf', 'image/x-wmf']:
                print('Converting EMF/WMF image to PNG')
                if image.content_type == 'image/x-wmf':
                    warn('wmf_images')
                fname = os.path.join(self.output_dir, num) + '.' + image.content_type[-3:]
                with open(os.path.join(fname), 'wb') as ofile:
                    ofile.write(image_bytes.read())
                subprocess.call([CONFIG['inkscape_path'], '--export-type=png', '--export-dpi=600',
                                fname], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                os.unlink(fname)
                return {'src': num + '.png'}
            warn('unknown_image_type', image.content_type)

    def add_pandoc_equations(self, pandoc_soup: bs4.BeautifulSoup) -> None:
        """Replace the placeholders we added in for equations (since Mammoth does not convert them)
        with the actual equations, as converted to MathML with Pandoc.

        Args:
            pandoc_soup (bs4.BeautifulSoup): Document converted to HTML with Pandoc
        """
        equations = pandoc_soup.find_all('math')
        if len(equations) != len(self.eq_placeholders):
            warn('unexpected', 'Could not convert equations')
            return
        for m_uuid, p_eq in zip(self.eq_placeholders, equations):
            m_eq = self.soup.find(string=re.compile(m_uuid))  # Get containing element
            before, after = m_eq.split(m_uuid)  # Extract any text before/after the UUID
            before = self.soup.new_string(before)
            m_eq.replace_with(before)  # Replace everything with "before" text (if any)
            before.insert_after(p_eq)  # Add equation
            p_eq.insert_after(after)   # Add any text after

    def process_captions(self) -> None:
        """Find captions, check that they match expectations for figures and tables, and move the
        caption elements inside the <table> or <figure> element where they should be.
        """
        caption_regex = re.compile(r'\s*(Figure|Fig\.|Table)\s+(.)')
        figure_counter = 0
        table_counter = 0
        for elem in self.soup.find_all('caption'):
            match = re.match(caption_regex, elem.get_text())
            # Assign the appropriate HTML tag depending on whether it is a figure or table
            if not match:  # Caption text doesn't match expectations
                caption_text = '"' + elem.get_text() + '"' if elem.get_text(strip=True) else 'BLANK'
                if caption_text == 'BLANK':
                    prev_text = ''
                    for prev_elem in elem.previous_elements:
                        prev_text = prev_elem.get_text(strip=True)
                        if prev_text:
                            break
                    next_text = ''
                    for next_elem in elem.next_elements:
                        next_text = next_elem.get_text(strip=True)
                        if next_text:
                            break
                    caption_text += '; text before: "' + prev_text + '" after: "' + next_text + '"'
                warn('unknown_caption_type', "Caption text: " + caption_text)
            elif match.group(1) == 'Table':  # Already a <caption> (for tables)
                table_counter += 1
                new_num = table_counter
                # Check that this <table> immediate follows the caption; otherwise they might have
                # done something like used an image of a table, put the caption below the table, or
                # put the caption inside the table
                check_in_table = elem.parent
                while check_in_table:
                    if check_in_table.name == 'tr':
                        warn('caption_in_table', 'Caption text: "' + elem.get_text() + '"')
                    check_in_table = check_in_table.parent
                table = elem.find_next('table')
                if not table or table.sourceline - elem.sourceline > 2:
                    warn('table_caption_distance', 'Caption text: "' + elem.get_text() + '"')
                elif table:
                    table.insert(0, elem)  # Move table <caption> inside <table> where it belongs
                if isinstance(elem.next_sibling, bs4.Tag) and elem.next_sibling.name == 'img':
                    warn('image_as_table', 'Caption text: "' + elem.get_text() + '"')
            else:  # Change to <figcaption> for figures
                elem.name = 'figcaption'
                figure_counter += 1
                new_num = figure_counter
                # Move <figcaption> inside a new <figure> containing the <img>(s)
                new_fig = self.soup.new_tag('figure')
                elem.insert_after(new_fig)
                if elem.find_parent('tr'):
                    warn('caption_in_table', 'Caption text: "' + elem.get_text() + '"')
                for img in elem.find_all('img'):  # Any images inside the same "Caption" paragraph
                    new_fig.append(img)
                img = elem.previous_sibling
                while img and ((isinstance(img, bs4.NavigableString) and not img.strip()) or
                               img.name == 'img' or img.name == 'a' or
                               (img.name == 'p' and img.find('img'))):
                    next_img = img.previous_sibling
                    new_fig.insert(0, img)
                    img = next_img
                # Unwrap images from <p> and other containers if needed
                for wrapper in new_fig.find_all(['p', 'em', 'strong']):
                    wrapper.unwrap()
                for br in new_fig.find_all('br'):
                    br.decompose()
                new_fig.append(elem)
            # Number figures and tables if the numbers have gotten dropped
            if match and not match.group(2).isdigit():
                txt = elem.find(string=caption_regex)
                suffix = '.' if match.group(2) == '.' else '. ' + match.group(2)
                numbered_txt = re.sub(caption_regex, r'\1 ' + str(new_num) + suffix, txt, count=1)
                txt.replace_with(numbered_txt)
            elif match and elem.get_text()[match.end(0)] != '.':
                warn('no_caption_number_period', match.group(0))

    def crop_images(self) -> None:
        """Crop images, if needed, and check that each one has a valid alt text set.
        """
        docx_soup = bs4.BeautifulSoup(self.xml_txt, 'lxml-xml')  # From which we will get crop info
        for img in self.soup.find_all('img'):
            if not validate_alt_text(img, img['src']):
                continue
            # Crop images if needed, where possible (find them based on alt text -- sort of hacky)
            xml_elem = docx_soup.find('pic:cNvPr', attrs={'descr': img['alt']})
            if not xml_elem:
                continue  # Only happens in strange cases, might indicate alt-text problem?
            drawing = xml_elem.find_parent('drawing')  # Find parent <w:drawing> element
            crop = drawing.find('a:srcRect')  # Find crop element if it exists
            # Crop coordinates are given as proportions * 100k
            t = int(crop['t']) / 100000 if crop and crop.has_attr('t') else 0
            r = int(crop['r']) / 100000 if crop and crop.has_attr('r') else 0
            b = int(crop['b']) / 100000 if crop and crop.has_attr('b') else 0
            l = int(crop['l']) / 100000 if crop and crop.has_attr('l') else 0
            if t + r + b + l:  # Crop may be missing/empty, so let's check if it is even needed
                if img['src'][-4:] in ['.jpg', '.png', '.gif']:  # Crop image itself
                    fname = os.path.join(self.output_dir, img['src'])
                    pil_image = PIL.Image.open(fname)
                    width, height = pil_image.size
                    crop_box = (l * width, t * height, width - r * width, height - b * height)
                    print('Cropping image file:', img['src'], 'LTRB:', crop_box)
                    pil_image = pil_image.crop(box=crop_box)
                    pil_image.save(fname)
                else:  # Do crop with an HTML element (for SVG)
                    pass

    def check_tables(self) -> None:
        """Check that tables have captions and appropriate header and text styles set.
        """
        for i, table in enumerate(self.soup.find_all('table')):
            if len(table.find_all('tr')) == 1:  # Single row presentation table
                table['role'] = 'presentation'
            else:
                if not table.find('caption'):
                    warn('table_caption_missing', 'Table index ' + str(i + 1) + '; table text: "' +
                         table.get_text(strip=True)[:15] + '..."')
                if not table.find('thead'):
                    warn('table_header_missing', 'Table index ' + str(i + 1) + '; table text: "' +
                         table.get_text(strip=True)[:15] + '..."')
                for p in table.find_all('p'):
                    if not p.has_attr('class') or ('table-text' not in p['class'] and
                                                   'table-header' not in p['class']):
                        warn('table_styles_missing', 'Table index ' + str(i + 1) + '; text: "' +
                             p.get_text(strip=True) + '"')
                        break
            for td in table.find_all('td', attrs={'rowspan': True}):
                td['class'] = 'has-rowspan'  # Mark rowspan cells so they can be styled

    def format_footnotes(self) -> None:
        """Apply some formatting to the footnotes section, if it exists.
        """
        first_footnote = self.soup.find('li', attrs={'id': 'footnote-1'})
        if not first_footnote:
            return
        footnote_section = first_footnote.parent
        separator = self.soup.new_tag('hr')
        footnote_section.insert_before(separator)

    def convert_drawingml(self, pandoc_soup: bs4.BeautifulSoup) -> None:
        """Check for "charts", a type of figure in DrawingML format that happens when you copy a
        figure from an Excel spreadsheet to Word, for example.
        Some info: http://www.officeopenxml.com/drwOverview.php

        Conversion to another graphical markup language, such as SVG, is not straightforward. Thus,
        this function uses LibreOffice to convert each chart to a PDF, then uses the ImageMagick
        `convert` command to crop the PDF and save as a high-density PNG. In the future hopefully we
        can convert to SVG instead.

        Args:
            pandoc_soup (bs4.BeautifulSoup): Soup parsed by Pandoc (which has chart locations)
        """
        chart_spans = pandoc_soup.find_all('span', {'class': 'chart'})
        chart_xmls = bs4.BeautifulSoup(self.xml_txt, 'lxml-xml').find_all('c:chart')
        if len(chart_spans) != len(chart_xmls):
            warn('unexpected', 'Mismatching chart counts: %d, %d' %
                 (len(chart_spans), len(chart_xmls)))
            return

        # For each chart we will create a minimal .docx file with only that chart in it, then
        # convert it with LibreOffice
        with open(os.path.join(CONFIG['utils_dir'], 'chart_convert_doc.xml')) as infile:
            scaffold_soup = bs4.BeautifulSoup(infile, 'lxml-xml')
        denumbering_regex = re.compile(r'\s*(Figure|Fig\.)\s+\d*[:\.]?\s*')
        for chart_i, (chart_span, chart_xml) in enumerate(zip(chart_spans, chart_xmls)):
            print('Converting chart', chart_i + 1)
            drawing = chart_xml.parent
            while drawing.name != 'drawing':
                drawing = drawing.parent
            # Insert drawing into XML document scaffold to create new docx with only figure
            scaffold_soup.find('w:drawing').replace_with(copy.copy(drawing))
            with zipfile.ZipFile(self.docx_path) as infile:
                with zipfile.ZipFile(os.path.join(self.output_dir, 'tmp.docx'), 'w') as outfile:
                    outfile.comment = infile.comment
                    for f in infile.infolist():
                        xml = infile.read(f)
                        if f.filename == 'word/document.xml':
                            xml = str(scaffold_soup).replace('\n', '').encode('utf8')
                        outfile.writestr(f, xml)
            # Convert figure docx to PDF
            subprocess.call([
                CONFIG['libreoffice_path'], '--headless', '--convert-to', 'pdf',
                os.path.join(self.output_dir, 'tmp.docx'), '--outdir', self.output_dir
            ], stdout=subprocess.DEVNULL)
            # Convert figure PDF to PNG and crop to figure part of PDF page
            subprocess.call([
                'convert', '-trim', '-density', '600', '-colorspace', 'RGB',
                os.path.join(self.output_dir, 'tmp.pdf'),
                '-shave', '1x1', '-trim',  # Shave 1px off the edges and trim again
                os.path.join(self.output_dir, 'chart' + str(chart_i + 1) + '.png')
            ], stdout=subprocess.DEVNULL)
            # Find alt text
            descr = drawing.find('wp:docPr', {'descr': True})
            alt = descr['descr'] if descr else ''
            # Insert new figure into soup
            img = self.soup.new_tag('img', alt=alt, src='chart' + str(chart_i + 1) + '.png')
            validate_alt_text(img, 'chart index' + str(chart_i))
            # Find next caption in Pandoc soup, or parent if the chart is within a caption, then get
            # the caption text and find the corresponding <figcaption> in the Mammoth soup
            caption = chart_span.find_parent('div', {'data-custom-style': 'caption'})
            if caption and caption.sourceline > chart_span.sourceline:
                caption = None  # Incorrect match
            if not caption:
                caption = chart_span.find_next('div', {'data-custom-style': 'caption'})
            if not caption:
                warn('chart_caption_not_found', 'Chart with alt text "' + alt + '"')
                continue
            if abs(caption.sourceline - chart_span.sourceline) > 5:
                warn('chart_caption_distance', 'Chart with alt text "' + alt + '"')
            chart_span.decompose()  # Remove [CHART], which may be part of the caption
            caption_text = re.sub(denumbering_regex, '', caption.get_text(strip=True))
            if not caption_text:
                warn('figure_caption_blank', 'Near chart with alt text "' + alt + '"')
                continue
            for cap in self.soup.find_all('figcaption'):
                if re.sub(denumbering_regex, '', cap.get_text(strip=True)) == caption_text:
                    cap.insert_before(img)
                    break
            else:
                warn('unexpected', 'Could not match caption: Chart alt text "' + alt + '"')

    def set_image_sizes(self) -> None:
        """Add image size classes and styles (if applicable) based on sizes found in the .docx XML
        source.
        """
        docx_soup = bs4.BeautifulSoup(self.xml_txt, 'lxml-xml')
        for img in self.soup.find_all('img'):
            # Find image in docx based on alt text
            if img.has_attr('alt'):
                drawing = docx_soup.find('wp:docPr', {'descr': img['alt']})
                while drawing.name != 'drawing':
                    drawing = drawing.parent
                width = int(drawing.find('wp:extent')['cx']) / 914400  # Convert width to inches
                set_img_class(img, width)

    def check_caption_placement(self) -> None:
        """Check whether or not images have successfully been incorporated into <figure> tags with
        captions.
        """
        for figcaption in self.soup.find_all('figcaption'):
            if not figcaption.parent.find('img'):
                warn('figure_caption_distance', 'Caption text: "' + figcaption.get_text() + '"')

    def fix_references(self) -> None:
        """Standardize formatting of references.
        """
        ref_header = get_elem_containing_text(self.soup, 'h1', 'references')
        if not ref_header:
            return  # Already going to warn about this
        if ref_header.next_sibling and ref_header.next_sibling.name == 'ol':
            return  # Already fine
        ol = self.soup.new_tag('ol')
        ref_header.insert_after(ol)
        num_regex = re.compile(r'\[\d+\]\s*')
        while ol.next_sibling and ol.next_sibling.name == 'p' and \
                ol.next_sibling.get_text(strip=True):
            ref = ol.next_sibling
            ref.name = 'li'
            ol.append(ref)
            if isinstance(ref.contents[0], bs4.NavigableString):
                ref.contents[0].replace_with(num_regex.sub('', ref.contents[0]))

    def format_authors(self) -> None:
        """Do any formatting fixes that can be managed for author info, though if the template is
        followed exactly this is typically unnecessary.
        """
        # If the author info is in a table, undo that
        info_styles = ['Author', 'Affiliations', 'E-Mail']
        wrappers = []
        for elem in self.soup.find_all('div', attrs={'class': lambda c: c in info_styles}):
            wrapper = elem.find_parent('table')
            if wrapper:
                wrapper.insert_before(elem)
                wrappers.append(wrapper)
        for wrapper in wrappers:
            wrapper.decompose()  # This works even if the wrapper has already decomposed
        # Remove any blank authors (e.g., because of Author style misapplied to whitespace)
        for elem in self.soup.find_all('div', attrs={'class': lambda c: c in info_styles}):
            if not elem.get_text(strip=True):
                elem.decompose()
