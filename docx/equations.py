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
