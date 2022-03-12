import csv
import os
import json
import re

import bs4


with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'config.json')) as infile:
    CONFIG = json.load(infile)
    CONFIG['utils_dir'] = os.path.dirname(os.path.realpath(__file__))


def warn(warning_name: str, extra_info: str='', tex: bool=False) -> None:
    """Display and record a warning, as defined in config.json. If `tex` is True, any keys/values in
    the "tex" key of the warning in config.json will overwrite the default message; see warn_tex().

    Extra information may be provided to help fix this specific instance of the warning; for
    example, to include a line number or table number.

    Args:
        warning_name (str): Key from the "warnings" object in config.json
        extra_info (str, optional): Information useful for debugging this warning. Defaults to ''.
        tex (bool, optional): Use LaTeX key/value, if it exists. Defaults to False.

    Raises:
        NotImplementedError: Indicates warning_name is not defined in config.json's "warnings"
    """
    if not hasattr(warn, 'output_filename'):
        raise KeyError('warn.output_filename must be set to a CSV file path')
    if warning_name not in CONFIG['warnings'].keys():
        raise NotImplementedError(warning_name, 'is not implemented; check spelling or implement')
    if not os.path.exists(warn.output_filename):
        with open(warn.output_filename, 'w', encoding='utf8') as ofile:
            ofile.write('warning_name,extra_info,is_tex\n')
    with open(warn.output_filename, 'a', encoding='utf8') as ofile:
        writer = csv.writer(ofile, lineterminator='\n')
        writer.writerow([warning_name, extra_info, int(tex)])
    message = CONFIG['warnings'][warning_name]['message']
    if tex and 'tex' in CONFIG['warnings'][warning_name].keys() and \
            'message' in CONFIG['warnings'][warning_name]['tex']:
        message = CONFIG['warnings'][warning_name]['tex']['message']
    if extra_info:
        extra_info = '\n    └> ' + str(extra_info)
    print('Conversion warning:', message, extra_info)


def warn_tex(warning_name: str, extra_info: str='') -> None:
    """Run warn() with `tex = True`. This is useful for shorthand, e.g., `import warn_tex as warn`.
    See warn() documentation for full description.

    Args:
        warning_name (str): Key from the "warnings" object in config.json
        extra_info (str, optional): Information useful for debugging this warning. Defaults to ''.
    """
    warn(warning_name, extra_info, True)


def get_elem_containing_text(soup: bs4.BeautifulSoup, tagname: str, text: str) -> bs4.Tag:
    """Find a BeautifulSoup element containing some specific text. For example, one could find the
    "References" h1 element. Text matching is case insensitive.

    Args:
        soup (bs4.BeautifulSoup): Soup or Tag to search within
        tagname (str): Name of tag, e.g., h1, div to look for
        text (str): Text to search for (case insensitive)

    Returns:
        bs4.Tag: Element containing the specified text, or None if not found
    """
    regex = re.compile(r'.*' + text + r'.*', re.IGNORECASE)
    for elem in soup.find_all(tagname):
        if regex.match(elem.get_text()):
            return elem
    return None


def check_styles(soup: bs4.BeautifulSoup) -> None:
    """Check the `soup` object to see if it has most of the expected elements with the appropriate
    styles, and trigger warnings if not. This is intended as one of the last steps, after
    postprocessing.

    Args:
        soup (bs4.BeautifulSoup): Processed paper
    """
    if not soup.find('div', attrs={'class': lambda x: x and 'Paper-Title' in x}):
        warn('style_paper_title')
    if not soup.find('h1', attrs={'class': lambda x: x and 'AbstractHeading' in x}):
        warn('style_abstract_heading')
    if not soup.find('h1', attrs={'class': lambda x: x and 'KeywordsHeading' in x}):
        warn('style_keywords_heading')
    if not soup.find('div', attrs={'class': lambda x: x and 'Keywords' in x}):
        warn('style_keywords')
    num_authors = len(soup.find_all('div', attrs={'class': lambda x: x and 'Author' in x}))
    num_affil = len(soup.find_all('div', attrs={'class': lambda x: x and 'Affiliations' in x}))
    num_emails = len(soup.find_all('div', attrs={'class': lambda x: x and 'E-Mail' in x}))
    if not num_authors:
        warn('style_author')
    if not num_affil:
        warn('style_affiliations')
    if not num_emails:
        warn('style_email')
    # Check headings
    if not get_elem_containing_text(soup, 'h1', 'introduction'):
        warn('style_no_intro')
    if not get_elem_containing_text(soup, 'h1', 'references'):
        warn('style_no_refs')


def validate_alt_text(img_elem: bs4.Tag, identifying_text: str, tex: bool=False) -> bool:
    """Check if the alt text for this <img> element meets expectations. Triggers warnings if not.

    Args:
        img_elem (bs4.Tag): An <img> element to check, e.g., from `soup.find('img')`
        identifying_text (str): Some helpful information to help identify this image
        tex (bool): Whether or not to trigger LaTeX warnings, if there are any warnings

    Returns:
        bool: True if the alt text seems OK, False if some serious issue was found
    """
    if not img_elem.has_attr('alt') or not img_elem['alt']:
        warn('alt_text_missing', identifying_text, tex)
        return False
    elif len(img_elem['alt']) > 150:
        warn('alt_text_long', img_elem['alt'], tex)
        return True  # Not good but not a deal breaker, so don't stop processing the image
    return True


def set_img_class(img_elem: bs4.Tag, width_inches: float) -> None:
    """Set the size of an <img> element using a CSS class, unless it is very small in which case
    the exact size will be used.

    Args:
        img_elem (bs4.Tag): <img> element; e.g., `soup.find('img')`
        width_inches (float): Image width in inches
    """
    # TODO: automatically check DPI on rasterized figures, warn on small DPI
    cur_class = img_elem['class'] if img_elem.has_attr('class') else ''
    if isinstance(cur_class, list):
        cur_class = ' '.join(cur_class)
    if width_inches < 1:  # Very small image; just use exact size
        img_elem['style'] = 'width:' + str(width_inches) + 'in;'
    elif width_inches < 2:
        img_elem['class'] = cur_class + ' img-small'
    elif width_inches < 4:
        img_elem['class'] = cur_class + ' img-medium'
    else:
        img_elem['class'] = cur_class + ' img-large'


def position_figures_tables(soup: bs4.BeautifulSoup) -> None:
    """Move tables and figures to the end of the next (sub)section, unless they are subfigures (as
    identified with the data-subfigure=1 property) or have data-position-here=1 set. Moving figures
    and tables may be necessary for two-column docx objects that occur in the XML before their
    position in the layout or for LaTeX figures/tables that are also typically layed out after their
    position in the source.

    Args:
        soup (bs4.BeautifulSoup): Paper soup with h1/h2/etc. headers describing sections
    """
    for elem in soup.find_all(['table', 'figure'], attrs={'data-subfigure': False,
                                                          'data-position-here': False}):
        next_header = elem.find_next(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        if next_header:
            next_header.insert_before(elem)
        else:  # This will almost never happen, and isn't necessarily worth warning about
            print('Info: Could not move table/figure to end of section')


def prettify_soup(soup: bs4.BeautifulSoup) -> str:
    """Generate an HTML string of a BeautifulSoup paper document that is slightly more readable
    than simply calling str(soup).

    Args:
        soup (bs4.BeautifulSoup): Paper soup

    Returns:
        str: HTML (UTF-8 encoded)
    """
    # Only insert newlines where it is safe to do so (not going to add semantic space)
    # TODO: indent nicely and all that
    html = soup.encode_contents(formatter='html').decode('utf8')
    html = re.sub(r'\n\n+', '\n', html)
    return html


def save_soup(soup: bs4.BeautifulSoup, output_filename: str) -> None:
    """Add header/footer to a BeautifulSoup object or Tag object and save to a file as UTF-8 HTML.

    Args:
        soup (bs4.BeautifulSoup or bs4.Tag): Soup to save to file
        output_filename (str): Output filename (probably ending with .html)
    """
    paper_title = soup.find('div', attrs={'class': 'Paper-Title'})
    paper_title = paper_title.get_text() if paper_title else 'Paper'
    header = '''<!doctype html>
<html lang="en-US">
    <head>
        <title>''' + paper_title + '''</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta charset="UTF-8">
        <link rel="stylesheet" type="text/css" href="../edm2022.css" />
        <script src="https://polyfill.io/v3/polyfill.min.js?features=es6"></script>
        <script id="MathJax-script" async
            src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
    </head>
    <body>
        <main role="main" class="paper-contents">
    '''
    footer = '''
        </main>
    </body>
</html>
'''
    with open(output_filename, 'w', encoding='utf8') as outfile:
        outfile.write(header)
        outfile.write(prettify_soup(soup))
        outfile.write(footer)
