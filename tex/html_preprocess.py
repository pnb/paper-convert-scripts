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
    return re.sub(
        r"\xa0almbox \..*?mbox ?(</span><span class='ptmr7t-'>)?",
        " al.",
        html_str,
        flags=re.DOTALL,  # Match \n
    )
