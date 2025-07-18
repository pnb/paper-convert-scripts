import argparse
import os
import re
import html
import shutil
import tempfile

import bs4
import magic
import pybtex.database
import pypandoc


ap = argparse.ArgumentParser(
    description="Generate proceedings from HTML converter output and .bib " "info"
)
ap.add_argument(
    "html_papers_dir",
    help="Path to a directory with a set of converted paper "
    "subdirectories (e.g., 0BSeO3So4v, PHxnRWijaa)",
)
ap.add_argument(
    "bib_dir",
    help="Path to directory with a set of .bib files, one per paper (to be "
    "matched based on paper title)",
)
ap.add_argument(
    "pdf_dir",
    help="Path to directory with a set of .pdf files, with filenames that "
    "correspond to .bib filenames",
)
ap.add_argument("output_dir", help="Path to output directory")
ap.add_argument(
    "url_base",
    help="URL where the result will eventually be placed (e.g., "
    '"https://example.com/proceedings/"); this is necessary because PDF URL metadata '
    "needs to be absolute URLs, per Google Scholar guidance",
)
ap.add_argument(
    "--category-regex-file",
    help="Path to a text file with a list of paper category "
    "names, each with a regular expression on the next line, which will be matched to "
    "BibTex keys; any uncategorized papers will appear at the top; regular expressions "
    "will be matched in order, with the first match found being applied",
)
ap.add_argument(
    "--intro-doc",
    help="Path to a Markdown or LaTeX file to show as a preface page; the title will "
    "be drawn from the first heading found in the file; LaTeX need not be a complete "
    "document, only a snippet (you might insert a \\section{Introduction to the "
    'Proceedings} title before "Preface" and delete everything before, and delete TOC '
    "and \\end{document}).",
)
ap.add_argument("--copyright", help="Path to a copyright notice snippet in HTML format")
args = ap.parse_args()

try:
    os.mkdir(args.output_dir)
except FileExistsError:
    pass


def hash_title(orig_title: str) -> str:
    """Take a paper title and "standardize" it to a format with only letters and
    numbers, making it easier to match across sources (e.g., BibTex, HTML pages).

    Args:
        orig_title (str): Paper title

    Returns:
        str: Hashed paper title
    """
    return re.sub(r"[^a-z0-9]", "", orig_title.lower())


def unescape_bib(field_value: str) -> str:
    """Pybtex doesn't seem to properly un-escape escaped characters, so do that here.
    Only handles cases that have come up so far.

    Args:
        field_value (str): String from some Pybtex entry.field['fieldname']

    Returns:
        str: Unescaped value
    """
    # "{" and "}" (capitalization)
    field_value = re.sub(r"(?<!\\)[\{\}]", "", field_value)
    # Escaped "#" (not a comment)
    return field_value.replace("\\#", "#")


category_regexes = {}
if args.category_regex_file:
    print("Loading categories")
    with open(args.category_regex_file, encoding="utf8") as infile:
        lines = infile.readlines()
    cur_title = ""
    for i in range(len(lines)):
        if lines[i].strip() and not cur_title:
            cur_title = lines[i].strip()
        elif lines[i].strip():
            category_regexes[lines[i].strip()] = cur_title
            cur_title = ""
        else:
            assert not cur_title, "Did not find regex after category title " + cur_title


print("Loading .bib files")
bib_data = {}  # "Standardized" paper title => Pybtex db with one entry
converted_encoding = None
convert_in_place = False
for bibfile in os.listdir(args.bib_dir):
    if bibfile.endswith(".bib"):
        # Check encoding and convert if needed to standardize as UTF-8
        with open(os.path.join(args.bib_dir, bibfile), "rb") as infile:
            bytecontents = infile.read()
        info = magic.detect_from_content(bytecontents)
        if info.encoding != "utf-8":
            if info.encoding.startswith("unknown"):
                print("Encoding could not be detected for", bibfile)
                if converted_encoding:  # Assume same encoding as the previous one?
                    print("Last converted file had encoding", converted_encoding)
                    assume = input("Should we assume the same? [Y/n] ")
                    if assume.lower().strip() not in ["y", ""]:
                        converted_encoding = None
                if converted_encoding is None:  # No prior conversion to base it on :(
                    print("Quitting (only UTF-8 files are supported).")
                    print("Please manually examine and convert this file and rerun.")
                    exit()
            else:
                converted_encoding = info.encoding
            if not convert_in_place:  # Ask the first time before converting
                print("\nNon-UTF-8 encoding detected for", bibfile, "=>", info.encoding)
                print("Must convert to UTF-8, but you may want to make a backup first.")
                conv = input("Convert bib files to UTF-8 now (will overwrite!)? [Y/n] ")
                if conv.lower().strip() not in ["y", ""]:
                    print("Quitting (only UTF-8 files are supported)")
                    exit()
                convert_in_place = True
            print("Converting from", converted_encoding, "to UTF-8:", bibfile)
            with open(os.path.join(args.bib_dir, bibfile), "wb") as outfile:
                outfile.write(bytecontents.decode(converted_encoding).encode("utf-8"))

        db = pybtex.database.parse_file(os.path.join(args.bib_dir, bibfile))
        if len(db.entries) != 1:
            print(".bib file has >1 entry! That is unexpected. Skipping", bibfile)
            continue
        # Filename (sans extension) is also key of the sole entry
        entry = db.entries[bibfile[:-4]]
        std_title = hash_title(entry.fields["title"].lower())
        assert std_title not in bib_data, "Duplicate title issue"
        bib_data[std_title] = db

print("Processing papers")
paper_index = {}  # Map first page number => hashed title, for creating index page
processed_titles = set()  # Track which ones we've taken care of for checking at the end
for pdir in os.listdir(args.html_papers_dir):
    pdir = os.path.join(args.html_papers_dir, pdir)
    if os.path.isdir(pdir):  # Is a paper directory, presumably
        print(pdir)
        with open(os.path.join(pdir, "index.html"), encoding="utf8") as infile:
            soup = bs4.BeautifulSoup(infile.read(), "lxml")
        first_meta_tag = soup.find("meta")  # To insert things around here

        # Match this paper to BibTex based on <title>
        title_elem = soup.find("title")
        std_title = hash_title(title_elem.get_text())
        if std_title not in bib_data:
            print("BibTex/HTML mismatch for HTML:", title_elem.get_text(strip=True))
            continue
        bib_id = next(iter(bib_data[std_title].entries))
        bib_entry = bib_data[std_title].entries[bib_id]
        # Replace the <title> with the exact match from BibTex, leaving the <div> title
        # as-is, since it may contain superscripts or other stuff
        title_from_bib = html.escape(unescape_bib(bib_entry.fields["title"]))
        title_elem.clear()
        title_elem.append(soup.new_string(title_from_bib))

        # citation_title
        meta_title = soup.new_tag(
            "meta", attrs={"name": "citation_title", "content": title_from_bib}
        )
        first_meta_tag.insert_before(meta_title)
        first_meta_tag.insert_before(soup.new_string("\n"))

        # citation_author
        for author in bib_entry.persons["author"]:
            meta_author = soup.new_tag(
                "meta",
                attrs={"name": "citation_author", "content": html.escape(str(author))},
            )
            first_meta_tag.insert_before(meta_author)
            first_meta_tag.insert_before(soup.new_string("\n"))

        # citation_publication_date
        # This needs to be YYYY or YYYY/M/D (1 digit if possible), which we can't do
        # without D
        # Also, months are not very standardized in BibTex, in general
        meta_date = soup.new_tag(
            "meta",
            attrs={
                "name": "citation_publication_date",
                "content": html.escape(bib_entry.fields["year"]),
            },
        )
        first_meta_tag.insert_before(meta_date)
        first_meta_tag.insert_before(soup.new_string("\n"))

        # citation_conference_title
        meta_conf = soup.new_tag(
            "meta",
            attrs={
                "name": "citation_conference_title",
                "content": html.escape(bib_entry.fields["booktitle"]),
            },
        )
        first_meta_tag.insert_before(meta_conf)
        first_meta_tag.insert_before(soup.new_string("\n"))

        # citation_firstpage and citation_lastpage
        pages = bib_entry.fields["pages"].split("--")
        meta_firstpage = soup.new_tag(
            "meta",
            attrs={"name": "citation_firstpage", "content": html.escape(pages[0])},
        )
        meta_lastpage = soup.new_tag(
            "meta",
            attrs={"name": "citation_lastpage", "content": html.escape(pages[1])},
        )
        first_meta_tag.insert_before(meta_firstpage)
        first_meta_tag.insert_before(soup.new_string("\n"))
        first_meta_tag.insert_before(meta_lastpage)
        first_meta_tag.insert_before(soup.new_string("\n"))
        paper_index[int(pages[0])] = std_title

        # citation_pdf_url  <== absolute URL, and must refer to a file in the same dir!
        assert re.match(
            r"[a-zA-Z0-9\-\_\.]+$", bib_id
        ), "Unexpected characters in BibTex ID"
        meta_pdf_url = soup.new_tag(
            "meta",
            attrs={
                "name": "citation_pdf_url",
                "content": args.url_base.rstrip("/")
                + "/"
                + bib_id
                + "/"
                + bib_id
                + ".pdf",
            },
        )
        first_meta_tag.insert_before(meta_pdf_url)
        first_meta_tag.insert_before(soup.new_string("\n"))

        # citation_doi
        meta_doi = soup.new_tag(
            "meta", attrs={"name": "citation_doi", "content": bib_entry.fields["doi"]}
        )
        first_meta_tag.insert_before(meta_doi)
        first_meta_tag.insert_before(soup.new_string("\n"))

        # Add banner with PDF/index/bib/doi links
        nav = soup.new_tag("header", attrs={"class": "paper-header"})
        soup.find("main").insert_before(nav)
        nav.insert_after(soup.new_string("\n"))

        nav_back = soup.new_tag("a", attrs={"href": "../index.html"})
        nav_back.append(soup.new_string("&larr; All papers"))
        nav.append(nav_back)
        nav.append(soup.new_string("\n"))

        nav_pdf = soup.new_tag(
            "a", attrs={"href": "./" + bib_id + ".pdf", "class": "pdf-link"}
        )
        nav_pdf.append(soup.new_string("pdf"))
        nav.append(nav_pdf)
        nav.append(soup.new_string("\n"))

        nav_bib = soup.new_tag(
            "a", attrs={"href": "./" + bib_id + ".bib", "class": "bib-link"}
        )
        nav_bib.append(soup.new_string("bib"))
        nav.append(nav_bib)
        nav.append(soup.new_string("\n"))

        nav_doi = soup.new_tag(
            "a",
            attrs={
                "href": "https://doi.org/" + bib_entry.fields["doi"],
                "class": "doi-link",
            },
        )
        nav_doi.append(soup.new_string("doi"))
        nav.append(nav_doi)
        nav.append(soup.new_string("\n"))

        # Add copyright notice, optionally
        if args.copyright:
            with open(args.copyright) as infile:
                # Use html.parser to avoid inserting <html><body> in the snippet like
                # lxml does
                soup.find("main").append(
                    bs4.BeautifulSoup(infile.read(), "html.parser")
                )

        # Copy images, flatten image directory structure, and change references to them
        try:
            os.mkdir(os.path.join(args.output_dir, bib_id))
        except FileExistsError:
            pass
        for img in soup.find_all("img", attrs={"src": lambda x: len(x)}):
            new_src = img["src"].lower().replace("/", "_")
            shutil.copy(
                os.path.join(pdir, img["src"]),
                os.path.join(args.output_dir, bib_id, new_src),
            )
            img["src"] = "./" + new_src

        # Save result for this paper
        with open(
            os.path.join(args.output_dir, bib_id, "index.html"), "w", encoding="utf8"
        ) as ofile:
            ofile.write(soup.decode(formatter=None))
        # Copy .bib
        shutil.copy(
            os.path.join(args.bib_dir, bib_id + ".bib"),
            os.path.join(args.output_dir, bib_id, bib_id + ".bib"),
        )
        # Copy .pdf
        shutil.copy(
            os.path.join(args.pdf_dir, bib_id + ".pdf"),
            os.path.join(args.output_dir, bib_id, bib_id + ".pdf"),
        )
        processed_titles.add(std_title)


# Create index page, grouped by category (if provided) and sorted in order of first page
# number
print("Generating index page")
script_dir = os.path.dirname(os.path.realpath(__file__))
with open(os.path.join(script_dir, "index_template.html"), encoding="utf8") as infile:
    index_soup = bs4.BeautifulSoup(infile.read(), "lxml")
main_elem = index_soup.find("main", attrs={"class": "proceedings-contents"})

# Add proceedings title from whatever the first paper says it is
first_std_title = next(iter(paper_index.values()))
first_bib_id = next(iter(bib_data[first_std_title].entries))
first_bib_entry = bib_data[first_std_title].entries[first_bib_id]
title_elem = index_soup.find("title")
title_elem.clear()
title_elem.append(index_soup.new_string(bib_entry.fields["booktitle"]))
h1_elem = index_soup.find("h1")
h1_elem.clear()
h1_elem.append(index_soup.new_string(bib_entry.fields["booktitle"]))

# Add intro/frontmatter if provided
if args.intro_doc:
    print("Creating introduction page")
    intro_html = None
    if args.intro_doc.lower().endswith(".tex"):
        with open(args.intro_doc, "r", encoding="utf8") as infile:
            tex_str = infile.read()
        # Check that number of \includegraphics = number of "alt=" for alt-text
        gfx_count = tex_str.count(R"\includegraphics")
        alt_count = tex_str.count("alt=")
        if gfx_count != alt_count:
            print(
                "Warning: number of \\includegraphics commands does not equal the "
                "number of alt= attributes in the front matter (" + str(gfx_count),
                "vs. " + str(alt_count) + "). This may indicate missing alt-text for "
                "images. If so, they can be added like:\n"
                "    \\includegraphics[alt=Some image description]{...",
            )
            quit_now = input("Quit now so you can fix and try again? [Y/n] ")
            if quit_now.lower().strip() in ["y", ""]:
                exit()
        if R"{\Large" in tex_str:
            print("Found non-semantic {\\Large ...} in front matter.")
            fix_headings = input("Try auto-convert to \\[sub]subsection? [Y/n] ")
            if fix_headings.lower().strip() in ["y", ""]:
                tex_str = re.sub(r"\{\s*\\Large\s+\\bf\s+", R"\\subsection{", tex_str)
                tex_str = re.sub(
                    r"\{\s*\\Large\s+\\it\s+", R"\\subsubsection{", tex_str
                )
        prefix = re.escape(
            R">{\raggedright\arraybackslash}p{(\columnwidth - 2\tabcolsep) * \real{"
        )
        if re.findall(prefix, tex_str):
            print("Found unsupported \\raggedright... column width definition.")
            fix_colwidth = input("Try to auto-replace with `l`? [Y/n] ")
            if fix_colwidth.lower().strip() in ["y", ""]:
                tex_str = re.sub(prefix + r"[\d\.]+\}\}", "l", tex_str)
        intro_html = pypandoc.convert_text(tex_str, "html", "latex")
    if intro_html is None:
        intro_html = pypandoc.convert_file(args.intro_doc, "html")
    with open(
        os.path.join(script_dir, "intro_template.html"), encoding="utf8"
    ) as infile:
        intro_soup = bs4.BeautifulSoup(infile.read(), "html.parser")
    intro_soup.find("main").append(bs4.BeautifulSoup(intro_html, "html.parser"))
    first_heading = intro_soup.find(["h1", "h2", "h3", "h4", "h5", "h6"])
    assert first_heading, "No heading found in " + args.intro_doc
    if first_heading.sourceline > 10:
        print(
            "Warning! First heading in preface file is far into the contents of the file."
        )
        print(" * Heading:", first_heading.get_text(strip=True))
        print(" * Could indicate the title is not correctly detected.")
    intro_soup.find("title").clear()
    intro_soup.find("title").append(
        intro_soup.new_string(first_heading.get_text(strip=True))
    )
    # Remove any image styles (don't want to get *too* much into Tex postprocessing...)
    for img in intro_soup.find_all("img"):
        if img.has_attr("style"):
            del img["style"]
    with open(
        os.path.join(args.output_dir, "intro.html"), "w", encoding="utf8"
    ) as ofile:
        ofile.write(str(intro_soup))
    # Now link to it from the proceedings page
    intro_link = index_soup.new_tag(
        "a", attrs={"href": "intro.html", "class": "intro-link"}
    )
    intro_link.append(index_soup.new_string(first_heading.get_text(strip=True)))
    main_elem.append(intro_link)


def add_paper_listing(bib_id: str, ul: bs4.Tag) -> None:
    """Create a paper listing <li> element and insert it into the given <ul>. Assumes several
    variables (e.g., bib_data) already exist in scope here, which is a bit hacky and could use
    refactoring into a class to avoid such assumptions.

    Args:
        bib_id (str): BibTex key for this paper
        ul (bs4.Tag): <ul> tag the result will be appended to
    """
    bib_entry = bib_data[std_title].entries[bib_id]

    list_elem = index_soup.new_tag("li")
    ul.append(list_elem)
    extras_elem = index_soup.new_tag("div", attrs={"class": "proceedings-extras"})
    list_elem.append(extras_elem)

    pdf_link = index_soup.new_tag(
        "a", attrs={"href": "./" + bib_id + "/" + bib_id + ".pdf", "class": "pdf-link"}
    )
    pdf_link.append(index_soup.new_string("pdf"))
    extras_elem.append(pdf_link)

    bib_link = index_soup.new_tag(
        "a", attrs={"href": "./" + bib_id + "/" + bib_id + ".bib", "class": "bib-link"}
    )
    bib_link.append(index_soup.new_string("bib"))
    extras_elem.append(bib_link)

    doi_link = soup.new_tag(
        "a",
        attrs={
            "href": "https://doi.org/" + bib_entry.fields["doi"],
            "class": "doi-link",
        },
    )
    doi_link.append(index_soup.new_string("doi"))
    extras_elem.append(doi_link)

    title_authors_elem = index_soup.new_tag(
        "div", attrs={"class": "proceedings-title-authors"}
    )
    list_elem.append(title_authors_elem)

    title_heading = index_soup.new_tag("h3", attrs={"class": "paper-list-title"})
    title_authors_elem.append(title_heading)
    title_link = index_soup.new_tag(
        "a", attrs={"href": "./" + bib_id + "/index.html", "class": "title-link"}
    )
    title_heading.append(title_link)  # Wrap title in <h3> for easier screen reader nav
    title_link.append(index_soup.new_string(unescape_bib(bib_entry.fields["title"])))

    authors_elem = index_soup.new_tag("div", attrs={"class": "author-list"})
    title_authors_elem.append(authors_elem)
    for author_i, author in enumerate(bib_entry.persons["author"]):
        if author_i > 0:
            sep_elem = index_soup.new_tag(
                "span", attrs={"class": "author-name-separator"}
            )
            sep_elem.append(index_soup.new_string(" | "))
            title_authors_elem.append(sep_elem)
        title_authors_elem.append(index_soup.new_string(str(author)))


# First handle any papers matching categories
cats_found = {c: False for c in category_regexes.keys()}
for cat_regex, cat_title in category_regexes.items():
    print("Indexing category:", cat_title)
    for first_page_num in sorted(paper_index.keys()):
        std_title = paper_index[first_page_num]
        bib_id = next(iter(bib_data[std_title].entries))
        if re.match(cat_regex, bib_id):
            if not cats_found[cat_regex]:  # Add category to soup for first time
                cats_found[cat_regex] = True
                title_h = index_soup.new_tag("h2")
                main_elem.append(title_h)
                title_h.append(index_soup.new_string(cat_title))
                cat_ul = index_soup.new_tag("ul", attrs={"class": "proceedings-list"})
                main_elem.append(cat_ul)
            listing_elem = add_paper_listing(bib_id, cat_ul)
            del paper_index[first_page_num]  # So it doesn't get added to uncategorized
for unfound_cat in cats_found:
    if not cats_found[unfound_cat]:
        print("No papers matched category:", category_regexes[unfound_cat])

# Add any remaining uncategorized papers
if paper_index:
    print("Indexing uncategorized papers")
    uncategorized_ul = index_soup.new_tag("ul", attrs={"class": "proceedings-list"})
    if args.intro_doc and intro_link:
        intro_link.insert_after(uncategorized_ul)
    else:
        h1_elem.insert_after(uncategorized_ul)
    for first_page_num in sorted(paper_index.keys()):
        std_title = paper_index[first_page_num]
        bib_id = next(iter(bib_data[std_title].entries))
        add_paper_listing(bib_id, uncategorized_ul)

# Save index page
with open(os.path.join(args.output_dir, "index.html"), "w", encoding="utf8") as ofile:
    ofile.write(index_soup.prettify())

# Copy CSS
shutil.copy(os.path.join(script_dir, "edm-proceedings.css"), args.output_dir)

# Check for unexpected mismatches
extra_bib_titles = set(bib_data.keys()).difference(processed_titles)
if extra_bib_titles:
    print("\nBibTex entries not matched to a paper:")
    for std_title in extra_bib_titles:
        bib_id = next(iter(bib_data[std_title].entries))
        print(" *", bib_id + ":", bib_data[std_title].entries[bib_id].fields["title"])

print(
    "\nNote that you will still need to manually copy iedms.css and table_sizer.js "
    "from the paper-convert-www repository to the output directory. Frontmatter images "
    "will also need to be copied manually."
)
