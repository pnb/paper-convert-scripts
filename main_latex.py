import argparse
import os
import shutil

from bs4 import BeautifulSoup
import cssutils

import make4ht_utils
import shared
import tex


ap = argparse.ArgumentParser(description="Convert LaTeX to HTML")
ap.add_argument("source_file_path", help="Path to the source .zip file")
ap.add_argument("output_dir", help="Path to output folder (will be created if needed)")
ap.add_argument(
    "--mathml",
    default=False,
    action="store_true",
    help="Use MathML conversion in make4ht",
)
ap.add_argument("--timeout-ms", type=int, help="Enforce make4ht execution time (in ms)")
ap.add_argument(
    "--skip-compile",
    action="store_true",
    help="Skip (re)compilation; useful only for quickly debugging postprocessing steps",
)
ap.add_argument(
    "--skip-extract",
    action="store_true",
    help="Skip extraction; useful for modifying Tex sources during debugging",
)
ap.add_argument(
    "--main-tex", default="main.tex", help="Name of main .tex file (default main.tex)"
)
args = ap.parse_args()

print("Creating output folder")
extracted_dir = os.path.join(args.output_dir, "source")
shared.warn.output_filename = os.path.join(args.output_dir, "conversion_warnings.csv")
try:
    os.mkdir(args.output_dir)
except FileExistsError:
    print("Output folder already exists; contents may be overwritten")
    # Clean up old files
    if not args.skip_compile and not args.skip_extract:
        try:
            shutil.rmtree(extracted_dir)
        except FileNotFoundError:
            pass


# Combine any \input files into 1 (makes postprocessing much easier for line numbers)
print("Reading LaTeX source")
if args.skip_extract:
    with open(os.path.join(extracted_dir, "tmp-make4ht.tex")) as infile:
        texstr = infile.read()
else:
    texstr = make4ht_utils.get_raw_tex_contents(
        args.source_file_path, extracted_dir, args.main_tex
    )
    with open(os.path.join(extracted_dir, "tmp-make4ht.tex"), "w") as ofile:
        ofile.write(texstr)

bib_backend = make4ht_utils.get_bib_backend(texstr)
extra_flags = make4ht_utils.detect_extra_flags_needed(texstr)
if extra_flags:
    print("Using extra make4ht flags:" + extra_flags)

template_name = "unknown"
if os.path.exists(os.path.join(extracted_dir, "edm_article.cls")):
    template_name = "EDM"
    make4ht_utils.check_file_hash(
        os.path.join(extracted_dir, "edm_article.cls"),
        "7efa88c45209f518695575100a433dca2e32f7a02d3d237e9f4c5bd1cb1c3553",
    )
elif os.path.exists(os.path.join(extracted_dir, "jedm.cls")):
    template_name = "JEDM"
else:
    shared.warn("template_not_detected", tex=True)
    exit()
print("Detected template:", template_name)

if not args.skip_compile:
    print("Converting via make4ht")
    scripts_dir = os.path.dirname(os.path.realpath(__file__))
    mk4_template = os.path.join(scripts_dir, "make4ht_hardcode_bib.mk4")
    if bib_backend:
        mk4_template = os.path.join(scripts_dir, "make4ht_template.mk4")
    with open(mk4_template) as infile:
        with open(os.path.join(extracted_dir, "make4ht_with_bibtex.mk4"), "w") as ofile:
            if bib_backend:
                ofile.write('Make:add("bibtex", "%s ${input}")\n' % bib_backend)
            ofile.write(infile.read())
    shutil.copy(os.path.join(scripts_dir, "make4ht_preamble.cfg"), extracted_dir)
    mathml = "mathml," if args.mathml else ""
    retcode = shared.exec_grouping_subprocesses(
        "make4ht" + extra_flags + " --output-dir .. --format html5+common_domfilters "
        "--build-file make4ht_with_bibtex.mk4 tmp-make4ht.tex "
        '"' + mathml + 'mathjax,svg,fn-in" --config make4ht_preamble',
        timeout=args.timeout_ms / 1000 if args.timeout_ms else None,
        shell=True,
        cwd=extracted_dir,
    )
    if retcode:
        if template_name == "JEDM" and "{natbib}" in texstr:
            shared.warn("natbib_jedm", tex=True)
        shared.warn("make4ht_warnings", tex=True)

# Load HTML
if not os.path.exists(os.path.join(extracted_dir, "tmp-make4ht.html")):
    shared.warn("make4ht_failed", tex=True)
    if os.path.exists(os.path.join(extracted_dir, "tmp-make4ht.blg")):
        print("\nBibliography log:")
        error_count = 0
        with open(os.path.join(extracted_dir, "tmp-make4ht.blg")) as blg:
            for line in blg.readlines():
                if line.startswith("You've used"):
                    break  # End of useful output
                print(line.strip())
                if line.startswith("I'm skipping"):
                    error_count += 1
        if error_count:
            shared.warn("bib_compile_errors", str(error_count) + " error(s)", tex=True)
    exit()
print("Loading converted HTML")
with open(os.path.join(extracted_dir, "tmp-make4ht.html")) as infile:
    html_str = tex.fix_et_al(infile.read())
    if " --lua" in extra_flags:
        html_str = tex.lua_font_remap(html_str)
    soup = BeautifulSoup(html_str, "html.parser")

texer = tex.TeXHandler(texstr, soup, template_name)
print("Formatting lists")
tex.parse_description_lists(texer)
print("Parsing headings")
tex.add_headings(texer)
print("Parsing authors")
tex.add_authors(texer)
shared.wrap_author_divs(texer.soup)
print("Merging unnecessary elements")
texer.merge_elements("span")
print("Formatting tables")
tex.format_tables(texer)
shared.fix_table_gaps(texer.soup)
print("Formatting figures")
tex.format_listings(texer)
tex.format_figures(texer)
shared.check_alt_text_duplicates(texer.soup, True)
print("Formatting equations")
texer.format_equations()
tex.add_macros_for_mathjax(texer)
print("Formatting fonts")
texer.fix_fonts()
print("Parsing references")
texer.fix_references()
shared.mark_up_citations(texer.soup, template_name)

# Inline any styles made by ID
print("Inlining styles selected by ID")
cssutils.log.setLevel("FATAL")
css = cssutils.parseFile(os.path.join(extracted_dir, "tmp-make4ht.css"))
for rule in css:
    if rule.type == rule.STYLE_RULE:
        if "#" in rule.selectorText:
            for elem in soup.select(rule.selectorText):
                elem["style"] = rule.style.cssText + ";" + elem.get("style", "")
                if elem.name == "col":
                    if not elem.parent.find_previous_sibling("colgroup"):
                        elem["style"] += "border-left:none;"
                    if not elem.parent.find_next_sibling("colgroup"):
                        elem["style"] += "border-right:none;"
                if elem.name == "td":
                    if not elem.find_previous_sibling("td"):
                        elem["style"] += "border-left:none;"
                    if not elem.find_next_sibling("td"):
                        elem["style"] += "border-right:none;"

print("Removing unused IDs")
texer.remove_unused_ids()

print("Checking styles")
shared.check_styles(soup, args.output_dir, template_name, tex=True)
shared.check_citations_vs_references(
    soup, args.output_dir, shared.CONFIG["anystyle_path"], template_name, tex=True
)

# Save result
print("Saving result")
shared.save_soup(soup.body, os.path.join(args.output_dir, "index.html"))
