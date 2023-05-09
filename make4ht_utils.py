import re
import zipfile
import os
import shutil
import uuid
import hashlib

from shared_utils import warn_tex as warn


def get_raw_tex_contents(source_zip_path: str, extracted_dir: str) -> str:
    """Return the LaTeX contents of a source zip file as a string. Assumes there is only 1 .tex file
    in the zip file root, or that there is a file called main.tex in the zip file root.

    Args:
        source_zip_path (str): Path to LaTeX .zip file
        extracted_dir (str): Path to a directory where the zip file should be extracted

    Returns:
        str: LaTeX contents
    """
    def _load_tex_str(source_tex_filename: str):
        with open(source_tex_filename, errors='replace') as infile:
            raw_tex = infile.read()
        # Remove lines starting with %; replace with single % to avoid introducing a <p>
        raw_tex = re.sub(r'([^\\]%).*$', r'\1', raw_tex, flags=re.MULTILINE)
        # Remove \titlenote{}, which make4ht handles poorly so far
        raw_tex = re.sub(r'([^\\]|^)\\titlenote\{[^\}]*\}', r'\1', raw_tex, flags=re.MULTILINE)
        thanksparts = raw_tex.split(R'\thanks{')
        if len(thanksparts) > 1:
            raw_tex = ''
            for i, part in enumerate(thanksparts[:-1]):
                raw_tex += part + R'\footnotemark[' + str(i + 1) + R']\thanks{'
            raw_tex += thanksparts[-1]
        return raw_tex

    with zipfile.ZipFile(source_zip_path, 'r') as inzip:
        inzip.extractall(extracted_dir)
    # If only one child and it is a folder, move all contents into the parent dir
    children = [x for x in os.listdir(extracted_dir) if x != '__MACOSX']
    if len(children) == 1:
        orig_name = os.path.join(extracted_dir, children[0])
        if os.path.isdir(orig_name):
            tmp_name = os.path.join(extracted_dir, str(uuid.uuid4()))  # Rename to avoid conflicts
            shutil.move(orig_name, tmp_name)
            for fname in os.listdir(tmp_name):
                shutil.move(os.path.join(tmp_name, fname), os.path.join(extracted_dir, fname))

    tex_files = [f for f in os.listdir(extracted_dir) if f.endswith('.tex') and f != 'tmp.tex']
    if len(tex_files) == 1:
        tex_fname = tex_files[0]
    elif 'main.tex' in tex_files:
        tex_fname = 'main.tex'
    elif len(tex_files):
        tex_fname = tex_files[0]
        warn('ambiguous_tex_file', 'Using first file: ' + tex_fname)
    else:
        warn('tex_file_missing')
        exit()

    # Load tex file and any \input files
    tex_str = _load_tex_str(os.path.join(extracted_dir, tex_fname))
    input_regex = re.compile(r'\\input\s*\{\s*([^\s}]+)\s*\}')
    for _ in range(25):  # Limit \input to prevent a recursive self-include bomb
        match = input_regex.search(tex_str)
        if not match:
            break
        input_fname = match.group(1)
        if not input_fname.lower().endswith('.tex'):
            input_fname += '.tex'
        print('Including \\input file:', input_fname)
        extra_tex_str = _load_tex_str(os.path.join(extracted_dir, input_fname))
        tex_str = tex_str[:match.start()] + extra_tex_str + tex_str[match.end():]

    # Check for known issues in the raw tex
    match = re.search(r'\\end\{algorithmic\}[ \t]*\n[ \t]*[a-zA-Z]{1,20}', tex_str, re.MULTILINE)
    if match:
        warn('no_newline_after_algorithmic', match.group(0))

    tex_str = tex_str.replace(R'\Bar{', R'\bar{') \
        .replace(R'\Tilde{', R'\tilde{') \
        .replace(R'\vcentcolon', ':')

    siunitx_tabulars = re.findall(r'\\begin\{tabular.?\}\s*\{[^\[]*S\[.*\}', tex_str)
    if siunitx_tabulars:
        print('Found `siunitx` "S" column in tabular environment; please note that this can cause '
              'conversion issues especially if an S column is the last column in the table')
        for tabular in siunitx_tabulars:
            print('###', tabular, '\n')

    # Mark up {description} environments that sometimes (always?) get lost
    tex_str = tex_str.replace(R'\begin{description}',
                              R'\HCode{<p class="description-env">}\begin{description}') \
        .replace(R'\end{description}', R'\end{description}\HCode{</p>}')

    # Look for image filenames with uppercase and/or mismatching case letters, which causes issues
    # across different OSs and issues with make4ht if the filename extension is uppercase
    img_fnames = set([re.sub(r'^\./', '', x)  # Remove any ./ cur dir prefix
                      for x in get_command_content(tex_str, 'includegraphics')])
    for dir, _, fnames in os.walk(extracted_dir):
        for fname in fnames:
            path = os.path.join(dir, fname)
            relative_path = re.sub(r'^' + re.escape(extracted_dir) + r'/?', '', path).lower()
            for img in img_fnames:
                # Check if this is probably the file being referenced; this matching is imperfect
                # in situations where authors have the same image filename in two different
                # directories or the same filename with different capitalizations (terrible ideas)
                if img.lower() == relative_path or relative_path.endswith(img.lower()):
                    if fname != fname.lower():  # Uppercase letters in image filename; rename file
                        os.rename(path, os.path.join(dir, fname.lower()))
                    newimg = img[:-len(fname)] + fname.lower()
                    if newimg != img:  # Replace lowercase filename in tex
                        tex_str = tex_str.replace('{' + img + '}', '{' + newimg + '}')
                    img_fnames.remove(img)
                    break
    return tex_str


def get_command_content(tex_str: str, cmd_name: str) -> list:
    """Find the contents of all occurrences of a LaTeX command, such as "label" or "textbf".
    Ignores command parameters in square brackets if they exist.

    Args:
        tex_str (str): LaTeX code
        cmd_names (str): Command to search for (without preceding slash)

    Returns:
        list of str: content of command[params]{content} for each occurrence of command
    """
    start_regex = re.compile(r'([^\\]|^)\\(' + cmd_name + r')(\[[^]]+\])?\{')
    cmds = []
    for match in start_regex.finditer(tex_str):
        bracket_depth = 0
        for match_end in range(match.end() - 1, len(tex_str)):
            if tex_str[match_end] == '{':
                bracket_depth += 1
            elif tex_str[match_end] == '}':
                bracket_depth -= 1
                if bracket_depth == 0:
                    break
        cmds.append(tex_str[match.end():match_end])
    return cmds


def get_bib_backend(tex_str: str) -> str:
    """Try to determine what bibliography backend a paper uses. Assumes BibTeX if it can't find any
    info. Assumes Biber if it finds BibLaTeX but no backend is specified (Biber is default there).
    Returns None in the rare case that bibliography items appear hard-coded in the Tex source.

    Args:
        tex_str (str): LaTeX document source code

    Returns:
        str: Name of backend command to use for compiling (e.g., "biber", "bibtex") or None
    """
    backend_regex = re.compile(r'^\s*\\usepackage\s*(\[.*backend=(\w+).*\])?\s*\{\bbiblatex\b\}',
                               re.MULTILINE)
    match = backend_regex.search(tex_str)
    if match:
        if match.group(2):
            return match.group(2)
        return 'biber'
    if not re.search(r'^\s*\\bibliography\s*\{', tex_str, re.MULTILINE) and \
            re.search(r'^\s*\\bibitem\s*\{', tex_str, re.MULTILINE):
        return None  # Bibliography items hard-coded inito the .tex doc
    return 'bibtex'


def check_file_hash(file_path: str, sha256_expected: str):
    """Compare the SHA256 hash of a file to an expected hash. Especially useful for making sure
    authors are using the correct version of the article style, and have not modified it.

    Args:
        file_path (str): Path to file to check
        sha256_expected (str): Expected SHA256 hash
    """
    try:
        with open(file_path, 'rb') as infile:
            sha256_actual = hashlib.sha256(infile.read()).hexdigest()
    except FileNotFoundError:
        sha256_actual = ''
    if sha256_actual != sha256_expected:
        warn('file_hash_' + os.path.split(file_path)[1])
