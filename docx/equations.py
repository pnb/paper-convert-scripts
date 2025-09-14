import bs4


def fix_equations(soup: bs4.BeautifulSoup) -> None:
    """Fix some equation conversion issues, at least as much as is possible in editing
    MathML outputs. In the past, there were more of these but they eventually got fixed
    correctly in Pandoc. Hopefully that trend continues."""
    for munder in soup.select("munder"):
        # Pandoc sometimes puts a stray <mo>something</mo> in the middle of the correct
        # two children of <munder>, which will not render with <> 2 children
        child_elems = [c for c in munder.children if isinstance(c, bs4.Tag)]
        if len(child_elems) > 2:
            annotation = munder.find_parent("math").select_one("annotation")
            text = annotation.get_text() if annotation else "(no equation annotation)"
            print("Warning:", len(child_elems), "children in <munder> in:", annotation)
            print("\t(trying to automatically fix, but good to look)")
            for child in child_elems[1:-1]:
                print("\tRemoving:", child)
                child.decompose()
    # Check for equation numbers sometimes parsed by Pandoc as "#(1)" with very little
    # space before it, and with # as an extra symbol; we'll replace it with some space,
    # although this is imperfect because it does not right align and might make some
    # equations too wide
    for mtd in soup.select("mtd"):
        if (
            mtd.parent.name == "mtr"
            and mtd.parent.find_next_sibling() is None
            and mtd.parent.parent.name == "mtable"
        ):
            children = [c for c in mtd.children if isinstance(c, bs4.Tag)]
            if (
                len(children) >= 4
                and children[-1].name == "mo"
                and children[-1].get("form") == "postfix"
                and children[-1].get("stretchy") == "false"
                and children[-1].get_text() == ")"
                and children[-2].name == "mn"
                and children[-2].get_text().isdigit()
                and children[-3].name == "mo"
                and children[-3].get("form") == "prefix"
                and children[-3].get("stretchy") == "false"
                and children[-3].get_text() == "("
                and children[-4].name == "mi"
                and children[-4].get_text() == "#"
            ):
                print("Fixing equation number spacing")
                children[-4].replace_with(
                    bs4.Tag(name="mspace", attrs={"width": "50px"})
                )
