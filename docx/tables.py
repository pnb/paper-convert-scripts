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
            # Check for existence of any <td>
            if not table.find("td"):
                warn(
                    "table_no_data",
                    "Table index "
                    + str(i + 1)
                    + '; table text: "'
                    + table.get_text(strip=True)[:15]
                    + '..."',
                )
        for td in table.find_all("td", attrs={"rowspan": True}):
            td["class"] = "has-rowspan"  # Mark rowspan cells so they can be styled

def force_table_lines(mp: MammothParser) -> None:
    """Add light lines between every row of tables for cases where the lines are needed
    but can't be detected automatically very well."""
    for table in mp.soup.find_all("table"):
        # Add .hlines-every-row class to table
        if table.get("class"):
            table["class"].append("hlines-every-row")
        else:
            table["class"] = ["hlines-every-row"]
