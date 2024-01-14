# Scripts for converting paper formats

## Installation

Required Python packages are specified in `conda_env.yml`. The Python environment is specified using `conda`, which can be obtained by installing Anaconda or Miniconda (recommended).

To install the environment, run:

    conda env create -f conda_env.yml  # If this gets OOM-killed, see below

On machines with limited RAM such as small cloud servers, the out-of-memory killer may stop the conda environment creation with a "Killed" message. If so, add swap space:

```bash
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
sudo cp /etc/fstab ~/fstab-backup
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

This will create a new conda environment called `paper_convert` with the required packages installed.

LaTeX conversion requires a recent version of TexLive. TexLive 2020 and older do not properly handle subfigures, for example.

Checking reference styles also requires the *anystyle-cli* Ruby gem to be installed, e.g., via `sudo gem install anystyle-cli`.

## Configuration

Edit `config.json` to adjust the paths to required applications, including the correct Python environment and path to *anystyle*.

`messages.json` can also be used to modify the warning messages shown when something goes wrong during paper conversion.

## Using conversion scripts

Scripts can be run via the [paper-convert-www](https://github.com/pnb/paper-convert-www) frontend or from the command line.

If run from the command line, scripts must be run from the current directory. The result will be an `index.html` file in the specified output folder, which may also include `conversion_warnings.csv` containing a record of possible problems encountered during conversion. Additionally, there will be any images that are part of the paper.

Run `python main_docx.py -h` to see info on DOCX => HTML conversion. The DOCX converter also produces a `tmp.docx` file for some types of image conversion. `tmp.docx` may be safely deleted.

Run `python main_latex.py -h` to see info on LaTeX => HTML conversion. The LaTeX converter also produces a `source` temporary directory in the output, which can be deleted, and a few `tmp-*` files that can also be safely deleted.

## 3rd-part licenses

[`acm-sig-proceedings-long-author-list.csl`](./acm-sig-proceedings-long-author-list.csl) is used under the Creative Commons Attribution-ShareAlike 3.0 License. See file for authorship information.
