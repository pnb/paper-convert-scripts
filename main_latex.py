import argparse
import os
import subprocess

from bs4 import BeautifulSoup
import cssutils

import make4ht_utils
import shared_utils


ap = argparse.ArgumentParser(description='Convert LaTeX to HTML')
ap.add_argument('source_file_path', help='Path to the source .zip file')
ap.add_argument('output_dir', help='Path to output folder (will be created if needed)')
args = ap.parse_args()

print('Creating output folder')
try:
    os.mkdir(args.output_dir)
except FileExistsError:
    print('Output folder already exists; contents may be overwritten')
extracted_dir = os.path.join(args.output_dir, 'source')
shared_utils.warn.output_filename = os.path.join(args.output_dir, 'conversion_warnings.csv')


# Combine any \input files into 1 (makes postprocessing much easier for line numbers)
print('Reading LaTeX source')
tex = make4ht_utils.get_raw_tex_contents(args.source_file_path, extracted_dir)
with open(os.path.join(extracted_dir, 'tmp-make4ht.tex'), 'w') as ofile:
    ofile.write(tex)

bib_backend = make4ht_utils.get_bib_backend(tex)

print('Converting via make4ht')
mk4_template = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'make4ht_sans_bib.mk4')
with open(mk4_template) as infile:
    with open(os.path.join(extracted_dir, 'make4ht_with_bibtex.mk4'), 'w') as ofile:
        ofile.write('Make:add("bibtex", "%s ${input}")\n' % bib_backend)
        ofile.write(infile.read())
verbose_args = {}
# not_verbose_args = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
retcode = subprocess.call('make4ht --output-dir .. --format html5+common_domfilters '
                          '--build-file make4ht_with_bibtex.mk4 tmp-make4ht.tex '
                          '"mathml,mathjax,svg,fn-in"', shell=True, cwd=extracted_dir)
if retcode:
    shared_utils.warn('make4ht_failed', tex=True)

# Load HTML
print('Loading converted HTML')
with open(os.path.join(extracted_dir, 'tmp-make4ht.html')) as infile:
    soup = BeautifulSoup(infile, 'html.parser')

texer = make4ht_utils.TeXHandler(tex, soup)
print('Parsing headers')
texer.add_headers()
print('Parsing authors')
texer.add_authors()
shared_utils.wrap_author_divs(texer.soup)
print('Merging unnecessary elements')
texer.merge_elements('span')
print('Formatting tables')
texer.format_tables()  # TODO: Need to add stuff into <thead> for accessibility and CSS
shared_utils.fix_table_gaps(texer.soup)
print('Formatting figures')
texer.format_figures()
print('Formatting equations')
texer.format_equations()
print('Formatting fonts')
texer.fix_fonts()
print('Parsing references')
texer.fix_references()

# TODO: Move table* to end of section

# Inline any styles made by ID
print('Inlining styles selected by ID')
css = cssutils.parseFile(os.path.join(extracted_dir, 'tmp-make4ht.css'))
for rule in css:
    if rule.type == rule.STYLE_RULE:
        if '#' in rule.selectorText:
            elem = soup.select_one(rule.selectorText)
            if elem:
                cur_style = elem['style'] if elem.has_attr('style') else ''
                elem['style'] = rule.style.cssText + ';' + cur_style

print('Removing unused IDs')
texer.remove_unused_ids()

print('Checking styles')
shared_utils.check_styles(soup,args.output_dir)

# Save result
print('Saving result')
shared_utils.save_soup(soup.body, os.path.join(args.output_dir, 'index.html'))
