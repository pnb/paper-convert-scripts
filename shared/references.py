# Can run tests via `python -m shared.references`
import re
import os
import subprocess
import json
import tempfile
from collections import defaultdict

import bs4

from .shared_utils import get_elem_containing_text, warn

# Words that are also lowercase parts of names
# Even better is to extract from references via get_lowercase_name_words
LC_NAME_WORDS = "van de der ten la y da das dos e di lo al bin bint abu".split()


def check_citations_vs_references(
    soup: bs4.BeautifulSoup,
    output_dir: str,
    anystyle_path: str,
    input_template: str,
    tex: bool,
):
    # Check every numbered reference appears in the text in square brackets
    refs = get_references(soup, output_dir, anystyle_path)
    if refs == []:
        warn("no_references_found_in_reference_section", tex=tex)
        return
    cites = get_citations(soup, input_template)
    if cites == []:
        warn("no_citations_found_in_text", tex=tex)
        return
    # Match citations to references
    if input_template == "EDM":
        ref_keys = set(str(i + 1) for i in range(len(refs)))
        mismatched = ["Citation: " + c for c in set(cites).difference(ref_keys)]
        mismatched += ["Reference: " + r for r in ref_keys.difference(cites)]
    elif input_template == "JEDM":
        # No 1-to-1 ref <=> cite key mapping due to et al. and disambiguation
        # Instead, search for approximate matches for every citation
        cite_matched_i = set()
        ref_matched_i = set()
        mismatched = []
        for cite_i, cite in enumerate(cites):
            for ref_i, ref in enumerate(refs):
                if "date" not in ref:
                    ref["date"] = ["XXXX"]  # n.d. citations sometimes
                if ref["date"][0][:4] != cite.split()[-1][:4]:
                    continue  # Year mismatch, ignoring disambiguation a/b/etc.
                if "author" not in ref:
                    if "publisher" in ref:  # Maybe misdetected as publisher (e.g., ISU)
                        ref["author"] = [{"family": ref["publisher"][0]}]
                    else:
                        continue
                if "pages" not in ref and "note" in ref:
                    maybe_pages = re.search(r"(\d+[-–]\d+)\.$", ref["note"][0])
                    if maybe_pages:
                        ref["pages"] = maybe_pages.group(1)
                if "publisher" not in ref and len(ref.get("container-title", [])) > 1:
                    ref["publisher"] = ref["container-title"][1]
                # Check if each author in the reference appears in the citation
                author_matches = []
                for a in ref["author"]:
                    if "others" in a and a["others"]:
                        continue  # 25+ authors have "...", which parses as this
                    name = a.get("family", a.get("given", ""))
                    if name == "n.d" and "given" in a:
                        name = a["given"]  # Misdetected n.d. as name
                    matches = re.search(r"\b" + re.escape(name) + r"\b", cite)
                    if not matches and re.match(r"([A-Z]\.)+", name):
                        name = name.replace(".", "")  # A.C.M.E. => ACME
                        matches = re.search(r"\b" + re.escape(name) + r"\b", cite)
                    author_matches.append(1 if matches else 0)
                # If yes, or it is an "et al." citation and the first matches, it is OK
                if (
                    sum(author_matches) == len(author_matches)
                    or " et al." in cite
                    and len(ref["author"]) > 2
                    and author_matches[0]
                ):
                    ref_matched_i.add(ref_i)
                    cite_matched_i.add(cite_i)
            if cite_i not in cite_matched_i:
                mismatched.append("Citation: " + cite)
        for ref_i, ref in enumerate(refs):
            if ref_i not in ref_matched_i:
                title = str(ref[next(iter(ref))])
                for prefer_key in ["title", "container-title"]:
                    if prefer_key in ref:
                        title = ref[prefer_key][0]
                        break
                mismatched.append("Reference: " + title)
    else:
        raise NotImplementedError(input_template)
    if len(mismatched) > 0:
        warn("mismatched_refs", sorted(mismatched), tex=tex)

    # Check references are complete
    ref_requirements = defaultdict(lambda: ["title", "date"])
    ref_requirements["book"] = ["author", "title", "date", "publisher"]
    ref_requirements["report"] = ["author", "title", "date", "publisher"]
    ref_requirements["chapter"] = [
        "author",
        "title",
        "date",
        "publisher",
        "editor",
        "container-title",
        "pages",
        "location",
    ]
    ref_requirements["paper-conference"] = [
        "author",
        "title",
        "date",
        "container-title",
        "pages",
    ]
    ref_requirements["article-journal"] = [
        "author",
        "title",
        "date",
        "container-title",
        "pages",
        "volume",
    ]  # "issue" is false alarming too much
    for i, ref_dict in enumerate(refs, start=1):
        if "pages" not in ref_dict and len(ref_dict.get("date", [])) > 1:
            ref_dict["pages"] = ref_dict["date"][1:]  # Misdetected pages as dates
        reqs = set(ref_requirements[ref_dict["type"]])
        missing_reqs = reqs.difference(set(ref_dict.keys()))
        if len(missing_reqs) > 0:
            ref_type = ref_dict["type"] if ref_dict["type"] else "other"
            short_key = ""
            if "title" in ref_dict:
                short_key = ref_dict["title"][0]
            elif "author" in ref_dict:
                short_key = ", ".join(
                    a["family"] for a in ref_dict["author"] if "family" in a
                )
            elif "container-title" in ref_dict:
                short_key = ref_dict["container-title"][0]
            if len(short_key) > 35:
                short_key = short_key[:30] + "..."
            if len(short_key):
                short_key = " (" + short_key + ")"
            warn(
                "incomplete_reference",
                f"Reference {i}{short_key} was recognized as {ref_type} and might "
                + "be missing the following: "
                + ", ".join(missing_reqs),
                tex,
            )


def get_references(
    soup: bs4.BeautifulSoup, output_dir: str, anystyle_path: str
) -> list:
    """Extract references from the references section using Anystyle.

    Args:
        soup (bs4.BeautifulSoup): Soup containing a "references" <h1>
        output_dir (str): Path to output folder
        anystyle_path (str): Path to `anystyle` executable

    Returns:
        list: List of dicts from JSON outputted by Anystyle
    """
    heading = get_elem_containing_text(soup, "h1", "references", True)
    if not heading:
        return []  # We should already going to warn about this
    # Format one per line as expected by Anystyle
    fname = os.path.join(output_dir, "extracted_refs.txt")
    with open(fname, "w", encoding="utf8") as ofile:
        for ref in heading.find_next("ol").find_all("li"):
            ofile.write(re.sub(r"\s+", " ", ref.get_text().strip()) + "\n")
    subprocess.call(
        [anystyle_path, "-f", "json", "--overwrite", "parse", fname, output_dir],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    with open(fname[:-4] + ".json") as infile:
        ref_dict_list = json.load(infile)
    return ref_dict_list


def get_lowercase_name_words(anystyle_output: list) -> set[str]:
    words = []
    for ref in anystyle_output:
        if "author" in ref:
            for author in ref["author"]:
                if "family" in author:
                    words.extend(w for w in author["family"].split() if w == w.lower())
                if "particle" in author:
                    words.extend(author["particle"].split())
    return set(words)


def get_citations(
    soup: bs4.BeautifulSoup, input_template: str, lc_name_words: set[str] = set()
) -> list[str]:
    """Find in-text citations for the given soup, in the format expected per the input
    template (e.g., EDM).

    Args:
        soup (bs4.BeautifulSoup): Soup to search through
        input_template (str): Expected document (and thus citation) format
        lc_name_words (set[str]): Optional lowercase words to consider part of names
            (e.g., van, bin, y); only relevant for certain styles like JEDM

    Raises:
        NotImplementedError: Error on unknown template name

    Returns:
        list[str]: Citations found
    """
    soup_copy = bs4.BeautifulSoup(str(soup), "html.parser")
    heading = get_elem_containing_text(soup_copy, "h1", "references", True)
    if heading:
        for elem in heading.find_all_next():
            if elem.name == "div" and "footnotes" in elem.get("class", []):
                break  # Stop deleting at footnotes
            elem.clear()  # Delete everything in references to avoid confusion
    text = soup_copy.get_text()
    if input_template == "JEDM":  # APA-ish
        return get_apa_citations(text, lc_name_words)
    elif input_template == "EDM":
        return get_square_brackets_citations(text)
    else:
        raise NotImplementedError(input_template)


def get_square_brackets_citations(text: str) -> list[str]:
    """Find in-text citations and return them as a list of strings (which should be
    integers), expanding ranges in citations like [12-15].

    Args:
        text (str): Plain text to process

    Returns:
        list[str]: List of citations found
    """
    cites_raw = re.findall(
        r"\[(?:cf\.\s*)?"  # Chomp cf. at the beginning
        r"((?:[1-9]\d*,?\s*)+)"  # Capture ref number (>0) and any space/comma
        r"(?:(?:p|Sec|Ch)[^\],]+)?\]",  # Chomp section/page(s) at the end
        text,
    )
    cite_ranges = re.findall(r"\[([1-9]\d*[-\u2013][1-9]\d*)\]", text)  # e.g., "[1-5]"
    for ref_range in cite_ranges:
        low, high = re.split(r"\D", ref_range)
        if int(low) < int(high) and int(high) - int(low) < 25:  # Not too big of a range
            cites_raw += [str(x) for x in range(int(low), int(high) + 1)]
    # Further filter to reasonable entries
    all_nums = sorted(set(int(x) for x in re.split(r"\D+", ",".join(cites_raw))))
    for i in range(1, len(all_nums)):
        if all_nums[i] > all_nums[i - 1] + 10:
            all_nums = all_nums[:i]  # Math range or other misdetected huge jump
            break
    cites = []
    for raw_cite in cites_raw:
        nums = [n for n in re.split(r"\D+", raw_cite) if len(n)]
        if all(int(n) in all_nums for n in nums):
            cites.extend(nums)
    return cites


def get_apa_citations(text: str, lc_name_words: set[str]) -> list[str]:
    """Find in-text citations and return tham as "Author(s), YYYY" strings, including
    et al. if that is what the citation says, and YYYYa/b/etc. if the citation includes
    disambiguating a/b info. Removes page/chapter/section ranges, since these do not
    influence the matching between citations and references.

    Args:
        text (str): Plain text to process
        lc_name_words (set[str]): Optional lowercase words to consider part of names

    Returns:
        list[str]: List of citations found
    """
    cites = []
    text = text.replace("\n", " ")  # Remove newlines that can complicate parsing
    # Collapse multiple spaces (easier parsing) and unusual spaces (e.g., nbsp)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(  # Remove page/chapter/section numbers
        r",? ((pp|Ch|Sec)\. \d+(\d*[-\u2010-\u2015, ]+\d+)*|(p|Ch|Sec)\. \d+)\b",
        "",
        text,
    )
    text = re.sub(
        r"(e\.g\.|i\.e\.|,? ?for example),? ?", "", text
    )  # Remove e.g., i.e., for example
    # Precompile expression for potential multi-year cites (Authors, 1999, 2000)
    year_end_re = re.compile(r",? *([12][0-9][0-9][0-9][a-z]?| nd)(?=($|,))")
    # Look for "YYYY)" or "YYYY]...)", which should be at the end of every citation, I
    # think...
    for ending in re.finditer(
        r"((\s|\(|\[)[12][0-9][0-9][0-9][a-z]?| nd| et al., )(\)|](?=[^(]*\)))", text
    ):
        # Then backtrack to figure out where the citing begins, then split multiple
        # Account for non-capitalized names (e.g., van Dijk), et al., ;, etc.
        inline = False
        for i in range(ending.end() - 1, -1, -1):
            if inline and text[i] in " (" and text[i + 1] not in "([":
                first_tok = text[i + 1 : ending.end() - 1].split()[0]
                first_word = first_tok.rstrip(".,;:")
                if text[i] == "(" or (
                    first_word == first_word.lower()
                    and first_word not in lc_name_words
                    and first_word not in ["et", "al", "&", "and"]
                ):
                    offset = 1 if text[i] == "(" else len(first_tok) + 2
                    ref = text[i + offset : ending.end() - 1]
                    cites.append(ref.replace(" (", ", ").replace(" [", ", "))
                    break
            elif text[i] in "([":
                if text[i + 1] in "0123456789":
                    # Matches (YYYY; YYYYb, pp. A-B, etc.) without author names
                    # Keep backtracking until we find likely start of author names
                    inline = True
                else:
                    # Split based on YYYY or YYYYa with another author name after
                    for cite in re.split(
                        r"((?<=\d{4})|(?<=\d{4}[a-z]))[;,] *(?=[^ \d])",
                        text[i + 1 : ending.end() - 1],
                    ):
                        for y in year_end_re.finditer(cite):
                            year = "XXXX" if y.group(1) == " nd" else y.group(1)
                            cites.append(year_end_re.sub("", cite) + ", " + year)
                    break
    return cites


def mark_up_citations(soup: bs4.BeautifulSoup, input_template: str) -> None:
    """Add useful semantic information to the in-text citations. Currently, this
    consists only of adding a "citation" CSS class for JEDM Tex citations, but in the
    future it could include other templates and maybe adding links for citations that
    don't have them (especially DOCX).

    Args:
        soup (bs4.BeautifulSoup): Soup to modify
        input_template (str): Expected document (and thus citation) format
    """
    if input_template == "JEDM":
        for a in soup.find_all("a", attrs={"href": True}):
            if a["href"].startswith("#X"):
                a["class"] = a.get("class", []) + ["citation"]


if __name__ == "__main__":
    processed_refs_html = """<ol>
        <li><span class="ReferenceAuthor">Ablamowicz, R. and Fauser, B.</span>. 2007.
            Clifford: a maple 11 package for clifford algebra computations, version 11.
        </li>
        <li>Namington, B., Anotherone, C., and Lastington, D. 1999. The article name.
            Journal of Reference Parsing Tests 1, 2, 123-124.
        </li>
        <li>Editorname, I., Ed. 2007. The Title of Book One, 1st. ed. The name of the
            series one, vol. 9. University of Chicago Press, Chicago.
        </li>
        <li>van der Waal, M. 1999. Een wetenschappelijk artikel. Journaal Van
            Artikelen 11, 12 (June), 1000-1010.
        </li>
        <li>Supporting Author, A. and Another. 1999. The second author has a mononym.
            Journal of Articles 1, 2, 10-11.</li>
        <li>Namington, B., Anotherone, C., and Lastington, D. 2000. The article name 2.
            Journal of Reference Parsing Tests 2, 3, 423-424.
        <li>Namington, B., Anotherone, C., and Lastington, D. 2001. The article name 3.
            Journal of Reference Parsing Tests 3, 4, 523-524.
        </li>
        <li>Solo, H. 1999. Kessel Running: A Memoir, 1st. ed. Corellia: Corellian Press.
        </li>
        <li>Solo, H. 2000. A Ship's Manual and More. Corellia: Corellian Press.</li>
        <li>Nestington, L. 1999. A paper to cite in a nested way. Journal of
            Reference Parsing Tests 4, 5, 623-624.
        </li>
        <li>Nestington, L. 2000. Another nested paper. Bird Quarterly 1, 2, 12-20.</li>
        <li>Gratia, E. 1999. Just one example. Example Articles 1, 2, 1-20.</li>
        <li><a id="Xjadud2015aggregate"></a>
            <span class="ptmrc7t-x-x-109">J<span class="small-caps">adud</span>,
            M.&nbsp;C.  <span class="small-caps">and</span>
            D<span class="small-caps">orn</span>,  B.  </span>
            <span class="ptmr7t-x-x-109">2015. Aggregate compilation behavior: Findings
            and implications from 27,698 users. In </span><span class="ptmri7t-x-x-109">
            ICER &rsquo;15: Proceedings of the Eleventh Annual International Conference
            on International Computing Education Research
            </span><span class="ptmr7t-x-x-109">.
            Association for Computing Machinery, 131&ndash;139.</span>
        </li>
        <li><span class="ptmrc7t-x-x-109">DWYL</span><span class="ptmr7t-x-x-109">.
            2022. List of English Words. </span>
            <a href="https://example.com"><span class="pcrr7t-x-x-109">
            words_alpha.txt</span></a>
            <span class="ptmr7t-x-x-109">(accessed 14 April, 2022).</span>
        </li>
        <li>Imaginary State University. n.d. Programs at ISU.
            https://imagistate.edu/programs/ Accessed: 1998-01-17.
        </li>
    </ol>
    <h1>Appendix</h1>
    <ol><li>List item in appendix</li></ol>
    """
    example_html = """
        <p>Square bracket style [1].</p>
        <p>Range style cite [2-4].</p>
        <p>Comma style cite [6, 7].<p>
        <p>Math inclusive range [8, 100] (not citations).</p>
        <p>Negative math range [-1, 1].</p>
        <p>Citation with page numbers that seem like cites [4, pp. 14-15].<p>
        <p>Not a real reference [9].</p>
        <h1>References</h1>
    """
    example_soup = bs4.BeautifulSoup(example_html + processed_refs_html, "html.parser")
    print("Square brackets citations:\n", get_citations(example_soup, "EDM"), "\n")
    with tempfile.TemporaryDirectory() as tmpdir:
        warn.output_filename = os.path.join(tmpdir, "warn.csv")
        refs = get_references(example_soup, tmpdir, "/usr/local/bin/anystyle")
        print("References:\n", refs, "\n")
        check_citations_vs_references(
            example_soup, tmpdir, "/usr/local/bin/anystyle", "EDM", False
        )

    example_html = """
        <p>No date (Imaginary State University, nd)</p>
        <p>Possibly confusing non-cite ending with nd (here is the end)</p> 
        <p>No comma after author like with \\citeNP (e.g., Adebeyo 2008)</p>
        <p>Parse nested parentheses (e.g. Jadud and Dorn (2015)).</p>
        <p>See, for example, Namington et al. (1999).</p>
        <p>Here is a claim (Supporting Author, Another, 1999).</p>
        <p>More complex (Author A, et al., 1999a; Ablamowicz and Fauser, 2007)</p>
        <p>With page number (Namington et al., 2000, p. 5)</p>
        <p>Multiple page numbers (Namington et al., 2001, pp. 55, 66)</p>
        <p>Page numbers/ranges (Namington et al., 2001, pp. 55-57, 66, 77-87)</p>
        <p>Numbers for first ref (Namington, 1999, pp. 1-11; van der Waal, 1999)</p>
        <p>Chapter numbers (Namington et al., 2002, Ch. 5-11)</p>
        <p>Section number (Namington et al., 2003, Sec. 2)</p>
        <p>Inline with page numbers by Namington et al. (2004, pp. 12-34)</p>
        <p>Claim from van der Waal (1999).</p>
        <p>Paper from A. Authorname (1999) disambiguation method.</p>
        <p>Edited book by Editorname (2007) does not work without author.</p>
        <p>Multiple cites from same author(s) (Solo, 1999, 2000)</p>
        <p>Citing something (in a parenthetical way [Nestington, 1999]).</p>
        <p>And in inline parentheses (a claim by Nestington [2000]).</p>
        <p>Cite as example (e.g., Gratia, 1999).</p>
        <p>Two authors cited inline, like Jadud and Dorn (2015).</p>
        <p>Abbrevation cite&nbsp;(<a href="#Xwords2022">DWYL, 2022</a>)</p>
        <p>Comma-separated cites (Commaname et al., 1999, Othername et al., 1999)</p>
        <p>Cites separated by nbsp (Ganapathy et al., 2011, El Asri et al., 2017)</p>
        <p>Multi-year cites with commas (Commaname et al., 2002, 2003, Solo, 1999)</p>
        <h1>References</h1>
    """
    example_soup = bs4.BeautifulSoup(example_html + processed_refs_html, "html.parser")
    with tempfile.TemporaryDirectory() as tmpdir:
        warn.output_filename = os.path.join(tmpdir, "warn.csv")
        cites = get_citations(example_soup, "JEDM", get_lowercase_name_words(refs))
        print("\nJEDM citations:\n", cites, "\n")
        check_citations_vs_references(
            example_soup, tmpdir, "/usr/local/bin/anystyle", "JEDM", False
        )
