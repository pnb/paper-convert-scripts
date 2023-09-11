def fix_et_al(html_str: str) -> str:
    """Fix a strange "et al." issue that occurs with some papers. It is possible the
    compilation process is slightly wrong.

    Args:
        html_str (str): Make4ht output *before* being put into BeautifulSoup

    Returns:
        str: Modified HTML string
    """
    return html_str.replace("\xa0almbox .<span class='accentb'>:</span>mbox", " al.")
