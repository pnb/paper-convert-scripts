import re

import bs4

import shared.shared_utils as shared_utils
from shared.shared_utils import warn_tex as warn


class TeXHandler:
    def __init__(
        self, tex_str: str, soup: bs4.BeautifulSoup, input_template: str = "EDM"
    ) -> None:
        """Create an instance of a class with a set of functions useful for
        postprocessing a document BeautifulSoup object given its source LaTeX string.
        Some functions need to be called before others.

        Args:
            tex_str (str): LaTeX document source code
            soup (bs4.BeautifulSoup): BeautifulSoup document object
        """
        self.tex_lines = tex_str.split("\n")
        self.soup = soup
        self.input_template = input_template
        self.env_start_regex = re.compile(r"(^|[^\\])\\begin\{(.+)\}")
        self.env_end_regex = re.compile(r"(^|[^\\])\\end\{")

        # Remove <hr>s added all over the place
        for hr in soup.find_all("hr"):
            hr.decompose()

        # Remove <br>s in links (sometimes \\ by authors due to LaTeX URL word-wrapping
        # troubles)
        for a in soup.find_all("a", attrs={"href": re.compile(r"https?://.*")}):
            for br in a.find_all("br"):
                br.decompose()

        # Remove random PICT thing it adds; later should delete all empty <p>
        pict_img = soup.find("img", attrs={"alt": "PICT"})
        if pict_img and "0x." in pict_img["src"]:
            top_parent = pict_img
            cur_elem = pict_img.parent
            while cur_elem.parent:
                if cur_elem.name == "p":
                    top_parent = cur_elem
                cur_elem = cur_elem.parent
            top_parent.decompose()

        self._copy_def_commands()

    def tex_line_num(self, soup_elem: bs4.Tag) -> int:
        """Get the line number of LaTeX code corresponding to a BeautifulSoup element
        (1-indexed). This works by using the comments make4ht adds to the soup, which
        are usually accurate but may be imprecise for commands like \\maketitle that
        rely on many other lines.

        Args:
            soup_elem (bs4.Tag or bs4.NavigableString): HTML element to find in Tex

        Returns:
            int: Line number (1-indexed) or 0 if no make4ht comment could be found
        """
        comment = soup_elem
        while comment:
            comment = comment.find_previous(string=lambda x: isinstance(x, bs4.Comment))
            if comment and comment.strip().startswith("l. "):
                return int(comment.strip().split(" ")[-1])
        return 0

    def find_image_line_num(self, starting_line_num: int, fname: str) -> int:
        """Find a LaTeX line number after a given line number that includes a specific
        image file (ignoring the subdirectory and extension which may differ due to
        conversion). Useful for cases where Make4ht does not provide the latest line
        number.

        Args:
            starting_line_num (int): Starting point, usually from `tex_line_num()`
            fname (str): Filename to look for (case insensitive)

        Returns:
            int: Line number, or starting line number if the image was not found
        """
        prefix = re.sub(r".*/", "", fname.lower())
        prefix = re.sub(r"\.[^.]+$", "", prefix)
        prefix = prefix.rstrip("-")  # SVG conversion adds this for some reason
        fname_regex = re.compile(r"[^{}]*\b" + prefix + r"[.}]")
        for i in range(starting_line_num - 1, len(self.tex_lines)):
            curline = self.tex_lines[i].lower()
            if R"\includegraphics" in curline and re.findall(fname_regex, curline):
                return i + 1
        return starting_line_num

    def tex_line(self, soup_elem: bs4.Tag) -> str:
        """Get the line of LaTeX code corresponding to a BeautifulSoup element. See
        `tex_line_num()` documentation.

        Args:
            soup_elem (bs4.Tag or bs4.NavigableString): HTML element to find in Tex

        Returns:
            str: Line of LaTeX code or '' if no make4ht comment could be found
        """
        line_num = self.tex_line_num(soup_elem)
        if line_num:
            return self.tex_lines[line_num - 1]
        return ""

    def merge_elements(self, elem_name: str = "span") -> None:
        """Merge consecutive elements that share the same class and (optionally) style;
        make4ht adds many of these.

        Args:
            elem_name (str, optional): Tag name to process. Defaults to 'span'.
        """
        for elem in self.soup.find_all(elem_name, attrs={"class": True}):
            prev = elem.previous_sibling
            if prev and prev.name == elem_name:
                class1 = prev["class"] if prev.has_attr("class") else ""
                class2 = elem["class"] if elem.has_attr("class") else ""
                style1 = prev["style"] if prev.has_attr("style") else ""
                style2 = elem["style"] if elem.has_attr("style") else ""
                if class1 == class2 and style1 == style2:
                    elem.insert(0, prev)
                    prev.unwrap()

    def format_equations(self) -> None:
        """Replace <table> wrappers for equations with <span> that can by styled with
        CSS. Tables should not be used for layout since an equation is not tabular data.
        """
        # Replace table wrappers for equations, since they are not real tables
        for eq_table in self.soup.select("table.equation, table.equation-star"):
            eq = eq_table.find("td")
            num = eq.next_sibling
            eq_table.insert_before(eq)
            eq.name = "span"
            eq["class"] = "math display"
            if num:
                eq.append(num)
                num.name = "span"
                num["class"] = "equation-number"
            eq_table.decompose()
            # Repair occasional MathML generation errors (specific to TexLive version)
            for elem in eq.find_all(["mrow", "mstyle", "mtd"]):
                for child in elem.contents:
                    if (
                        isinstance(child, bs4.NavigableString)
                        and not isinstance(child, bs4.Comment)
                        and child.strip()
                    ):
                        if re.match(r"\d.*", child.strip()):
                            child.wrap(self.soup.new_tag("mn"))  # Number
                        elif re.match(r"[\+\-\*\/=><&\|%!\^\(\)\?]", child.strip()):
                            child.wrap(self.soup.new_tag("mo"))  # Operator
                        else:
                            child.wrap(self.soup.new_tag("mi"))  # Identifier
            for elem in eq.find_all("mo"):
                if all(
                    isinstance(c, bs4.Tag) and c.name == "mtr" for c in elem.contents
                ):
                    elem.unwrap()  # Extraneous <mo> surrounding <mtr> elements
                elif re.match(r"[a-zA-Z]", elem.get_text(strip=True)):
                    elem.name = "mi"  # Identifier, not operator (e.g., "M" in MSE)

    def fix_fonts(self) -> None:
        """Insert HTML elements where needed to mark up typeface and font options
        specified by class by make4ht. This relies on specific abbreviations for fonts
        (e.g., "aeb10") and is probably very brittle.
        """
        class_elem_map = {
            "aeb10-": "strong",
            "aeti9-": "em",
            "aeti8-": "em",
            "aeti7-": "em",
            "phvbo8t-": "em",  # Title oblique
            "aett9-": "code",
            "ectt-": "code",
            "ectc-": "code",
            "pcrr7t-x-x-120": "code",
            "ptmb7t-x-x-120": "strong",
            "ptmri7t-x-x-120": "em",
            "ptmri7t-x-x-109": "em",
            "aebxti-": ["strong", "em"],
            "aer-7": None,  # Unwrap; not a good/necessary style to keep (tiny text)
        }
        for prefix, name in class_elem_map.items():
            for elem in self.soup.find_all(
                "span", attrs={"class": lambda x: x and x.startswith(prefix)}
            ):
                if not name:
                    elem.unwrap()
                elif isinstance(name, str):
                    elem.name = name
                else:
                    elem.name = name[-1]
                    for nested in reversed(name[:-1]):
                        wrapper = self.soup.new_tag(nested)
                        elem.insert_before(wrapper)
                        wrapper.append(elem)
                        elem = wrapper
        # Unnecessary styles
        for caption in self.soup.find_all(["caption", "figcaption"]):
            for elem in caption.find_all("strong"):
                elem.unwrap()

    def fix_references(self) -> None:
        """Format the references section. Requires that fonts have already been fixed to
        make finding the references section easier.
        """
        ref_heading = shared_utils.get_elem_containing_text(
            self.soup, "h1", "references"
        )
        if not ref_heading:
            return  # Already going to warn about this in style check
        new_ref_regex = re.compile(r"\[\d+\]\s*")
        ref_section = self.soup.new_tag("ol", attrs={"class": "references"})
        biber_section = ref_heading.find_next("dl")
        if biber_section:  # Biber style
            for elem in reversed(biber_section.find_all("dd")):
                if elem.find("p"):
                    elem.p.unwrap()
                ref_section.append(elem)
                elem.name = "li"
                doi = elem.find("a")
                if doi and doi.has_attr("href") and not doi["href"].startswith("http"):
                    doi["href"] = "https://doi.org/" + doi["href"]
            biber_section.decompose()
        else:  # Bibtex style
            cur_li = self.soup.new_tag("li")
            ref_section.append(cur_li)
            for elem in reversed(ref_heading.find_next("p").contents):
                if isinstance(elem, bs4.NavigableString) and new_ref_regex.search(elem):
                    new_str = new_ref_regex.sub("", elem)
                    if new_str.strip():
                        cur_li.insert(0, new_ref_regex.sub("", elem))
                    elem.replace_with("")
                else:
                    cur_li.insert(0, elem)
                if (
                    not isinstance(elem, bs4.NavigableString)
                    and elem.name == "a"
                    and not elem.get_text()
                ):
                    cur_li = self.soup.new_tag("li")
                    ref_section.insert(0, cur_li)
            # Remove first empty ref number added
            ref_section.find("li").decompose()
        ref_heading.insert_after(ref_section)

    def remove_unused_ids(self) -> None:
        """Remove any leftover `id` attributes that are never referenced by `href`
        values. This must be done only *after* we are sure the id attributes are not
        needed; for example, after CSS has been inlined.
        """
        used_ids = [
            a["href"].replace("#", "")
            for a in self.soup.find_all("a")
            if a.has_attr("href")
        ]
        for elem in self.soup.find_all(attrs={"id": lambda x: x and x not in used_ids}):
            del elem["id"]
            if elem.name == "a" and not elem.has_attr("href"):
                elem.decompose()  # Remove unused anchors

    def get_tex_environment(self, tex_line_num: int) -> "tuple[int, int]":
        """Get the LaTeX environment that contains a specified line number, assuming the
        environment consists of a \\begin{something} and \\end{something} pair. If the
        line number corresponds to a begin or end command, that will the environment
        returned (rather than its parent).

        It will handle nested environments (e.g., for subfigures) by counting the number
        of begin and end commands encountered.

        Args:
            tex_line_num (int): Line number

        Returns:
            tuple[int, int]: Tuple of (begin, end) line numbers
        """
        env_depth = 1
        for start_line_num in range(tex_line_num, -1, -1):
            if self.env_end_regex.search(self.tex_lines[start_line_num]):
                env_depth += 1
            if self.env_start_regex.search(self.tex_lines[start_line_num]):
                env_depth -= 1
                if env_depth == 0:
                    break
        else:
            warn("tex_env_parse_fail", tex_line_num)
        for end_line_num in range(start_line_num, len(self.tex_lines)):
            if self.env_start_regex.search(self.tex_lines[end_line_num]):
                env_depth += 1
            if self.env_end_regex.search(self.tex_lines[end_line_num]):
                env_depth -= 1
                if env_depth == 0:
                    break
        else:
            warn("tex_env_parse_fail", tex_line_num)
        return (start_line_num, end_line_num)

    def _copy_def_commands(self) -> None:
        """Find \\def commands in Tex and copy them to the soup for MathJax to parse."""
        defs = []
        for line in self.tex_lines:
            if line.lstrip().startswith("\\def\\"):
                defs.append(line.strip())
        if defs:
            defcontainer = self.soup.new_tag("div", attrs={"class": "hidden"})
            defcontainer.append("\\(\n  " + "\n  ".join(defs) + "\n\\)")
            self.soup.body.insert(0, defcontainer)
