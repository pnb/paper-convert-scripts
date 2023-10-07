import re

from . import TeXHandler


def add_macros_for_mathjax(texer: TeXHandler) -> None:
    """Find macro definitions in Tex and copy them to the soup for MathJax to parse.

    Args:
        texer (TeXHandler): LaTeX handler containing soup and tools to modify it
    """
    macros = []
    for line in texer.tex_lines:
        if line.lstrip().startswith("\\def\\"):
            macros.append(line.strip())
        for macro in re.finditer(r"(^|(?<=\W))\\newcommand[\\{].*$", line):
            macros.append(macro.group(0) + "\n")
        if R"\begin{document}" in line:
            break
    if macros:
        defcontainer = texer.soup.new_tag("div", attrs={"class": "hidden"})
        defcontainer.append("\\(\n  " + "\n  ".join(macros) + "\n\\)")
        texer.soup.body.insert(0, defcontainer)
