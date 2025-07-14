# HTML proceedings generation

The `online_proceedings.py` script generates an HTML version of a proceedings. The proceedings conforms with [Google Scholar indexing requirements](https://scholar.google.com/intl/en/scholar/inclusion.html#content).

Run `python online_proceedings.py -h` for additional help and description of argument usage/order.

## Requirements

* The [paper_convert conda environment](../conda_env.yml)
* A directory with all of the converted HTML papers to be included in the proceedings (and no more), each as an individual directory
* A directory with a .bib file, one per paper
  * Filenames need not match the HTML paper folders, since they will be matched based on title
  * The directory may contain additional BibTex files, but a one-to-one matching is assumed so these will generate warnings at the end to allow you to check that all expected HTML papers were found
* A directory with PDF files, one per paper
  * The PDF filenames *do* need to match the BibTex filenames; e.g., long-paper-1.bib and long-paper-1.pdf
  * For testing without PDFs, you can create a *pdf-mockup* directory next to the .bib directory and then, from within the .bib directory, run: `for i in *.bib; do fname=$(basename "$i" .bib); touch "../pdf-mockup/$fname.pdf"; done`
* A URL for where the proceedings will be hosted online; i.e., the folder in which the generated `index.html` file will be
* Eventually, copy `iedms.css` and `table_sizer.js` from the *paper-convert-www* project to the finished HTML proceedings for proper styles/sizes

## Optional elements

* Papers may be organized by category (e.g., short, long) in sections in the resulting proceedings
  * Create a text file with category names and a regular expression for each category name on the subsequent line
  * The regular expression will be matched to BibTex keys from the .bib files
  * Any papers not matched will be in an unnamed section at the top of the proceedings index
  * Within category (or uncategorized), papers will be ordered based on page number
* Front matter, linked at the top of the proceedings index and outputted to a separate `intro.html` file
  * Note that both Markdown and LaTeX are supported (technically anything Pandoc can handle as input), but very little sanity checking is done on the output; hence, Markdown is strongly recommended since there is very little chance of strange results
* Copyright info, which will be appended to the end of each paper after a horizontal rule

## Example with all options

```bash
python online_proceedings.py \
    ~/Downloads/papers_select \  # HTML paper directories
    ~/Downloads/bib-with-doi \   # .bib files
    ~/Downloads/stamped \        # .pdf files
    ~/Downloads/edm_html_proceedings \  # Output destination
    https://educationaldatamining.org/edm2023/proceedings \
    --category-regex-file edm-categories.txt \
    --intro-doc ~/Downloads/front_matter_final.md \
    --copyright edm2023-copyright.html
```
