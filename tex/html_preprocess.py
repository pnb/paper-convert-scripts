def fix_et_al(html_str: str) -> str:
    """Fix a strange "et al." issue that occurs with some papers. It is possible the
    compilation process is slightly wrong. This is related to LaTeX adding \\mbox in
    citations that have "et al.", which also causes the compile error
    `Command \: unavailable in encoding OT1.`

    Args:
        html_str (str): Make4ht output *before* being put into BeautifulSoup

    Returns:
        str: Modified HTML string
    """
    # First replace the version with a space after the last mbox, then without
    return html_str.replace(
        "\xa0almbox .<span class='accentb'>:</span>mbox ", " al."
    ).replace("\xa0almbox .<span class='accentb'>:</span>mbox", " al.")
