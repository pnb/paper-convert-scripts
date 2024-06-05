import re


def fix_et_al(html_str: str) -> str:
    """Fix a strange "et al." issue that occurs with some papers. It is possible the
    compilation process is slightly wrong. This is related to LaTeX adding \\mbox in
    citations that have "et al.", which also causes the compile error
    `Command \\: unavailable in encoding OT1.`

    Args:
        html_str (str): Make4ht output *before* being put into BeautifulSoup

    Returns:
        str: Modified HTML string
    """
    # The </span> version occurs during footnote citations
    html = re.sub(
        r"\xa0almbox \..*?mbox ?(</span><span class='ptmr7t-'>)?",
        " al.",
        html_str,
        flags=re.DOTALL,  # Match \n
    )
    # Additional JEDM ones with SVGs inserted that are super complicated
    html = re.sub(
        r"\xa0al.{,45}?mbox.{,110}?mbox ?</span>\s*<span\s*class=.ptmr7t-[^>]+>",
        " al.",
        html,
        flags=re.DOTALL,
    )
    return html


def lua_font_remap(html_str: str) -> str:
    """Remap the slightly different fonts LuaLaTeX produces.

    Args:
        html_str (str): Make4ht output *before* being put into BeautifulSoup

    Returns:
        str: Modified HTML string
    """
    return html_str.replace("8r-x-x-", "8t-x-x-")
