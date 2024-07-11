# Occasionally we need to change things much later, when it is tough to regenerate the
# proceedings from scratch.
import os
import argparse


def postprocess(paper_dir):
    with open(os.path.join(paper_dir, "index.html"), "r", encoding="utf8") as infile:
        html = infile.read()
    new_html = html.replace(
        '<script src="https://polyfill.io/v3/polyfill.min.js?features=es6"></script>',
        "",
    )
    with open(os.path.join(paper_dir, "index.html"), "w", encoding="utf8") as ofile:
        ofile.write(new_html)


print("Currently set up to remove polyfill.")

ap = argparse.ArgumentParser(description="Postprocess proceedings")
ap.add_argument("html_path", help="Path to HTML proceedings root (papers as subdirs)")
args = ap.parse_args()

for item in os.listdir(args.html_path):
    item_path = os.path.join(args.html_path, item)
    if os.path.isdir(item_path):
        if os.path.isfile(os.path.join(item_path, "index.html")):
            print("Found index.html in:", item)
            postprocess(item_path)
