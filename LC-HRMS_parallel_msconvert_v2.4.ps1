<#
.SYNOPSIS
    Parallel msconvert for LC-HRMS RAW files in the CLUES standard study layout.

.DESCRIPTION
    Converts Thermo RAW files to mzML in parallel and writes the sample mapfiles
    used by 6-Data_Extraction, for any untargeted LC-HRMS study stored as:

        <study folder for one LC mode, e.g. ...\CLU0000_YYMMDD_NAME_HILIC>\
            1-Raw_Files\Batch_*\*.raw            MS1 files   -> 1a-<LC>_mzML
            1-Raw_Files\Batch_*\MSMS\*.raw       MSMS files  -> 1a-<LC>_mzML\<LC>_MSMS
            3-Sequence_Files\*.csv               Xcalibur sequence exports

    Give the study folder for each LC mode explicitly (HILICPath, C18Path); a mode
    left blank is not processed. Nothing is searched for. The mapfiles and the list of files to
    convert come from the Xcalibur sequence files (lc_sequence_mapfile.py, Python
    standard library). RAW files are only converted by msconvert, and one RAW file
    per distinct method is read for the method reports.

    Helper scripts are pulled from GitHub at run time, both from
    CLUES-Emory/clues-msconvert-tools: lc_sequence_mapfile.py (mapfiles; falls
    back to the copy next to this script, then the last download) and
    instrument_method_report.py (method reports; optional).

.NOTES
    Script Version: 2.4.1
    Author: CLUES Lab, Emory University

    Version History:
    - v2.0: Initial LC-HRMS multi-instrument support
    - v2.1: Automatic sequence file path generation using instrument paths
    - v2.2: Optional centroiding, WriteIndex, BinaryEncodingPrecision
    - v2.3 (2026-09-08): Instrument method report step; instruments selected
            per LC mode by name; mapfile sort + RAW cross-check.
    - v2.4 (2026-11-07): General version for any study in the standard layout.
            * FIX: polarity is no longer assigned by odd/even row. v2.3 sorted the
              sequence rows by file name and then alternated pos/neg, which puts
              about half of the files in the wrong polarity mapfile whenever file
              names contain pos/neg (108 of 214 rows in one test study).
              Polarity now comes from the sequence "Instrument Method" column
              (then the File Name), never from row order.
            * Mapfiles still come from the sequence CSVs (File Name, Sample ID,
              Comment -> Batch, Sample Name -> Sample_type), in sequence order:
              CSVs by the batch number in their name, rows as listed.
              Output format (File.Name, Sample.ID, Batch, Sample_type) unchanged.
            * Each sequence row is matched to its RAW file by name (listing only;
              RAW files are not opened). Rows with no RAW file stay in the mapfile
              and are reported. Only RAW files listed in a sequence are converted;
              unlisted files (e.g. an aborted run) are reported, not converted.
              Xcalibur's renamed repeats (name_yyyymmddhhmmss) are matched to the
              repeated sequence rows.
            * The study folder of each LC mode is given explicitly (HILICPath,
              C18Path); a blank path skips that mode. Replaces the instrument
              registry, StudyFolderName and LCModes. A path whose folder name
              ends in the other mode's suffix (e.g. _C18 given as HILICPath) is
              rejected.
            * MSMS mzML go to 1a-<LC>_mzML\<LC>_MSMS (was 1b-<LC>_mzML_MSMS).
            * RAW files modified < SkipFilesNewerThanMinutes ago (still being
              acquired) are left for the next run.
            * Incomplete mzML files (e.g. from a killed or timed-out msconvert)
              are detected and reconverted; msconvert is stopped at the timeout and
              partial output removed; the real msconvert error is logged.
            * Method reports: one per distinct method in the sequence (MS1 + MSMS),
              read from one representative RAW file each.
            * QC report, per-row sequence check and a run log are written.
            The msconvert settings and conversion engine are unchanged from v2.3.
            Developed with Claude Opus 5.5 via Claude Code.
    - v2.4.1 (2026-11-08): Method reports also as JSON
            (<ID>_<method>_method_report.json) and one summary of all methods per
            LC mode (2-Method_Report\<ID>_<LC>_method_summary.json). The reports now
            include the LC gradient (binary-pump methods were not read before) and
            the dual-column setup. Conversion and mapfiles unchanged.

    Requirements: Windows PowerShell 5.1+, ProteoWizard msconvert, Python 3.8+
    (standard library for the mapfiles; fisher_py for the method reports only).

    BEFORE RUNNING: Execute this command in PowerShell to allow script execution:
        Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process

.EXAMPLE
    Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
    cd <folder holding this script>
    .\LC-HRMS_parallel_msconvert_v2.4.ps1

.EXAMPLE
    # Settings can also be given on the command line (they override $config):
    .\LC-HRMS_parallel_msconvert_v2.4.ps1 -StudyID CLU0000 -OutputDirectory D:\path\to\output `
        -HILICPath "R:\<USERNAME>\1-RAW Files\<date>-RawFiles_LC-<model>-<Instrument>\CLU0000_YYMMDD_NAME_HILIC" `
        -C18Path   "R:\<USERNAME>\1-RAW Files\<date>-RawFiles_LC-<model>-<Instrument>\CLU0000_YYMMDD_NAME_C18"

.EXAMPLE
    # One mode only: leave the other path blank (in $config, or pass it as "")
    .\LC-HRMS_parallel_msconvert_v2.4.ps1 -StudyID CLU0000 -OutputDirectory D:\path\to\output `
        -C18Path "R:\...\CLU0000_YYMMDD_NAME_C18" -HILICPath ""
#>

param(
    [string]$StudyID,
    [string]$OutputDirectory,
    [string]$HILICPath,
    [string]$C18Path,
    [string]$MSConvertPath,
    [string]$PythonExe,
    [switch]$MapfileOnly       # build mapfiles / QC / method reports only; no conversion
)

#===============================================================================
# CONFIGURATION - Edit this section for your study
# -----------------------------------------------------------------------------
# Values shown as <PLACEHOLDER> MUST be replaced (here or on the command line).
# Do not commit real data paths, machine paths, or usernames to a public repo.
#===============================================================================

$config = @{
    #---------------------------------------------------------------------------
    # STUDY SETTINGS
    #---------------------------------------------------------------------------
    # Study ID for output file naming, e.g. "CLU0000"
    StudyID          = "<STUDY_ID>"

    # Output directory for mzML files, mapfiles and logs
    OutputDirectory  = "<PATH_TO_OUTPUT_DIRECTORY>"

    #---------------------------------------------------------------------------
    # STUDY FOLDERS (one per LC mode)
    #---------------------------------------------------------------------------
    # Full path of each LC mode's study folder: the folder that holds 1-Raw_Files
    # and 3-Sequence_Files. Leave a mode blank ("") to skip it; at least one is
    # required. Nothing is searched for: only these folders are used.
    #   e.g. "R:\<USERNAME>\1-RAW Files\<date>-RawFiles_LC-<model>-<Instrument>\CLU0000_YYMMDD_NAME_HILIC"
    HILICPath        = ""
    C18Path          = ""

    #---------------------------------------------------------------------------
    # MSCONVERT SETTINGS
    #---------------------------------------------------------------------------
    # Full path to msconvert.exe
    # Typically under: C:\Users\<you>\AppData\Local\Apps\ProteoWizard <version>\msconvert.exe
    MSConvertPath    = "<PATH_TO_MSCONVERT_EXE>"

    # Number of parallel conversion jobs (network drive: 4-6; local disk: up to cores/3)
    MaxParallelJobs  = 6

    # Timeout per file in minutes (0 = no timeout)
    TimeoutMinutes   = 10

    # Skip files that already have a complete mzML
    SkipExisting     = $true

    # msconvert output options
    OutputFormat     = "--mzML"
    Compression      = "--zlib"

    # Write index at end of mzML file (enables faster random access to spectra)
    WriteIndex       = $true

    # Binary encoding precision for m/z and intensity arrays: "32" or "64"
    BinaryEncodingPrecision = "64"

    # Centroiding (peak picking): $true = vendor peak picking, $false = keep as acquired
    EnableCentroiding = $false

    #---------------------------------------------------------------------------
    # MAPFILE SETTINGS (mapfiles are built from the sequence CSVs)
    #---------------------------------------------------------------------------
    # Sample types (sequence "Sample Name") left out of the mapfiles. Their RAW files
    # are still converted. Case-sensitive. e.g. @("MSMS", "PFAS-MSMS", "AMAP", "PFAS_Spike", "Cal_Std")
    ExcludeSampleTypes = @("MSMS", "PFAS-MSMS", "AMAP", "PFAS_Spike", "Cal_Std")

    # RAW files modified less than this many minutes ago are treated as still being
    # acquired and are converted on a later run.
    SkipFilesNewerThanMinutes = 15

    # Mapfile builder (Python standard library only). Pulled from GitHub at run time,
    # from the same repo as the method report script. If the download fails, the copy
    # next to this script is used, then the last downloaded copy in %TEMP%.
    # Set MapfileScriptUrl = "" to always use the local copy.
    MapfileScriptUrl = "https://raw.githubusercontent.com/CLUES-Emory/clues-msconvert-tools/main/lc_sequence_mapfile.py"
    MapfileScript    = (Join-Path $PSScriptRoot "lc_sequence_mapfile.py")

    # Python executable (name on PATH, or full path to python.exe).
    # fisher_py (pip install fisher_py) is needed only for the method reports.
    PythonExe        = "python"

    #---------------------------------------------------------------------------
    # INSTRUMENT METHOD REPORT SETTINGS (OPTIONAL)
    #---------------------------------------------------------------------------
    GenerateMethodReport  = $true
    MethodReportScriptUrl = "https://raw.githubusercontent.com/CLUES-Emory/clues-msconvert-tools/main/instrument_method_report.py"

    # Save the console output to <OutputDirectory>\<StudyID>_conversion_log_<timestamp>.txt
    WriteRunLog      = $true
}

# Command-line values override $config
if ($StudyID)         { $config.StudyID         = $StudyID }
if ($OutputDirectory) { $config.OutputDirectory = $OutputDirectory }
# A path given on the command line always wins, including "" (which skips that mode)
if ($PSBoundParameters.ContainsKey('HILICPath')) { $config.HILICPath = $HILICPath }
if ($PSBoundParameters.ContainsKey('C18Path'))   { $config.C18Path   = $C18Path }
if ($MSConvertPath)   { $config.MSConvertPath   = $MSConvertPath }
if ($PythonExe)       { $config.PythonExe       = $PythonExe }

$ScriptVersion = "2.4"
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false

#===============================================================================
# FUNCTIONS
#===============================================================================

function Get-LCStudyPaths {
    <#
    .SYNOPSIS
        Checks the study folder given for one LC mode (no searching) and returns a
        hashtable (BasePath, RawFilesPath, SequenceFilesPath), or throws.
    #>
    param(
        [Parameter(Mandatory=$true)] [string]$Path,
        [Parameter(Mandatory=$true)] [string]$LCMode
    )
    $base = $Path.Trim().Trim('"').TrimEnd('\', '/')
    if (!(Test-Path -LiteralPath $base -PathType Container)) { throw "${LCMode}Path not found: $base" }
    $leaf  = Split-Path $base -Leaf
    $other = if ($LCMode -eq "HILIC") { "C18" } else { "HILIC" }
    if ($leaf -match "(?i)_${other}$") {
        throw "${LCMode}Path points at a $other folder ($leaf). Check that HILICPath and C18Path are not swapped."
    }
    if ($leaf -notmatch "(?i)_${LCMode}$") {
        Write-Host "WARNING: ${LCMode}Path folder name '$leaf' does not end in _$LCMode; check it is the right study folder." -ForegroundColor Yellow
    }
    $raw = Join-Path $base "1-Raw_Files"
    $seq = Join-Path $base "3-Sequence_Files"
    $missing = @($raw, $seq | Where-Object { !(Test-Path -LiteralPath $_ -PathType Container) })
    if ($missing.Count -gt 0) {
        throw "${LCMode}Path is not a study folder (missing: $(($missing | ForEach-Object { Split-Path $_ -Leaf }) -join ', ')): $base"
    }
    return @{ BasePath = $base; RawFilesPath = $raw; SequenceFilesPath = $seq }
}


function Test-MapfileScript {
    <# $true if the file looks like a complete lc_sequence_mapfile.py (guards against an HTML error page or a partial download). #>
    param([string]$Path)
    if (-not $Path -or !(Test-Path -LiteralPath $Path)) { return $false }
    $text = Get-Content -LiteralPath $Path -Raw -ErrorAction SilentlyContinue
    return ($text -match 'def build\(' -and $text -match 'def main\(' -and $text -match '(?m)^VERSION = ')
}


function Get-MapfileScript {
    <#
    .SYNOPSIS
        Returns the path of lc_sequence_mapfile.py to use: downloaded from GitHub
        (same repo as the method report script), else the copy next to this script,
        else the last downloaded copy in %TEMP%. $null if none is usable.
    #>
    param([string]$Url, [string]$LocalPath)
    $cached = Join-Path $env:TEMP "lc_sequence_mapfile.py"
    $use = $null; $source = ""
    if ($Url) {
        try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
        $tmp = "$cached.download"
        try {
            Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing -ErrorAction Stop
            if (Test-MapfileScript -Path $tmp) {
                Move-Item -LiteralPath $tmp -Destination $cached -Force
                $use = $cached; $source = "GitHub ($Url)"
            } else {
                Write-Host "WARNING: downloaded mapfile script is not valid; not used." -ForegroundColor Yellow
            }
        } catch {
            Write-Host "WARNING: could not download the mapfile script: $($_.Exception.Message)" -ForegroundColor Yellow
        }
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
    if (-not $use -and (Test-MapfileScript -Path $LocalPath)) { $use = $LocalPath; $source = "local copy" }
    if (-not $use -and $Url -and (Test-MapfileScript -Path $cached)) { $use = $cached; $source = "cached copy from an earlier download" }
    if ($use) {
        $ver = (Select-String -LiteralPath $use -Pattern '^VERSION = "(.*)"' | Select-Object -First 1).Matches.Groups[1].Value
        Write-Host "Mapfile script: $source -> $use (v$ver)" -ForegroundColor Green
    }
    return $use
}


function Invoke-SequenceMapfile {
    <#
    .SYNOPSIS
        Runs lc_sequence_mapfile.py for one LC mode: mapfiles, conversion list,
        methods table and QC report from the sequence CSVs. Returns the files to
        convert (from the manifest), or $null on failure.
    #>
    param(
        [Parameter(Mandatory=$true)] [hashtable]$Config,
        [Parameter(Mandatory=$true)] [hashtable]$Paths,
        [Parameter(Mandatory=$true)] [string]$LCMode,
        [Parameter(Mandatory=$true)] [string]$OutputPath
    )
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "$LCMode mapfiles from sequence files" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    # Windows PowerShell drops empty-string arguments to native programs, so an empty
    # list is passed as ","
    $exclTypes = (@($Config.ExcludeSampleTypes) | Where-Object { $_ }) -join ","
    if (-not $exclTypes) { $exclTypes = "," }
    $pyArgs = @($Config.MapfileScript,
                "--raw-dir", $Paths.RawFilesPath, "--seq-dir", $Paths.SequenceFilesPath,
                "--out-dir", $OutputPath, "--study-id", $Config.StudyID, "--lc-mode", $LCMode,
                "--exclude-types", $exclTypes,
                "--min-age-minutes", "$($Config.SkipFilesNewerThanMinutes)")
    & $Config.PythonExe @pyArgs 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: mapfile step failed for $LCMode (exit $LASTEXITCODE)." -ForegroundColor Red
        return $null
    }
    $pre = Join-Path $OutputPath "$($Config.StudyID)_${LCMode}"
    $manifest = @(Import-Csv -LiteralPath "${pre}_conversion_manifest.tsv" -Delimiter "`t")
    Write-Host "  QC report: ${pre}_mapfile_QC.txt" -ForegroundColor Green
    return @{
        RawFiles        = @($manifest | Where-Object { $_.Kind -eq "MS1" }  | ForEach-Object { $_.RawPath })
        MSMSFiles       = @($manifest | Where-Object { $_.Kind -eq "MSMS" } | ForEach-Object { $_.RawPath })
        PositiveMapfile = "${pre}pos_sample_mapfile.txt"
        NegativeMapfile = "${pre}neg_sample_mapfile.txt"
        MethodsTable    = "${pre}_methods.tsv"
    }
}


function Test-MzMLComplete {
    <# $true if the mzML ends with its closing tag (a killed msconvert leaves it open). #>
    param([Parameter(Mandatory=$true)][string]$Path)
    try {
        $fs = [System.IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
        try {
            $n = [Math]::Min(4096, $fs.Length)
            if ($n -le 0) { return $false }
            $null = $fs.Seek(-$n, 'End')
            $buf = New-Object byte[] $n
            $null = $fs.Read($buf, 0, $n)
            $tail = [System.Text.Encoding]::ASCII.GetString($buf)
            return ($tail -match '</indexedmzML>\s*$' -or $tail -match '</mzML>\s*$')
        } finally { $fs.Close() }
    } catch { return $false }
}


function Get-PendingConversions {
    <#
    .SYNOPSIS
        Returns the RAW files that do not yet have a complete mzML. Incomplete
        mzML files (e.g. from a timed-out msconvert) are deleted and reconverted.
    #>
    param(
        [Parameter(Mandatory=$true)] [AllowEmptyCollection()] [string[]]$RawFiles,
        [Parameter(Mandatory=$true)] [string]$MzMLDirectory,
        [Parameter(Mandatory=$true)] [string]$FileType
    )
    Write-Host ""
    Write-Host "Checking for existing $FileType conversions..." -ForegroundColor Cyan
    if (!(Test-Path -LiteralPath $MzMLDirectory)) {
        New-Item -ItemType Directory -Path $MzMLDirectory -Force | Out-Null
        return $RawFiles
    }
    $existing = @{}
    foreach ($mz in (Get-ChildItem -LiteralPath $MzMLDirectory -Filter "*.mzML" -File -ErrorAction SilentlyContinue)) {
        $existing[$mz.BaseName.ToLower()] = $mz.FullName
    }
    $pending = @(); $skipped = 0; $incomplete = 0
    foreach ($rawFile in $RawFiles) {
        $key = [System.IO.Path]::GetFileNameWithoutExtension($rawFile).ToLower()
        if ($existing.ContainsKey($key)) {
            if (Test-MzMLComplete -Path $existing[$key]) { $skipped++; continue }
            Remove-Item -LiteralPath $existing[$key] -Force -ErrorAction SilentlyContinue
            $incomplete++
        }
        $pending += $rawFile
    }
    Write-Host "Already converted (skipping): $skipped" -ForegroundColor Green
    if ($incomplete -gt 0) { Write-Host "Incomplete mzML removed for reconversion: $incomplete" -ForegroundColor Yellow }
    Write-Host "Pending conversion: $($pending.Count)" -ForegroundColor Yellow
    return $pending
}


function Compare-MapfileToConverted {
    <#
    .SYNOPSIS
        Compares mapfile entries against converted mzML files to find missing files.
    .DESCRIPTION
        Reads the mapfile, extracts File.Name column, compares against mzML files
        in the output directory, and reports files present in mapfile but missing
        from converted files.
    #>
    param(
        [Parameter(Mandatory=$true)]
        [string]$MapfilePath,
        
        [Parameter(Mandatory=$true)]
        [string]$MzMLDirectory,
        
        [Parameter(Mandatory=$true)]
        [string]$OutputPath,
        
        [Parameter(Mandatory=$true)]
        [string]$StudyID,
        
        [Parameter(Mandatory=$true)]
        [string]$ModeName
    )
    
    Write-Host ""
    Write-Host "Comparing $ModeName mapfile to converted files..." -ForegroundColor Cyan
    
    if (!(Test-Path $MapfilePath)) {
        Write-Host "  Mapfile not found: $MapfilePath" -ForegroundColor Yellow
        return $null
    }
    
    if (!(Test-Path $MzMLDirectory)) {
        Write-Host "  mzML directory not found: $MzMLDirectory" -ForegroundColor Yellow
        return $null
    }
    
    # Read mapfile (tab-separated, skip header)
    $mapfileContent = Get-Content $MapfilePath | Select-Object -Skip 1
    $mapfileNames = @()
    
    foreach ($line in $mapfileContent) {
        $fields = $line -split "`t"
        if ($fields.Count -gt 0 -and $fields[0]) {
            # Extract base name without extension
            $baseName = [System.IO.Path]::GetFileNameWithoutExtension($fields[0])
            $mapfileNames += $baseName
        }
    }
    
    Write-Host "  Files in mapfile: $($mapfileNames.Count)"
    
    # Get converted mzML files
    $convertedFiles = Get-ChildItem -Path $MzMLDirectory -Filter "*.mzML" -File -ErrorAction SilentlyContinue
    $convertedNames = New-Object System.Collections.Generic.HashSet[string]
    
    foreach ($mzml in $convertedFiles) {
        [void]$convertedNames.Add($mzml.BaseName.ToLower())
    }
    
    Write-Host "  Converted mzML files: $($convertedNames.Count)"
    
    # Find missing files
    $missingFiles = @()
    
    foreach ($name in $mapfileNames) {
        if (-not $convertedNames.Contains($name.ToLower())) {
            $missingFiles += $name
        }
    }
    
    # Write missing files report
    $missingReportPath = Join-Path $OutputPath "${StudyID}_${ModeName}_missing_files.txt"
    
    if ($missingFiles.Count -gt 0) {
        Write-Host "  MISSING FILES: $($missingFiles.Count)" -ForegroundColor Red
        
        $reportLines = @("# Missing files for $ModeName")
        $reportLines += "# Files present in mapfile but not found in converted mzML"
        $reportLines += "# Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        $reportLines += ""
        $reportLines += $missingFiles
        
        $reportLines | Out-File -FilePath $missingReportPath -Encoding UTF8
        Write-Host "  Missing files report: $missingReportPath" -ForegroundColor Yellow
    } else {
        Write-Host "  All mapfile entries have been converted" -ForegroundColor Green
        
        # Write empty/success report
        $reportLines = @("# No missing files for $ModeName")
        $reportLines += "# All $($mapfileNames.Count) files in mapfile have been converted"
        $reportLines += "# Verified: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        
        $reportLines | Out-File -FilePath $missingReportPath -Encoding UTF8
    }
    
    return @{
        MapfileCount = $mapfileNames.Count
        ConvertedCount = $convertedNames.Count
        MissingCount = $missingFiles.Count
        MissingFiles = $missingFiles
        ReportPath = $missingReportPath
    }
}


function New-LCMethodReports {
    <#
    .SYNOPSIS
        One instrument method report per distinct method (MS1 and MSMS), using the
        methods table built from the sequence (one representative RAW per method;
        these are the only RAW files read outside msconvert).
        Report script pulled from GitHub. Non-fatal.
    #>
    param(
        [Parameter(Mandatory=$true)]  [string]$MethodsTable,
        [Parameter(Mandatory=$true)]  [string]$OutputPath,
        [Parameter(Mandatory=$true)]  [string]$StudyID,
        [Parameter(Mandatory=$true)]  [string]$LCMode,
        [Parameter(Mandatory=$true)]  [string]$ScriptUrl,
        [Parameter(Mandatory=$false)] [string]$PythonExe = "python"
    )
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "Generating $LCMode Instrument Method Reports" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    try {
        if (!(Test-Path -LiteralPath $MethodsTable)) {
            Write-Host "WARNING: methods table not found; skipping method reports." -ForegroundColor Yellow
            return $null
        }
        $methods = @(Import-Csv -LiteralPath $MethodsTable -Delimiter "`t")
        if ($methods.Count -eq 0) { Write-Host "WARNING: no methods found." -ForegroundColor Yellow; return $null }
        Write-Host "Distinct methods in the sequence files: $($methods.Count)"

        # The report script needs fisher_py; check once instead of failing per method
        $null = & $PythonExe -c "import fisher_py" 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "WARNING: fisher_py is not installed for '$PythonExe'; skipping method reports (conversion continues)." -ForegroundColor Yellow
            Write-Host "         Install it with: $PythonExe -m pip install fisher_py" -ForegroundColor DarkGray
            return $null
        }

        $reportDir = Join-Path $OutputPath "2-Method_Report"
        if (!(Test-Path -LiteralPath $reportDir)) { New-Item -ItemType Directory -Path $reportDir -Force | Out-Null }

        try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
        $scriptPath = Join-Path $env:TEMP "instrument_method_report.py"
        try {
            Write-Host "Pulling report script from: $ScriptUrl"
            Invoke-WebRequest -Uri $ScriptUrl -OutFile $scriptPath -UseBasicParsing -ErrorAction Stop
        } catch {
            if (!(Test-Path $scriptPath) -or ((Get-Item $scriptPath).Length -lt 1000)) {
                Write-Host "WARNING: Could not download method report script: $($_.Exception.Message)" -ForegroundColor Yellow
                return $null
            }
            Write-Host "  download failed; using cached copy $scriptPath" -ForegroundColor DarkGray
        }

        $summary = @("Method`tCategory`tPolarity`tInjections`tSampleTypes`tRepresentativeFile`tReport")
        $made = 0
        foreach ($m in $methods) {
            if (-not $m.Representative) {
                Write-Host "  [SKIP] $($m.Method) (no RAW file yet)" -ForegroundColor DarkGray
                continue
            }
            $pyOut  = & $PythonExe $scriptPath $m.Representative $reportDir 2>&1
            $pyExit = $LASTEXITCODE
            $repBase   = [System.IO.Path]::GetFileNameWithoutExtension($m.Representative)
            $generated = Join-Path $reportDir "${repBase}_method_report.txt"
            if ($pyExit -eq 0 -and (Test-Path -LiteralPath $generated)) {
                $reportName = "${StudyID}_$($m.Method)_method_report.txt"
                Move-Item -LiteralPath $generated -Destination (Join-Path $reportDir $reportName) -Force
                # Same content as JSON (report script 2026-11-08 and later); read by the summary below
                $generatedJson = Join-Path $reportDir "${repBase}_method_report.json"
                if (Test-Path -LiteralPath $generatedJson) {
                    Move-Item -LiteralPath $generatedJson -Destination (Join-Path $reportDir "${StudyID}_$($m.Method)_method_report.json") -Force
                }
                $made++
                $summary += "$($m.Method)`t$($m.Category)`t$($m.Polarity)`t$($m.Injections)`t$($m.SampleTypes)`t$repBase`t$reportName"
                Write-Host "  [OK] $($m.Method)" -ForegroundColor Green
            } else {
                Write-Host "  [FAIL] $($m.Method) (exit $pyExit)" -ForegroundColor Yellow
                if ($pyOut) { Write-Host "         $($pyOut -join ' ')" -ForegroundColor DarkGray }
            }
        }
        if ($made -gt 0) {
            $summaryPath = Join-Path $reportDir "${StudyID}_${LCMode}_method_summary.txt"
            [System.IO.File]::WriteAllLines($summaryPath, [string[]]$summary, $Utf8NoBom)
            Write-Host "Generated $made method report(s) in: $reportDir" -ForegroundColor Green
            # All methods in one JSON (methods table + each report's JSON + dual-column pairing)
            $sumOut  = & $PythonExe $scriptPath --summary $MethodsTable $reportDir $StudyID $LCMode 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  $($sumOut -join ' ')" -ForegroundColor Green
            } else {
                Write-Host "WARNING: method summary JSON not written (exit $LASTEXITCODE): $($sumOut -join ' ')" -ForegroundColor Yellow
            }
        }
        return $reportDir
    } catch {
        Write-Host "WARNING: Method report step error: $($_.Exception.Message)" -ForegroundColor Yellow
        return $null
    }
}


function Convert-RawFilesParallel {
    <#
    .SYNOPSIS
        Converts RAW files to mzML in parallel using msconvert.
    .DESCRIPTION
        Launches multiple msconvert processes simultaneously for improved throughput.
        Includes comprehensive error handling, timeout protection, and logging.
    #>
    param(
        [Parameter(Mandatory=$true)]
        [string[]]$RawFiles,
        
        [Parameter(Mandatory=$true)]
        [string]$OutputDirectory,
        
        [Parameter(Mandatory=$true)]
        [string]$MSConvertPath,
        
        [Parameter(Mandatory=$false)]
        [int]$MaxJobs = 6,
        
        [Parameter(Mandatory=$true)]
        [string]$StudyID,
        
        [Parameter(Mandatory=$true)]
        [string]$FileType,
        
        [Parameter(Mandatory=$false)]
        [string]$OutputFormat = "--mzML",
        
        [Parameter(Mandatory=$false)]
        [string]$Compression = "--zlib",
        
        [Parameter(Mandatory=$false)]
        [bool]$WriteIndex = $true,
        
        [Parameter(Mandatory=$false)]
        [ValidateSet("32", "64")]
        [string]$BinaryEncodingPrecision = "64",
        
        [Parameter(Mandatory=$false)]
        [bool]$EnableCentroiding = $false,
        
        [Parameter(Mandatory=$false)]
        [int]$TimeoutMinutes = 10,
        
        [Parameter(Mandatory=$true)]
        [string]$LogDirectory
    )
    
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "Converting $FileType Files" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "Output: $OutputDirectory"
    Write-Host "Parallel jobs: $MaxJobs"
    Write-Host "Files to convert: $($RawFiles.Count)"
    
    if ($RawFiles.Count -eq 0) {
        Write-Host "No files to convert." -ForegroundColor Yellow
        return @{ Successful = @(); Failed = @() }
    }
    
    # Create output directory
    if (!(Test-Path $OutputDirectory)) {
        New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    }
    
    # Initialize tracking
    $successful = [System.Collections.ArrayList]::new()
    $failed = [System.Collections.ArrayList]::new()
    $activeJobs = @{}
    $fileQueue = [System.Collections.Queue]::new()
    
    foreach ($file in $RawFiles) {
        $fileQueue.Enqueue($file)
    }
    
    $totalFiles = $RawFiles.Count
    $processedCount = 0
    $startTime = Get-Date
    
    # Main processing loop
    while ($fileQueue.Count -gt 0 -or $activeJobs.Count -gt 0) {
        
        # Check completed jobs
        $completedJobIds = @()
        
        foreach ($jobId in $activeJobs.Keys) {
            $job = Get-Job -Id $jobId -ErrorAction SilentlyContinue
            
            if ($null -eq $job) {
                $completedJobIds += $jobId
                continue
            }
            
            $jobInfo = $activeJobs[$jobId]
            $elapsed = (Get-Date) - $jobInfo.StartTime
            
            if ($job.State -in @('Completed', 'Failed', 'Stopped')) {
                $rawFile = $jobInfo.RawFile
                $fileName = [System.IO.Path]::GetFileName($rawFile)
                
                # Check for output file
                $expectedOutput = Join-Path $OutputDirectory ([System.IO.Path]::GetFileNameWithoutExtension($rawFile) + ".mzML")
                
                if ($job.State -eq 'Completed' -and (Test-Path -LiteralPath $expectedOutput) -and (Test-MzMLComplete -Path $expectedOutput)) {
                    [void]$successful.Add(@{
                        File = $rawFile
                        Time = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
                        Duration = $elapsed.TotalSeconds
                    })
                    $duration = [math]::Round($elapsed.TotalSeconds, 1)
                    Write-Host "  [OK] $fileName (${duration}s)" -ForegroundColor Green
                } else {
                    $errorMsg = "Conversion failed or output not found"
                    try {
                        # v2.4: the job's thrown error (msconvert message / timeout) is in the error stream
                        $jerr = $null
                        $jobOutput = Receive-Job -Job $job -ErrorAction SilentlyContinue -ErrorVariable jerr
                        if ($jerr) { $errorMsg = (($jerr | ForEach-Object { $_.ToString() }) -join ' ').Trim() }
                        elseif ($jobOutput -and ("$jobOutput" -ne "Success")) { $errorMsg = $jobOutput | Out-String }
                        elseif ($job.State -eq 'Completed') { $errorMsg = "msconvert finished but the mzML is missing or incomplete" }
                    } catch {}
                    
                    # v2.4: never leave a partial mzML behind (it would be skipped on the next run)
                    Remove-Item -LiteralPath $expectedOutput -Force -ErrorAction SilentlyContinue
                    [void]$failed.Add(@{
                        File = $rawFile
                        Time = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
                        Error = $errorMsg.Substring(0, [Math]::Min(500, $errorMsg.Length))
                    })
                    Write-Host "  [FAIL] $fileName - $errorMsg" -ForegroundColor Red
                }
                
                Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
                $completedJobIds += $jobId
                $processedCount++
            }
            elseif ($TimeoutMinutes -gt 0 -and $elapsed.TotalMinutes -gt ($TimeoutMinutes + 2)) {
                # Backstop only: the job itself kills msconvert at TimeoutMinutes (v2.4)
                $rawFile = $jobInfo.RawFile
                $fileName = [System.IO.Path]::GetFileName($rawFile)
                
                Stop-Job -Job $job -ErrorAction SilentlyContinue
                Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
                $partial = Join-Path $OutputDirectory ([System.IO.Path]::GetFileNameWithoutExtension($rawFile) + ".mzML")
                Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
                
                [void]$failed.Add(@{
                    File = $rawFile
                    Time = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
                    Error = "Timeout after $TimeoutMinutes minutes"
                })
                Write-Host "  [TIMEOUT] $fileName" -ForegroundColor Yellow
                
                $completedJobIds += $jobId
                $processedCount++
            }
        }
        
        # Remove completed jobs from tracking
        foreach ($jobId in $completedJobIds) {
            $activeJobs.Remove($jobId)
        }
        
        # Start new jobs if capacity available
        while ($activeJobs.Count -lt $MaxJobs -and $fileQueue.Count -gt 0) {
            $rawFile = $fileQueue.Dequeue()
            $fileName = [System.IO.Path]::GetFileName($rawFile)
            
            $job = Start-Job -ScriptBlock {
                param($exePath, $inputFile, $outputDir, $formatArg, $compressionArg, $doCentroid, $doWriteIndex, $bitPrecision, $timeoutMin)
                
                # Build argument string with all options
                $argString = "`"$inputFile`" -o `"$outputDir`" $formatArg $compressionArg"
                
                # Add --noindex if WriteIndex is disabled (index is written by default)
                if (-not $doWriteIndex) {
                    $argString += " --noindex"
                }
                
                # Add binary encoding precision (--32 or --64)
                $argString += " --$bitPrecision"
                
                # Add centroiding filter if enabled
                if ($doCentroid) {
                    $argString += " --filter `"peakPicking vendor msLevel=1-`""
                }
                
                $processInfo = New-Object System.Diagnostics.ProcessStartInfo
                $processInfo.FileName = $exePath
                $processInfo.Arguments = $argString
                $processInfo.RedirectStandardOutput = $true
                $processInfo.RedirectStandardError = $true
                $processInfo.UseShellExecute = $false
                $processInfo.CreateNoWindow = $true
                
                $process = New-Object System.Diagnostics.Process
                $process.StartInfo = $processInfo
                $process.Start() | Out-Null
                # v2.4: read both streams asynchronously (a full pipe buffer can hang
                # msconvert) and kill msconvert itself on timeout
                $stdoutTask = $process.StandardOutput.ReadToEndAsync()
                $stderrTask = $process.StandardError.ReadToEndAsync()
                $waitMs = if ($timeoutMin -gt 0) { [int]($timeoutMin * 60000) } else { -1 }
                if (-not $process.WaitForExit($waitMs)) {
                    try { $process.Kill() } catch {}
                    $process.WaitForExit(30000) | Out-Null
                    $partial = Join-Path $outputDir ([System.IO.Path]::GetFileNameWithoutExtension($inputFile) + ".mzML")
                    Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
                    throw "Timeout after $timeoutMin minutes (msconvert stopped)"
                }
                $process.WaitForExit()
                
                if ($process.ExitCode -ne 0) {
                    # msconvert writes most errors to stdout (e.g. "[RawFileImpl::ctor()] Corrupt RAW file ...");
                    # keep the error lines, without the file path
                    $lines = ("$($stderrTask.Result)`n$($stdoutTask.Result)" -split "`r?`n") |
                             Where-Object { $_ -match '(?i)error|corrupt|exception|fail|^\s*\[' }
                    $msg = (($lines | Select-Object -First 3) -join ' | ').Replace($inputFile, '<file>')
                    if (-not $msg) { $msg = "$($stdoutTask.Result)".Trim() }
                    if ($msg.Length -gt 400) { $msg = $msg.Substring(0, 400) + "..." }
                    throw "msconvert failed (exit $($process.ExitCode)): $msg"
                }
                
                return "Success"
                
            } -ArgumentList $MSConvertPath, $rawFile, $OutputDirectory, $OutputFormat, $Compression, $EnableCentroiding, $WriteIndex, $BinaryEncodingPrecision, $TimeoutMinutes
            
            $activeJobs[$job.Id] = @{
                RawFile = $rawFile
                StartTime = Get-Date
            }
            
            Write-Host "  [START] $fileName (Job $($job.Id))"
        }
        
        # Progress update
        if ($processedCount -gt 0) {
            $elapsed = (Get-Date) - $startTime
            $avgTime = $elapsed.TotalSeconds / $processedCount
            $remaining = ($totalFiles - $processedCount) * $avgTime / $MaxJobs
            $pct = [math]::Round(($processedCount / $totalFiles) * 100, 1)
            
            Write-Progress -Activity "Converting $FileType" `
                          -Status "$processedCount of $totalFiles ($pct%) - ~$([math]::Round($remaining/60, 1)) min remaining" `
                          -PercentComplete $pct
        }
        
        Start-Sleep -Milliseconds 500
    }
    
    Write-Progress -Activity "Converting $FileType" -Completed
    
    # Write logs
    $successLogPath = Join-Path $LogDirectory "${StudyID}_${FileType}_conversion_success.txt"
    $failureLogPath = Join-Path $LogDirectory "${StudyID}_${FileType}_conversion_failures.txt"
    
    if ($successful.Count -gt 0) {
        $successLines = @("File`tTimestamp`tDuration_sec")
        foreach ($item in $successful) {
            $successLines += "$($item.File)`t$($item.Time)`t$($item.Duration)"
        }
        $successLines | Out-File -FilePath $successLogPath -Encoding UTF8
    }
    
    if ($failed.Count -gt 0) {
        $failLines = @("File`tTimestamp`tError")
        foreach ($item in $failed) {
            $failLines += "$($item.File)`t$($item.Time)`t$($item.Error)"
        }
        $failLines | Out-File -FilePath $failureLogPath -Encoding UTF8
    }
    
    # Summary
    $totalTime = (Get-Date) - $startTime
    Write-Host ""
    Write-Host "$FileType Conversion Summary:" -ForegroundColor Cyan
    Write-Host "  Successful: $($successful.Count)" -ForegroundColor Green
    if ($failed.Count -gt 0) {
        Write-Host "  Failed: $($failed.Count)" -ForegroundColor Red
    } else {
        Write-Host "  Failed: $($failed.Count)" -ForegroundColor Green
    }
    Write-Host "  Total time: $([math]::Round($totalTime.TotalMinutes, 1)) minutes"
    
    return @{
        Successful = $successful
        Failed = $failed
    }
}


#===============================================================================
# MAIN EXECUTION
#===============================================================================

Write-Host ""
Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host "       LC-HRMS Parallel msconvert - Standard Study Layout               " -ForegroundColor Cyan
Write-Host "                           Version $ScriptVersion                                  " -ForegroundColor Cyan
Write-Host "                   CLUES Lab, Emory University                         " -ForegroundColor Cyan
Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Validating configuration..." -ForegroundColor Yellow
$placeholders = @(@("StudyID", "OutputDirectory") | Where-Object { "$($config[$_])" -match '<[A-Z_]+>' -or -not "$($config[$_])".Trim() })
if (-not $MapfileOnly -and "$($config.MSConvertPath)" -match '<[A-Z_]+>') { $placeholders += "MSConvertPath" }
if ($placeholders) {
    Write-Host "ERROR: Set these values in `$config (or on the command line): $($placeholders -join ', ')" -ForegroundColor Red
    exit 1
}
# LC modes = the modes with a study folder path; a blank path skips that mode
$modePaths = [ordered]@{ HILIC = "$($config.HILICPath)".Trim(); C18 = "$($config.C18Path)".Trim() }
$config.LCModes = @($modePaths.Keys | Where-Object { $modePaths[$_] })
if ($config.LCModes.Count -eq 0) {
    Write-Host "ERROR: Set HILICPath and/or C18Path (the study folder holding 1-Raw_Files and 3-Sequence_Files)." -ForegroundColor Red
    exit 1
}
if ($config.LCModes.Count -eq 2 -and $modePaths.HILIC.TrimEnd('\', '/') -eq $modePaths.C18.TrimEnd('\', '/')) {
    Write-Host "ERROR: HILICPath and C18Path are the same folder." -ForegroundColor Red
    exit 1
}
if (-not $MapfileOnly -and !(Test-Path -LiteralPath $config.MSConvertPath)) {
    Write-Host "ERROR: msconvert.exe not found at: $($config.MSConvertPath)" -ForegroundColor Red
    exit 1
}
if (!(Test-Path -LiteralPath $config.OutputDirectory)) {
    New-Item -ItemType Directory -Path $config.OutputDirectory -Force | Out-Null
}
$transcribing = $false
if ($config.WriteRunLog) {
    $logPath = Join-Path $config.OutputDirectory ("$($config.StudyID)_conversion_log_{0}.txt" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
    try { Start-Transcript -LiteralPath $logPath | Out-Null; $transcribing = $true } catch {}
}

# Check every study folder before doing any work
$lcPaths = @{}
foreach ($lcMode in $config.LCModes) {
    try { $lcPaths[$lcMode] = Get-LCStudyPaths -Path $modePaths[$lcMode] -LCMode $lcMode }
    catch {
        Write-Host "ERROR ($lcMode): $($_.Exception.Message)" -ForegroundColor Red
        if ($transcribing) { Stop-Transcript | Out-Null }
        exit 1
    }
}
$resolvedMapfileScript = Get-MapfileScript -Url $config.MapfileScriptUrl -LocalPath $config.MapfileScript
if (-not $resolvedMapfileScript) {
    Write-Host "ERROR: lc_sequence_mapfile.py is not available (download failed and no local copy at $($config.MapfileScript))." -ForegroundColor Red
    if ($transcribing) { Stop-Transcript | Out-Null }
    exit 1
}
$config.MapfileScript = $resolvedMapfileScript
if (-not (Get-Command $config.PythonExe -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Python ('$($config.PythonExe)') not found; it is needed to build the mapfiles." -ForegroundColor Red
    if ($transcribing) { Stop-Transcript | Out-Null }
    exit 1
}

Write-Host ""
Write-Host "Configuration:" -ForegroundColor Green
Write-Host "  Study: $($config.StudyID)"
Write-Host "  LC Modes: $($config.LCModes -join ', ')$(if ($config.LCModes.Count -lt 2) { '   (other mode left blank: skipped)' })"
foreach ($lcMode in $config.LCModes) {
    Write-Host "    $lcMode -> $($lcPaths[$lcMode].BasePath)"
}
Write-Host "  Output: $($config.OutputDirectory)"
Write-Host "  Mapfiles: from sequence files (lc_sequence_mapfile.py)   Excluded sample types: $($config.ExcludeSampleTypes -join ', ')"
if ($MapfileOnly) {
    Write-Host "  Mode: mapfiles only (no conversion)" -ForegroundColor Yellow
} else {
    Write-Host "  msconvert: $($config.MSConvertPath)"
    Write-Host "  Parallel Jobs: $($config.MaxParallelJobs)   Timeout: $($config.TimeoutMinutes) min"
    Write-Host "  Centroiding: $(if ($config.EnableCentroiding) { 'Enabled (vendor peak picking)' } else { 'Disabled (as acquired)' })"
    Write-Host "  Write Index: $(if ($config.WriteIndex) { 'Enabled' } else { 'Disabled' })   Binary Encoding: $($config.BinaryEncodingPrecision)-bit"
}

$allResults = [ordered]@{}
foreach ($lcMode in $config.LCModes) {
    Write-Host ""
    Write-Host "================================================================================" -ForegroundColor Magenta
    Write-Host "Processing $lcMode Mode" -ForegroundColor Magenta
    Write-Host "================================================================================" -ForegroundColor Magenta

    $paths = $lcPaths[$lcMode]
    $lcOutputDir = Join-Path $config.OutputDirectory $lcMode
    $mzmlDir = Join-Path $lcOutputDir "1a-${lcMode}_mzML"
    # MSMS mzML go in a subfolder of the MS1 folder (e.g. 1a-HILIC_mzML\HILIC_MSMS). MS1
    # listings here and in 6-Data_Extraction are not recursive, so the two never mix.
    $msmsDir = Join-Path $mzmlDir "${lcMode}_MSMS"
    if (!(Test-Path -LiteralPath $lcOutputDir)) { New-Item -ItemType Directory -Path $lcOutputDir -Force | Out-Null }

    #---------------------------------------------------------------------------
    # STEP 1: Mapfiles and conversion list from the sequence files
    #---------------------------------------------------------------------------
    $mapfileResult = Invoke-SequenceMapfile -Config $config -Paths $paths -LCMode $lcMode -OutputPath $lcOutputDir
    if ($null -eq $mapfileResult) {
        $allResults[$lcMode] = @{ Error = "mapfile step failed" }
        continue
    }
    $fileResult = @{ RawFiles = $mapfileResult.RawFiles; MSMSFiles = $mapfileResult.MSMSFiles }

    #---------------------------------------------------------------------------
    # STEP 1b: Instrument method reports (non-fatal)
    #---------------------------------------------------------------------------
    if ($config.GenerateMethodReport -and $mapfileResult -and $mapfileResult.MethodsTable) {
        $null = New-LCMethodReports -MethodsTable $mapfileResult.MethodsTable -OutputPath $lcOutputDir `
            -StudyID $config.StudyID -LCMode $lcMode -ScriptUrl $config.MethodReportScriptUrl -PythonExe $config.PythonExe
    }

    $rawResult = @{ Successful = @(); Failed = @() }
    $msmsResult = @{ Successful = @(); Failed = @() }
    if (-not $MapfileOnly) {
        #-----------------------------------------------------------------------
        # STEP 2: Pending conversions (skips complete mzML; redoes incomplete ones)
        #-----------------------------------------------------------------------
        $pendingRawFiles = @($fileResult.RawFiles)
        $pendingMSMSFiles = @($fileResult.MSMSFiles)
        if ($config.SkipExisting) {
            if ($pendingRawFiles.Count -gt 0) {
                $pendingRawFiles = @(Get-PendingConversions -RawFiles $pendingRawFiles -MzMLDirectory $mzmlDir -FileType "${lcMode}_RAW")
            }
            if ($pendingMSMSFiles.Count -gt 0) {
                $pendingMSMSFiles = @(Get-PendingConversions -RawFiles $pendingMSMSFiles -MzMLDirectory $msmsDir -FileType "${lcMode}_MSMS")
            }
        }

        #-----------------------------------------------------------------------
        # STEP 3: Convert MS1 and MSMS files
        #-----------------------------------------------------------------------
        Write-Host ""
        Write-Host "$lcMode files to convert: RAW $($pendingRawFiles.Count), MSMS $($pendingMSMSFiles.Count)" -ForegroundColor Yellow
        $convArgs = @{
            MSConvertPath = $config.MSConvertPath; MaxJobs = $config.MaxParallelJobs; StudyID = $config.StudyID
            OutputFormat = $config.OutputFormat; Compression = $config.Compression; WriteIndex = $config.WriteIndex
            BinaryEncodingPrecision = $config.BinaryEncodingPrecision; EnableCentroiding = $config.EnableCentroiding
            TimeoutMinutes = $config.TimeoutMinutes; LogDirectory = $lcOutputDir
        }
        if ($pendingRawFiles.Count -gt 0) {
            $rawResult = Convert-RawFilesParallel -RawFiles $pendingRawFiles -OutputDirectory $mzmlDir -FileType "${lcMode}_RAW" @convArgs
        }
        if ($pendingMSMSFiles.Count -gt 0) {
            $msmsResult = Convert-RawFilesParallel -RawFiles $pendingMSMSFiles -OutputDirectory $msmsDir -FileType "${lcMode}_MSMS" @convArgs
        }

        #-----------------------------------------------------------------------
        # STEP 4: Every mapfile entry has an mzML?
        #-----------------------------------------------------------------------
        if ($mapfileResult) {
            foreach ($pm in @(@("pos", $mapfileResult.PositiveMapfile), @("neg", $mapfileResult.NegativeMapfile))) {
                if ($pm[1] -and (Test-Path -LiteralPath $pm[1])) {
                    $null = Compare-MapfileToConverted -MapfilePath $pm[1] -MzMLDirectory $mzmlDir `
                        -OutputPath $lcOutputDir -StudyID $config.StudyID -ModeName "${lcMode}$($pm[0])"
                }
            }
        }
    }
    $allResults[$lcMode] = @{ RawResult = $rawResult; MSMSResult = $msmsResult; MapfileResult = $mapfileResult }
}

#===============================================================================
# FINAL SUMMARY
#===============================================================================
Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "FINAL SUMMARY" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
$exitCode = 0
foreach ($lcMode in $allResults.Keys) {
    $r = $allResults[$lcMode]
    Write-Host ""
    Write-Host "$lcMode Mode:" -ForegroundColor Yellow
    if ($r.Error) { Write-Host "  ERROR: $($r.Error)" -ForegroundColor Red; $exitCode = 1; continue }
    Write-Host "  RAW - Success: $($r.RawResult.Successful.Count), Failed: $($r.RawResult.Failed.Count)"
    Write-Host "  MSMS - Success: $($r.MSMSResult.Successful.Count), Failed: $($r.MSMSResult.Failed.Count)"
    if ($r.RawResult.Failed.Count + $r.MSMSResult.Failed.Count -gt 0) { $exitCode = 1 }
    $qc = Join-Path (Join-Path $config.OutputDirectory $lcMode) "$($config.StudyID)_${lcMode}_mapfile_QC.txt"
    if (Test-Path -LiteralPath $qc) {
        $w = Get-Content -LiteralPath $qc | Select-String -Pattern '^WARNINGS:|^  - ' | ForEach-Object { $_.Line }
        $w | Select-Object -First 12 | ForEach-Object { Write-Host "  $_" }
        Write-Host "  QC report: $qc"
    }
}
Write-Host ""
Write-Host "Output directory: $($config.OutputDirectory)" -ForegroundColor Green
Write-Host ""
Write-Host "Done." -ForegroundColor Green
if ($transcribing) { Stop-Transcript | Out-Null }
exit $exitCode
