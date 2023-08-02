from shared.shared_utils import warn
from . import MammothParser


def check_tables(mp: MammothParser) -> None:
    """Check that tables have captions and appropriate header and text styles set."""
    for i, table in enumerate(mp.soup.find_all("table")):
        if len(table.find_all("tr")) == 1:  # Single row presentation table
            table["role"] = "presentation"
        else:
            if not table.find("caption"):
                warn(
                    "table_caption_missing",
                    "Table index "
                    + str(i + 1)
                    + '; table text: "'
                    + table.get_text(strip=True)[:15]
                    + '..."',
                )
            if not table.find("thead"):
                warn(
                    "table_header_missing",
                    "Table index "
                    + str(i + 1)
                    + '; table text: "'
                    + table.get_text(strip=True)[:15]
                    + '..."',
                )
        for td in table.find_all("td", attrs={"rowspan": True}):
            td["class"] = "has-rowspan"  # Mark rowspan cells so they can be styled
