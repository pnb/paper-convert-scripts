import argparse
import os
import shutil
import subprocess

from bs4 import BeautifulSoup
import cssutils

import make4ht_utils
import shared_utils
import tex


ap = argparse.ArgumentParser(description='Convert LaTeX to HTML')
ap.add_argument('source_file_path', help='Path to the source .zip file')
ap.add_argument('output_dir', help='Path to output folder (will be created if needed)')
ap.add_argument('--mathml', default=False, action='store_true',
                help='Use MathML conversion in make4ht')
ap.add_argument('--skip-compile', default=False, action='store_true',
                help='Skip (re)compilation; useful only for quickly debugging postprocessing steps')
args = ap.parse_args()

print('Creating output folder')
extracted_dir = os.path.join(args.output_dir, 'source')
shared_utils.warn.output_filename = os.path.join(args.output_dir, 'conversion_warnings.csv')
try:
    os.mkdir(args.output_dir)
except FileExistsError:
    print('Output folder already exists; contents may be overwritten')
    # Clean up old files
    if not args.skip_compile:
        try:
            shutil.rmtree(extracted_dir)
        except FileNotFoundError:
            pass


# Combine any \input files into 1 (makes postprocessing much easier for line numbers)
print('Reading LaTeX source')
texstr = make4ht_utils.get_raw_tex_contents(args.source_file_path, extracted_dir)
with open(os.path.join(extracted_dir, 'tmp-make4ht.tex'), 'w') as ofile:
    ofile.write(texstr)

bib_backend = make4ht_utils.get_bib_backend(texstr)
make4ht_utils.check_file_hash(os.path.join(extracted_dir, 'edm_article.cls'),
                              '7efa88c45209f518695575100a433dca2e32f7a02d3d237e9f4c5bd1cb1c3553')

if not args.skip_compile:
    print('Converting via make4ht')
    scripts_dir = os.path.dirname(os.path.realpath(__file__))
    mk4_template = os.path.join(scripts_dir, 'make4ht_hardcode_bib.mk4')
    if bib_backend:
        mk4_template = os.path.join(scripts_dir, 'make4ht_template.mk4')
    with open(mk4_template) as infile:
        with open(os.path.join(extracted_dir, 'make4ht_with_bibtex.mk4'), 'w') as ofile:
            if bib_backend:
                ofile.write('Make:add("bibtex", "%s ${input}")\n' % bib_backend)
            ofile.write(infile.read())
    shutil.copy(os.path.join(scripts_dir, 'make4ht_preamble.cfg'), extracted_dir)
    mathml = 'mathml,' if args.mathml else ''
    retcode = subprocess.call('make4ht --output-dir .. --format html5+common_domfilters '
                              '--build-file make4ht_with_bibtex.mk4 tmp-make4ht.tex '
                              '"' + mathml + 'mathjax,svg,fn-in" --config make4ht_preamble',
                              shell=True, cwd=extracted_dir)
    if retcode:
        shared_utils.warn('make4ht_warnings', tex=True)

# Load HTML
if not os.path.exists(os.path.join(extracted_dir, 'tmp-make4ht.html')):
    shared_utils.warn('make4ht_failed', tex=True)
    if os.path.exists(os.path.join(extracted_dir, 'tmp-make4ht.blg')):
        print('\nBibliography log:')
        error_count = 0
        with open(os.path.join(extracted_dir, 'tmp-make4ht.blg')) as blg:
            for line in blg.readlines():
                if line.startswith('You\'ve used'):
                    break  # End of useful output
                print(line.strip())
                if line.startswith('I\'m skipping'):
                    error_count += 1
        if error_count:
            shared_utils.warn('bib_compile_errors', str(error_count) + ' error(s)', tex=True)
    exit()
print('Loading converted HTML')
with open(os.path.join(extracted_dir, 'tmp-make4ht.html')) as infile:
    soup = BeautifulSoup(infile, 'html.parser')

texer = tex.TeXHandler(texstr, soup)
print('Parsing headings')
tex.add_headings(texer)
print('Parsing authors')
tex.add_authors(texer)
shared_utils.wrap_author_divs(texer.soup)
print('Merging unnecessary elements')
texer.merge_elements('span')
print('Formatting tables')
tex.format_tables(texer)
shared_utils.fix_table_gaps(texer.soup)
print('Formatting figures')
texer.format_figures()
shared_utils.check_alt_text_duplicates(texer.soup, True)
print('Formatting equations')
texer.format_equations()
print('Formatting lists')
tex.parse_description_lists(texer)
print('Formatting fonts')
texer.fix_fonts()
print('Parsing references')
texer.fix_references()

# Inline any styles made by ID
print('Inlining styles selected by ID')
cssutils.log.setLevel('FATAL')
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
shared_utils.check_styles(soup, args.output_dir, True)

# Save result
print('Saving result')
shared_utils.save_soup(soup.body, os.path.join(args.output_dir, 'index.html'))
