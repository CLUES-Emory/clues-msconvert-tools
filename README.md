# thermo-raw-method-report

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
