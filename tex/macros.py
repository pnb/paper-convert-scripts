import re

from . import TeXHandler


def add_macros_for_mathjax(texer: TeXHandler) -> None:
    """Find macro definitions in Tex and copy them to the soup for MathJax to parse.

    Args:
        texer (TeXHandler): LaTeX handler containing soup and tools to modify it
    """
    # For some reason macro definitions in the MathJax config don't seem to be working
    # anymore, so we'll insert the commonly needed macros here instead.
    macros = [
        R"\def\bm#1{\boldsymbol{#1}}",
        R"\def\mathds#1{\mathbb{#1}}",
        R"\def\mathbbm#1{\mathbb{#1}}",
        R"\def\bold#1{\boldsymbol{#1}}",
    ]
    for line in texer.tex_lines:
        if line.lstrip().startswith("\\def\\"):
            macros.append(line.strip())
        for macro in re.finditer(r"(^|(?<=\W))\\newcommand[\\{].*$", line):
            macros.append(macro.group(0) + "\n")
        for macro in re.finditer(r"(^|(?<=\W))\\DeclareMathOperator\*[\\{].*$", line):
            macros.append(macro.group(0) + "\n")
    defcontainer = texer.soup.new_tag("div", attrs={"class": "hidden"})
    defcontainer.append("\\(\n  " + "\n  ".join(macros) + "\n\\)")
    texer.soup.body.insert(0, defcontainer)
