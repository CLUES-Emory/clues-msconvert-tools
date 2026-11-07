# thermo-raw-method-report

Helper scripts for the CLUES file-conversion workflow. The conversion scripts pull them from this repo at run time.

| Script | Purpose | Requires |
|--------|---------|----------|
| `instrument_method_report.py` | Extracts the instrument method from one `.raw` file into a formatted report (see below). | [`fisher_py`](https://pypi.org/project/fisher_py/) |
| `lc_sequence_mapfile.py` | Builds the LC-HRMS sample mapfiles, the list of files to convert, the methods table and a QC report from the Xcalibur **sequence files**. It does not open `.raw` files (see below). Used by `LC-HRMS_parallel_msconvert_v2.4.ps1`. | Python standard library |
| `mapfile_crosscheck.py` | Cross-checks a sequence-derived sample mapfile against the metadata embedded in the `.raw` files, and writes a raw-derived mapfile and a report of discrepancies and batch order. Used by LC-HRMS v2.3. Usage: `python mapfile_crosscheck.py <raw_dir_or_filelist> <sequence_mapfile> <output_prefix>` | [`fisher_py`](https://pypi.org/project/fisher_py/) |

## lc_sequence_mapfile.py

This script builds the sample mapfiles for one LC mode of a study in the CLUES standard layout:

```
<study>_<LC>\3-Sequence_Files\*.csv        Xcalibur sequence exports (the source)
<study>_<LC>\1-Raw_Files\Batch_*\*.raw     MS1  (listed only, never opened)
<study>_<LC>\1-Raw_Files\Batch_*\MSMS\*.raw MSMS (listed only, never opened)
```

**Mapfile columns:** `File.Name` ← `File Name`, `Sample.ID` ← `Sample ID`, `Batch` ← `Comment`, `Sample_type` ← `Sample Name`.

**Rules:**
- Rows stay in sequence order. The CSVs are taken in the order of the batch number in their name.
- Polarity comes from the `Instrument Method` column, then the `File Name`. It is **never** taken from row order: LC-HRMS v2.3 sorted the rows by file name and then alternated pos and neg, which mislabels about half the rows when file names contain pos/neg.
- Rows are matched to `.raw` files by name, from a folder listing:
  - Rows with no `.raw` file stay in the mapfile and are reported.
  - Only listed files are converted. Unlisted files, such as an aborted run, are reported.
  - Xcalibur's renamed repeats (`name_yyyymmddhhmmss`) are matched to the repeated rows.
  - Duplicate copies of a file are resolved by the sequence `Path`.
- Rows whose `Sample Name` is in `--exclude-types` are converted but left out of the mapfiles.

```bash
python lc_sequence_mapfile.py --raw-dir <...\1-Raw_Files> --seq-dir <...\3-Sequence_Files> \
    --out-dir <out> --study-id <ID> --lc-mode <HILIC|C18> \
    [--exclude-types MSMS,Cal_Std,PFAS-MSMS] [--min-age-minutes 15]
```

It writes `<ID>_<LC>{pos,neg}_sample_mapfile.txt` and a combined mapfile, plus `_sequence_check.tsv`, `_conversion_manifest.tsv`, `_methods.tsv`, `_mapfile_QC.txt` and `_mapfile_summary.json`. The tests are in `tests/` (`python -m unittest discover -s tests`).

## instrument_method_report.py

Extract the **instrument method** from a Thermo `.raw` file and write a
formatted, human-readable text report of every method component.

The script auto-detects the front-end configuration from the embedded method
text and formats each accordingly:

| Front end | Method 0 (front end)                | Method 1 (MS)              |
|-----------|-------------------------------------|----------------------------|
| **LC-MS** (e.g. Orbitrap Exploris 120) | LC method / Autosampler / Column oven (TCC) | ESI source |
| **GC-HRMS** (Orbitrap Exploris GC)     | GC inlet + oven program / TriPlus RSH autosampler | EI source |

The report includes File / Instrument / Sample information, the full method
detail for each component, and a **Quick Reference** block of the key
parameters.

## Requirements

- Windows with the Thermo raw-file libraries available to `fisher_py`
- Python 3.8+
- [`fisher_py`](https://pypi.org/project/fisher_py/)

```bash
pip install -r requirements.txt
```

## Usage

```bash
python instrument_method_report.py <raw_file> <output_dir>
```

Example:

```bash
python instrument_method_report.py "C:\data\B260130_GCSSL_CLU0007_006.raw" "C:\reports"
```

The report is written to `<output_dir>\<raw_basename>_method_report.txt`
(UTF-8, so `°C` / `µL` symbols render correctly).

You can also set `raw_file` / `output_dir` near the top of the script and run it
with no arguments (command-line arguments take precedence).

## Pulling into a batch script

Because this repository is public, a batch/conversion script can fetch the
latest version of the script directly, no authentication required.

**PowerShell**

```powershell
$src = "https://raw.githubusercontent.com/CLUES-Emory/thermo-raw-method-report/main/instrument_method_report.py"
$dst = Join-Path $PSScriptRoot "instrument_method_report.py"
Invoke-WebRequest -Uri $src -OutFile $dst

# then, for each raw file:
python $dst "C:\data\sample.raw" "C:\reports"
```

**curl**

```bash
curl -L -o instrument_method_report.py \
  https://raw.githubusercontent.com/CLUES-Emory/thermo-raw-method-report/main/instrument_method_report.py
```

Pin to a specific tagged release by replacing `main` with the tag (e.g.
`v1.0`) in the raw URL for reproducible batch runs.
