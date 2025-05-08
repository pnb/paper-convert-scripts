import argparse
import os

import pypandoc
from bs4 import BeautifulSoup

import docx
import shared


ap = argparse.ArgumentParser(description="Convert .docx to HTML")
ap.add_argument("source_file_path", help="Path to the source .docx file")
ap.add_argument("output_dir", help="Path to output folder (will be created if needed)")
args = ap.parse_args()

print("Creating output folder")
try:
    os.mkdir(args.output_dir)
except FileExistsError:
    print("Output folder already exists; contents may be overwritten")
shared.warn.output_filename = os.path.join(args.output_dir, "conversion_warnings.csv")

# First do Pandoc conversion, which we will use for math parsing and DrawingML placement
print("Loading via Pandoc")
html = pypandoc.convert_file(
    args.source_file_path, to="html5", format="docx+styles", extra_args=["--mathml"]
)
with open(os.path.join(args.output_dir, "tmp-pandoc.html"), "w") as ofile:
    ofile.write(html)  # In case we need to debug later
pandoc_soup = BeautifulSoup(html, "html.parser")
template_name = "unknown"
if pandoc_soup.find("div", attrs={"data-custom-style": "Paper-Title"}):
    template_name = "EDM"
elif pandoc_soup.find("div", attrs={"data-custom-style": "MainTitle"}):
    template_name = "JEDM"
else:
    shared.warn("template_not_detected", tex=True)
    exit()
print("Detected template:", template_name)

# Now convert via Mammoth, which handles a couple things better than Pandoc; we will
# Frankenstein some Pandoc things in later using BeautifulSoup
docx_conv = docx.MammothParser(args.source_file_path, args.output_dir, template_name)

print("Formatting authors")
docx_conv.format_authors()
shared.wrap_author_divs(docx_conv.soup)
print("Processing captions")
docx.process_captions(docx_conv)

print("Checking figures")
docx.one_to_one_alt_text_map(docx_conv)
docx.crop_images(docx_conv)  # Crop figures and check them

print("Checking tables")
docx.check_tables(docx_conv)
shared.fix_table_gaps(docx_conv.soup)
print("Formatting any footnotes")
docx_conv.format_footnotes()
print("Copying equations and block quotes from Pandoc")
docx_conv.add_pandoc_equations(pandoc_soup)
docx.add_pandoc_blockquotes(pandoc_soup, docx_conv.soup)
docx.add_pandoc_bullets(pandoc_soup, docx_conv.soup)
print("Checking for DrawingML charts")
docx_conv.convert_drawingml(pandoc_soup)
print("Setting image sizes")
docx_conv.set_image_sizes()
shared.check_alt_text_duplicates(docx_conv.soup)
docx_conv.check_caption_placement()
print("Formatting references")
docx_conv.fix_references()
print("Checking styles")
docx.fix_jedm_frontmatter(docx_conv)
shared.check_styles(docx_conv.soup, args.output_dir, template_name, tex=False)
shared.check_citations_vs_references(
    docx_conv.soup,
    args.output_dir,
    shared.CONFIG["anystyle_path"],
    template_name,
    tex=False,
)

# Save result
print("Saving result")
shared.save_soup(docx_conv.soup, os.path.join(args.output_dir, "index.html"))
