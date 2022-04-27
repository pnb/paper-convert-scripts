import argparse
import os

import pypandoc
from bs4 import BeautifulSoup

import mammoth_utils
import shared_utils


ap = argparse.ArgumentParser(description='Convert .docx to HTML')
ap.add_argument('source_file_path', help='Path to the source .docx file')
ap.add_argument('output_dir', help='Path to output folder (will be created if needed)')
args = ap.parse_args()

print('Creating output folder')
try:
    os.mkdir(args.output_dir)
except FileExistsError:
    print('Output folder already exists; contents may be overwritten')
shared_utils.warn.output_filename = os.path.join(args.output_dir, 'conversion_warnings.csv')

# First do Pandoc conversion, which we will use for math parsing and DrawingML placement
print('Loading via Pandoc')
html = pypandoc.convert_file(args.source_file_path, to='html5', format='docx+styles',
                             extra_args=['--mathml'])
pandoc_soup = BeautifulSoup(html, 'html.parser')

# Now convert via Mammoth, which handles a couple things better than Pandoc; we will Frankenstein
# some Pandoc things in later using BeautifulSoup.
docx_conv = mammoth_utils.MammothParser(args.source_file_path, args.output_dir)

print('Processing captions')
docx_conv.process_captions()

# TODO: Check for possible SVG files that correspond to PNG "preview version" files
#   -- problem is the filenames in docx/media/ don't match for PNG/SVG; probably have to match by
#      alt text in docx_bs
#   -- They are both in the same <w:drawing> at least, but would have to load
#      _rels/document.xml.rels to find the rId for the <asvg:svgBlip> in <w:drawing>
print('Checking figures')
docx_conv.crop_images()  # Crop figures and check them

# TODO: If possible, find two-column tables and move them to the end of a section; currently they
#       can just appear sort of wherever near where the anchor is. Same maybe for figures?
print('Checking tables')
docx_conv.check_tables()
shared_utils.fix_table_gaps(docx_conv.soup)
print('Formatting any footnotes')
docx_conv.format_footnotes()
print('Copying equations from Pandoc')
docx_conv.add_pandoc_equations(pandoc_soup)
print('Checking for DrawingML charts')
docx_conv.convert_drawingml(pandoc_soup)
print('Setting image sizes')
docx_conv.set_image_sizes()
print('Formatting references')
docx_conv.fix_references()
print('Formatting authors')
shared_utils.wrap_author_divs(docx_conv.soup)
print('Checking styles')
shared_utils.check_styles(docx_conv.soup,args.output_dir)

# Save result
print('Saving result')
shared_utils.save_soup(docx_conv.soup, os.path.join(args.output_dir, 'index.html'))
