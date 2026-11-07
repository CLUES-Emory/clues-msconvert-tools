# clues-msconvert-tools

This repo holds the CLUES conversion tools for Thermo `.raw` files: the LC-HRMS conversion driver, and the helper scripts that the LC-HRMS and GC-HRMS conversion scripts download from here at run time.

| Script | Purpose | Requires |
|--------|---------|----------|
| `LC-HRMS_parallel_msconvert_v2.4.ps1` | **LC-HRMS conversion driver.** For each LC mode's study folder it builds the sample mapfiles from the sequence files, writes the instrument method reports, and converts the RAW files to mzML in parallel with msconvert. | Windows PowerShell 5.1+, ProteoWizard msconvert, Python 3.8+ |
| `lc_sequence_mapfile.py` | Builds the LC-HRMS sample mapfiles, the list of files to convert, the methods table and a QC report from the Xcalibur **sequence files**. It does not open `.raw` files. The v2.4 driver downloads it at run time. | Python standard library |
| `instrument_method_report.py` | Extracts the instrument method from one `.raw` file into a formatted report. The v2.4 driver and the GC-HRMS script download it at run time. | [`fisher_py`](https://pypi.org/project/fisher_py/) |
| `mapfile_crosscheck.py` | Compares a sequence-derived mapfile with the metadata in the `.raw` files (used by LC-HRMS v2.3 and GC-HRMS v1.8). | [`fisher_py`](https://pypi.org/project/fisher_py/) |

**Contents:**
1. [Setup (one time per computer)](#setup-one-time-per-computer)
2. [LC-HRMS conversion: LC-HRMS_parallel_msconvert_v2.4.ps1](#lc-hrms-conversion-lc-hrms_parallel_msconvert_v24ps1)
3. [lc_sequence_mapfile.py](#lc_sequence_mapfilepy)
4. [instrument_method_report.py](#instrument_method_reportpy)
5. [mapfile_crosscheck.py](#mapfile_crosscheckpy)
6. [Downloading the helper scripts into other scripts](#downloading-the-helper-scripts-into-other-scripts)
7. [Tests](#tests)

---

## Setup (one time per computer)

The tools run on **Windows 10/11 (64-bit)**. Install the following in order, then run the check in step 6.

### 1. Windows PowerShell 5.1

Windows PowerShell 5.1 is built into Windows 10/11. Check the version:

```powershell
$PSVersionTable.PSVersion        # 5.1 or later
```

### 2. ProteoWizard (msconvert)

1. Download ProteoWizard from <https://proteowizard.sourceforge.io/download.html>. Choose the **Windows 64-bit** installer **that can convert vendor files**; plain installers can't read Thermo `.raw` files. Accept the vendor licence during installation.
2. The installer puts each version in its own folder, by default:
   ```
   C:\Users\<you>\AppData\Local\Apps\ProteoWizard <version> 64-bit\msconvert.exe
   ```
   Several versions can be installed side by side.
3. Find the path to `msconvert.exe`. Search only the ProteoWizard folders:
   ```powershell
   Get-ChildItem "$env:LOCALAPPDATA\Apps\ProteoWizard*" -Filter msconvert.exe -Recurse | Select-Object -ExpandProperty FullName
   ```
   If Skyline is installed, a broader search also finds Skyline's private copies under `AppData\Local\Apps\2.0\…`. Don't use those; use the one in a `ProteoWizard <version> 64-bit` folder.
4. Check that it runs:
   ```powershell
   & "C:\Users\<you>\AppData\Local\Apps\ProteoWizard <version> 64-bit\msconvert.exe" --help | Select-Object -First 1
   # Usage: msconvert [options] [filemasks]
   ```

**Telling the driver where msconvert is.** Give the full path to `msconvert.exe` in either of two ways:
- **In the script**, the usual way for a lab PC. Open `LC-HRMS_parallel_msconvert_v2.4.ps1` in a text editor and set it in the `$config` block near the top:
  ```powershell
  MSConvertPath    = "C:\Users\<you>\AppData\Local\Apps\ProteoWizard 3.0.25345.6feda23 64-bit\msconvert.exe"
  ```
- **On the command line**, which overrides the script: `-MSConvertPath "C:\...\msconvert.exe"`.

Notes:
- Use the exact versioned folder rather than "whichever is newest", so conversions stay reproducible. The run log records the path used.
- `-MapfileOnly` runs don't need msconvert.
- If the path is still the placeholder or the file doesn't exist, the driver stops before doing any work.
- The driver calls msconvert as `msconvert "<file>.raw" -o "<output folder>" --mzML --zlib --64`. Settings change this: `WriteIndex = $false` adds `--noindex`, `BinaryEncodingPrecision = "32"` uses `--32`, and `EnableCentroiding = $true` adds `--filter "peakPicking vendor msLevel=1-"`.

### 3. Python (64-bit)

1. Install **64-bit Python 3.8 or later** from <https://www.python.org/downloads/windows/>. 3.12 is the tested version. During installation, tick **"Add python.exe to PATH"**.
2. Open a **new** PowerShell window and check:
   ```powershell
   python --version                                                # Python 3.12.x
   python -c "import struct; print(struct.calcsize('P')*8, 'bit')"  # must print 64 bit
   ```
3. **If `python` opens the Microsoft Store or isn't found:** either turn off the `python.exe` / `python3.exe` aliases in *Settings → Apps → Advanced app settings → App execution aliases*, or give the driver the full path, with `PythonExe = "C:\Users\<you>\AppData\Local\Programs\Python\Python312\python.exe"` in `$config` or with `-PythonExe "<path>"`.

64-bit Python is required: `fisher_py` loads Thermo's 64-bit .NET libraries.

### 4. Python packages

From a clone of this repo:

```powershell
python -m pip install -r requirements.txt      # installs fisher_py (and its dependencies numpy and pythonnet)
```

What needs what:
- **The mapfile step** (`lc_sequence_mapfile.py`) needs only the Python standard library.
- **The method reports** (`instrument_method_report.py`) and `mapfile_crosscheck.py` need **`fisher_py`**. It ships Thermo's RawFileReader libraries itself, so no separate Thermo software is needed. It runs on the .NET Framework 4.7.2 or later that comes with Windows 10/11.
- **Without `fisher_py`**, the driver still converts and builds mapfiles, and only skips the method reports with a warning.

### 5. Get the scripts

```powershell
git clone https://github.com/CLUES-Emory/clues-msconvert-tools.git
```

Alternatively, download the ZIP from GitHub (*Code → Download ZIP*). Files from a ZIP are marked as downloaded from the internet, so unblock them once:

```powershell
Get-ChildItem -Recurse | Unblock-File
```

The driver downloads `lc_sequence_mapfile.py` and `instrument_method_report.py` from this repo on every run. Keep `lc_sequence_mapfile.py` next to the driver as the offline fallback; it's already there in a clone.

### 6. Check the setup

Paste this into PowerShell, with your msconvert path filled in. Every line should print the value shown in its comment.

```powershell
$msc = "C:\Users\<you>\AppData\Local\Apps\ProteoWizard <version> 64-bit\msconvert.exe"
"PowerShell: "  + $PSVersionTable.PSVersion                                        # 5.1.x
"msconvert:  "  + (& $msc --help 2>&1 | Select-Object -First 1)                    # Usage: msconvert ...
"Python:     "  + (python --version 2>&1)                                          # Python 3.8+
"Python bits: " + (python -c "import struct; print(struct.calcsize('P')*8)")      # 64
"fisher_py:  "  + (python -c "import importlib.metadata as m, fisher_py; print(m.version('fisher_py'))" 2>&1)   # a version number
".NET 4.x:   "  + (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full").Release        # 461808 or higher
"GitHub:     "  + (Invoke-WebRequest "https://raw.githubusercontent.com/CLUES-Emory/clues-msconvert-tools/main/lc_sequence_mapfile.py" -UseBasicParsing).StatusCode   # 200
```

Then try a mapfile-only run on a real study (see below). It needs no msconvert and converts nothing.

**Tested versions:**

| Component | Version |
|---|---|
| Windows PowerShell | 5.1 |
| ProteoWizard msconvert | 3.0.25345 (64-bit, vendor support) |
| Python | 3.12.10, 64-bit |
| fisher_py | 2.0.2 (pythonnet 3.1.0) |
| .NET Framework | 4.8.1 |

You also need read access to the instrument data drive holding the study folders, and network access to `raw.githubusercontent.com` for the helper downloads.

---

## LC-HRMS conversion: LC-HRMS_parallel_msconvert_v2.4.ps1

### Running it

```powershell
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process      # each new PowerShell window
cd <folder with the driver>

# 1. Mapfiles, QC report and method reports only (no conversion, no msconvert needed)
.\LC-HRMS_parallel_msconvert_v2.4.ps1 -StudyID CLU0000 -OutputDirectory "D:\path\to\output" `
    -HILICPath "R:\<USERNAME>\1-RAW Files\<date>-RawFiles_LC-<model>-<Instrument>\CLU0000_YYMMDD_NAME_HILIC" `
    -C18Path   "R:\<USERNAME>\1-RAW Files\<date>-RawFiles_LC-<model>-<Instrument>\CLU0000_YYMMDD_NAME_C18" -MapfileOnly

# 2. Read <OutputDirectory>\<LC>\<StudyID>_<LC>_mapfile_QC.txt, then run the same command
#    without -MapfileOnly (with MSConvertPath set in $config, or add -MSConvertPath "<path>")
```

**Study folders.** `HILICPath` and `C18Path` are the full paths of each mode's study folder, the one that holds `1-Raw_Files` and `3-Sequence_Files`. **Leave one blank to convert only the other mode.** On the command line, omit it, or pass `-HILICPath ""` to override a path set in `$config`. Nothing is searched for. Before any work starts, the script stops if:
- neither path is set
- a folder doesn't exist
- a folder lacks `1-Raw_Files` or `3-Sequence_Files`
- both paths are the same folder
- a folder name ends in the other mode's suffix (for example a `…_C18` folder given as `HILICPath`), which catches swapped paths

A folder name that doesn't end in `_HILIC` or `_C18` only triggers a warning.

### Settings

Each setting can be set in the `$config` block at the top of the script. The ones with a parameter can also be given on the command line, which overrides the script.

| Setting | Parameter | Default | Meaning |
|---|---|---|---|
| `StudyID` | `-StudyID` | *(required)* | Prefix for output file names, e.g. `CLU0000` |
| `OutputDirectory` | `-OutputDirectory` | *(required)* | Where mzML, mapfiles, reports and logs go |
| `HILICPath`, `C18Path` | `-HILICPath`, `-C18Path` | blank | Each mode's study folder; a blank path skips the mode |
| `MSConvertPath` | `-MSConvertPath` | *(required to convert)* | Full path to `msconvert.exe` ([setup step 2](#2-proteowizard-msconvert)) |
| `PythonExe` | `-PythonExe` | `python` | Python executable, by name on PATH or as a full path |
| `MaxParallelJobs` | | 6 | Parallel msconvert jobs (4–6 when reading from a network drive) |
| `TimeoutMinutes` | | 10 | Per-file limit; msconvert is stopped and its partial output removed |
| `SkipExisting` | | `$true` | Skip files that already have a complete mzML |
| `WriteIndex`, `BinaryEncodingPrecision`, `EnableCentroiding` | | `$true`, `"64"`, `$false` | msconvert output options (see setup step 2) |
| `ExcludeSampleTypes` | | `MSMS, Cal_Std, PFAS-MSMS` | Sequence `Sample Name` values left out of the mapfiles; their files are still converted |
| `SkipFilesNewerThanMinutes` | | 15 | RAW files modified more recently than this are converted on a later run |
| `GenerateMethodReport` | | `$true` | One report per distinct method (needs `fisher_py`) |
| `MapfileScriptUrl`, `MethodReportScriptUrl` | | this repo, `main` | Where the helpers are downloaded from; set `MapfileScriptUrl = ""` to use the local copy only |
| `WriteRunLog` | | `$true` | Writes the console transcript to `<OutputDirectory>\<StudyID>_conversion_log_<timestamp>.txt` |
| | `-MapfileOnly` | off | Builds the mapfiles, QC report and method reports without converting |

### Layout and output

```
<HILICPath or C18Path>\                     e.g. ...\CLU0000_YYMMDD_NAME_HILIC\
    3-Sequence_Files\*.csv                  source of the mapfiles (top level only; Archive\ is ignored)
    1-Raw_Files\Batch_*\*.raw               MS1   -> <OutputDirectory>\<LC>\1a-<LC>_mzML\
    1-Raw_Files\Batch_*\MSMS\*.raw          MSMS  -> <OutputDirectory>\<LC>\1a-<LC>_mzML\<LC>_MSMS\
```

| File in `<OutputDirectory>\<LC>\` | Contents |
|---|---|
| `<ID>_<LC>pos_sample_mapfile.txt`, `<ID>_<LC>neg_sample_mapfile.txt` | Mapfiles for data extraction (`File.Name, Sample.ID, Batch, Sample_type`), in sequence order. Tab-separated, UTF-8 without a BOM. |
| `<ID>_<LC>_sample_mapfile.txt` | Both polarities, plus `Polarity, Seq_Order, Seq_File, Instrument_Method, RAW_Found` |
| `<ID>_<LC>_mapfile_QC.txt` | **Read this first.** Warnings, a per-CSV table, sample types, methods, rows with no RAW file, RAW files not converted, flagged rows |
| `<ID>_<LC>_sequence_check.tsv` | Every sequence row (status, matched RAW file, flags) and every RAW file not used |
| `<ID>_<LC>_conversion_manifest.tsv` | The RAW files to convert |
| `<ID>_<LC>_methods.tsv` | Distinct methods and their representative RAW files |
| `2-Method_Report\` | One `<ID>_<method>_method_report.txt` per method, plus `<ID>_<LC>_method_summary.txt` |
| `<ID>_<LC>{pos,neg}_missing_files.txt` | Mapfile entries with no mzML |
| `<ID>_<LC>_{RAW,MSMS}_conversion_{success,failures}.txt` | Conversion logs for this run, including msconvert's error lines |
| `<ID>_<LC>_mapfile_summary.json` | A machine-readable summary |

The MS1 listings (the skip check, the missing-files check, and the data-extraction step) aren't recursive, so the `<LC>_MSMS\` subfolder never mixes with the MS1 files.

### How the mapfile is built

The mapfile is built from the sequence files, as described under [lc_sequence_mapfile.py](#lc_sequence_mapfilepy). In short:
- Polarity comes from the `Instrument Method` column (then the file name), **never from row order**.
- Rows keep sequence order.
- Rows with no RAW file stay in the mapfile and are reported.
- Only RAW files listed in a sequence are converted.

**Which RAW files are opened:** msconvert opens the files it converts. Apart from that, only one representative file per distinct instrument method is opened, for the method report.

### Method reports

The distinct methods, MS1 and MSMS, come from the sequence's `Instrument Method` column. For each, the first listed RAW file that will be converted is the representative, and `instrument_method_report.py` is run on it. A method with no RAW file yet is skipped until a later run. The reports are rebuilt on every run.

Methods are told apart by file name only. A method edited mid-study but saved under the same name gets one report, from its first injection.

### Re-running

Run the same command again at any time:
- Files with a complete mzML are skipped.
- Incomplete mzML (for example from a stopped run) are converted again.
- Mapfiles and QC are rebuilt from the current sequence files.
- New batches are picked up once their CSV is in `3-Sequence_Files\`.

### Troubleshooting

- **"running scripts is disabled on this system"**: run `Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process` in that window first. If the files came from a ZIP, also run `Unblock-File` (setup step 5).
- **"Set these values …: MSConvertPath"** or **"msconvert.exe not found"**: set `MSConvertPath` to the full path from setup step 2.
- **"Python ('python') not found"**, or Python opens the Microsoft Store: see setup step 3, or set `PythonExe` to the full path.
- **"fisher_py is not installed"** or method reports skipped: run `python -m pip install -r requirements.txt` with the same Python the driver uses.
- **"lc_sequence_mapfile.py is not available"**: the download failed and there's no copy next to the driver. Keep the repo's copy next to the driver, or check access to GitHub.
- **"HILICPath points at a C18 folder"** (or the reverse): the two paths are swapped.
- **"is not a study folder"**: give the folder that holds `1-Raw_Files` and `3-Sequence_Files`, not `1-Raw_Files` itself.
- **"no sequence rows found"**: `3-Sequence_Files\` has no CSV with a `File Name` header row.
- **Many rows with no RAW file**: the sequence lists injections that haven't run yet, or file names were changed after export. See the QC report.
- **A conversion failed**: the failure log has msconvert's message (for example `Corrupt RAW file`). To test one file by hand: `& "<msconvert.exe>" "<file>.raw" -o "D:\test" --mzML`.
- **Paths of 260 characters or more**: Thermo's reader and msconvert can't open them. Use a shorter output location.
- **Centroiding**: check the scan filter in the method report. `FTMS + c …` means the data were acquired centroided, so `EnableCentroiding = $false` keeps them as they are.

---

## lc_sequence_mapfile.py

This script builds the sample mapfiles for one LC mode of a study in the CLUES standard layout:

```
<study>_<LC>\3-Sequence_Files\*.csv          Xcalibur sequence exports (the source)
<study>_<LC>\1-Raw_Files\Batch_*\*.raw       MS1  (listed only, never opened)
<study>_<LC>\1-Raw_Files\Batch_*\MSMS\*.raw  MSMS (listed only, never opened)
```

**Mapfile columns:** `File.Name` ← `File Name`, `Sample.ID` ← `Sample ID`, `Batch` ← `Comment`, `Sample_type` ← `Sample Name`.

**Rules:**
- **Rows:** every row of every CSV directly in `3-Sequence_Files\`. The header is the first line containing `File Name`.
- **Order:** the CSVs are taken in the order of the batch number in their name (`_01_` before `_10_`), and rows keep their sequence order.
- **Polarity** comes from the `Instrument Method` column, then the `File Name`. It is **never** taken from row order: LC-HRMS v2.3 sorted the rows by file name and then alternated pos and neg, which mislabels about half the rows when file names contain pos/neg. A row with no polarity is reported and left out. If the method and the file name disagree, the row is flagged.
- **MSMS rows** (sequence `Path` ending in `\MSMS`) are converted but never go into the mapfiles.
- **Excluded types:** rows whose `Sample Name` is in `--exclude-types` are converted but left out of the mapfiles. So are rows recorded with the other LC mode's method.
- **Matching rows to `.raw` files** is by name, from a folder listing:
  - Rows with no `.raw` file stay in the mapfile and are reported.
  - Only listed files are converted. Unlisted files, such as an aborted run or files in `Temp\`, are reported.
  - Xcalibur's renamed repeats (`name_yyyymmddhhmmss`) are matched to the repeated rows.
  - Duplicate copies of a file are resolved by the sequence `Path`.
  - Files modified in the last `--min-age-minutes` are left for a later run.
- **QC flags:**
  - `polarity_method(…)!=file_name(…)`: the method and the file name give different polarities
  - `method_LC(…)!=study_LC(…)`: the row was recorded with the other LC mode's method
  - `comment_batch(n)!=folder_batch(m)`: the Comment batch differs from the Batch folder number
  - `in_folder(…)!=sequence_path(…)`: the file isn't in the folder the sequence `Path` names
  - `file_name_in_more_than_one_csv`: the same file name is in more than one CSV
  - `comment_not_numeric`: the Comment is not a batch number
  - `xcalibur_renamed_file`: the row was matched to an Xcalibur-renamed file

```powershell
python lc_sequence_mapfile.py --raw-dir <...\1-Raw_Files> --seq-dir <...\3-Sequence_Files> `
    --out-dir <out> --study-id <ID> --lc-mode <HILIC|C18> `
    [--exclude-types MSMS,Cal_Std,PFAS-MSMS] [--min-age-minutes 15]
```

It writes the mapfiles and QC files listed in [Layout and output](#layout-and-output).

---

## instrument_method_report.py

This script extracts the **instrument method** from a Thermo `.raw` file and writes a formatted, human-readable text report of every method component. It detects the front-end configuration from the embedded method text and formats each one accordingly:

| Front end | Method 0 (front end) | Method 1 (MS) |
|-----------|----------------------|---------------|
| **LC-MS** (e.g. Orbitrap Exploris 120) | LC method / Autosampler / Column oven (TCC) | ESI source |
| **GC-HRMS** (Orbitrap Exploris GC) | GC inlet + oven program / TriPlus RSH autosampler | EI source |

The report includes File, Instrument and Sample information, the full method detail for each component, and a **Quick Reference** block of the key parameters.

**Requires** `fisher_py` (setup step 4).

```powershell
python instrument_method_report.py <raw_file> <output_dir>
python instrument_method_report.py "C:\data\<prefix>_001.raw" "C:\reports"
```

The report is written to `<output_dir>\<raw_basename>_method_report.txt` (UTF-8, so `°C` and `µL` render correctly). You can also set `raw_file` and `output_dir` near the top of the script and run it with no arguments; command-line arguments take precedence.

---

## mapfile_crosscheck.py

The LC-HRMS v2.3 and GC-HRMS v1.8 scripts use this. It reads every `.raw` file's embedded Sample ID, Comment and Sample Name, plus its `Batch_*` folder, and builds a mapfile from them. It then compares that with the sequence-derived mapfile and reports:
- RAW files missing from the mapfile
- mapfile rows with no RAW file
- Comment-batch vs folder mismatches
- duplicate file names
- batch-order inversions

The v2.4 driver doesn't use it.

```powershell
python mapfile_crosscheck.py <raw_dir_or_filelist> <sequence_mapfile> <output_prefix> [exclude_types]
```

**Requires** `fisher_py`. It reads every RAW file (about 0.5–1 s each), so it takes several minutes per study. The RAW-derived mapfile is cached and reused; delete it to read the files again.

---

## Downloading the helper scripts into other scripts

Because this repository is public, a script can download the latest version of a helper directly, with no authentication:

```powershell
$src = "https://raw.githubusercontent.com/CLUES-Emory/clues-msconvert-tools/main/instrument_method_report.py"
$dst = Join-Path $PSScriptRoot "instrument_method_report.py"
Invoke-WebRequest -Uri $src -OutFile $dst -UseBasicParsing
python $dst "C:\data\sample.raw" "C:\reports"
```

The URLs above follow `main`. For runs that must be exactly reproducible, use a commit SHA in place of `main` in the URL, since the repo has no release tags yet.

This repo was renamed from `thermo-raw-method-report`. GitHub redirects the old URLs, so a new repo must never take that name.

---

## Tests

```powershell
python -m unittest discover -s tests -v     # lc_sequence_mapfile.py; no RAW files or network needed
```
