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

from shared import CONFIG, warn, validate_alt_text, set_img_class, get_elem_containing_text


class MammothParser:
    def __init__(self, docx_path: str, output_dir: str, input_template: str = 'EDM') -> None:
        """Loads a .docx file and provides a number of parsing and processing functions
        that can be used to convert the document to nicer HTML.

        Args:
            docx_path (str): Path to the source .docx file
            output_dir (str): Output directory (must already exist)
            input_template (str): Optional specification of what format is expected
        """
        self.docx_path = docx_path
        self.output_dir = output_dir
        self.input_template = input_template
        self.converted_image_count = 0

        print('Preprocessing docx')
        self.eq_placeholders = self._add_equation_placeholders(docx_path)

        # Load the XML just of the document.xml file, which we will use throughout for
        # finding things that aren't parsed well
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
        # Save initial HTML to a file for development purposes
        with open(os.path.join(self.output_dir, 'tmp-mammoth.html'), 'w') as ofile:
            ofile.write(str(self.soup))

    def _add_equation_placeholders(self, docx_path: str) -> list:
        """Replace equations in document.xml part of a .docx file with randomly
        generated UUIDs. This is necessary because Mammoth does not parse equations and
        drops them, so this way they can be easily found in order by UUID and replaced
        with correctly parsed equations (e.g., from Pandoc). The result will be saved to
        tmp.docx in the output directory.

        Args:
            docx_path (str): Path to .docx file

        Returns:
            list: UUIDs in order of where the equations occurred in the XML
        """
        placeholders = []
        # Regex from github.com/zlqm/docx-equation/blob/master/docx_equation/docx.py
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
        """Use Mammoth to convert the current .docx file for this parser (after
        preprocessing is done) to HTML and load into a BeautifulSoup object.

        Args:
            style_map (str): Style map to use (see Mammoth docs for what this is)

        Returns:
            bs4.BeautifulSoup: Soup of the converted HTML document (body only; no
            <head>, etc.)
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
        """Internal function used for transforming text as it is loaded with Mammoth.
        Currently handles adding <code> tags.

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
        """Process an image by converting the format if needed and saving to a file.
        This is intended to be used as a processing function for
        `mammoth.images.img_element()`.

        Args:
            image (mammoth.transforms.documents.Image): Image to convert/save

        Returns:
            dict: <img> attributes for img_element(), usually {"src": filename}
        """
        self.converted_image_count += 1
        num = str(self.converted_image_count)
        ok_formats = {
            'image/jpeg': '.jpg',
            'image/png': '.png',
            'image/gif': '.gif',
            'image/svg+xml': '.svg',  # Mammoth may use embedded PNG preview anyway :(
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
        """Replace the placeholders we added in for equations (since Mammoth does not
        convert them) with the actual equations, as converted to MathML with Pandoc.

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
        """Check for "charts", a type of figure in DrawingML format that happens when
        you copy a figure from an Excel spreadsheet to Word, for example.
        Some info: http://www.officeopenxml.com/drwOverview.php

        Conversion to another graphical markup language, such as SVG, is not
        straightforward. Thus, this function uses LibreOffice to convert each chart to a
        PDF, then uses the ImageMagick `convert` command to crop the PDF and save as a
        high-density PNG. In the future hopefully we can convert to SVG instead.

        Args:
            pandoc_soup (bs4.BeautifulSoup): Soup parsed by Pandoc (which has chart
            locations)
        """
        chart_spans = pandoc_soup.find_all('span', {'class': 'chart'})
        chart_xmls = bs4.BeautifulSoup(self.xml_txt, 'lxml-xml').find_all('c:chart')
        if len(chart_spans) != len(chart_xmls):
            warn('unexpected', 'Mismatching chart counts: %d, %d' %
                 (len(chart_spans), len(chart_xmls)))
            return

        # For each chart we will create a minimal .docx file with only that chart in it,
        # then convert it with LibreOffice
        with open(os.path.join(CONFIG['utils_dir'], 'chart_convert_doc.xml')) as infile:
            scaffold_soup = bs4.BeautifulSoup(infile, 'lxml-xml')
        denumbering_regex = re.compile(r'\s*(Figure|Fig\.)\s+\d*[:\.]?\s*')
        for chart_i, (chart_span, chart_xml) in enumerate(zip(chart_spans, chart_xmls)):
            print('Converting chart', chart_i + 1)
            drawing = chart_xml.parent
            while drawing.name != 'drawing':
                drawing = drawing.parent
            # Insert drawing into XML scaffold to create new docx with only figure
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
            # Find next caption in Pandoc soup, or parent if the chart is within a
            # caption, then get the caption text and find the corresponding <figcaption>
            # in the Mammoth soup
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
        """Add image size classes and styles (if applicable) based on sizes found in the
        .docx XML source.
        """
        docx_soup = bs4.BeautifulSoup(self.xml_txt, 'lxml-xml')
        for img in self.soup.find_all('img'):
            # Find image in docx based on alt text
            if img.has_attr('alt'):
                drawing = docx_soup.find('wp:docPr', {'descr': img['alt']})
                while drawing.name != 'drawing':
                    drawing = drawing.parent
                width = int(drawing.find('wp:extent')['cx']) / 914400  # To inches
                set_img_class(img, width)

    def check_caption_placement(self) -> None:
        """Check whether or not images have successfully been incorporated into <figure>
        tags with captions.
        """
        for figcaption in self.soup.find_all('figcaption'):
            if not figcaption.parent.find('img'):
                warn('figure_caption_distance', 'Caption text: "' + figcaption.get_text() + '"')

    def fix_references(self) -> None:
        """Standardize formatting of references."""
        ref_heading = get_elem_containing_text(self.soup, 'h1', 'references', True)
        if not ref_heading:
            return  # Already going to warn about this
        if ref_heading.next_sibling and ref_heading.next_sibling.name == 'ol':
            return  # Already fine
        ol = self.soup.new_tag('ol')
        ref_heading.insert_after(ol)
        if self.input_template == 'EDM':
            num_regex = re.compile(r'\[\d+\]\s*')
            while ol.next_sibling and ol.next_sibling.name == 'p' and \
                    ol.next_sibling.get_text(strip=True):
                ref = ol.next_sibling
                ref.name = 'li'
                ol.append(ref)
                if isinstance(ref.contents[0], bs4.NavigableString):
                    ref.contents[0].replace_with(num_regex.sub('', ref.contents[0]))
        elif self.input_template == 'JEDM':
            while ol.next_sibling and ol.next_sibling.name == 'p' and \
                    ol.next_sibling.has_attr('class') and \
                    'ReferenceItem' in ol.next_sibling['class']:
                ref = ol.next_sibling
                ref.name = 'li'
                ol.append(ref)

    def format_authors(self) -> None:
        """Do any formatting fixes that can be managed for author info, though if the
        template is followed exactly this is typically unnecessary.
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
            wrapper.decompose()  # This works even if the wrapper is already decomposed
        # Remove blank authors (e.g., because of Author style misapplied to whitespace)
        for elem in self.soup.find_all('div', attrs={'class': lambda c: c in info_styles}):
            if not elem.get_text(strip=True):
                elem.decompose()
