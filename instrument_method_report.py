# instrument_method_report.py
# Extracts instrument method details from Thermo .raw files using fisher_py
# and outputs a formatted, easy-to-read text report with clearly separated
# sections for all method components.
#
# Supports BOTH front-end configurations, auto-detected from the method text:
#   * LC-MS  (e.g. Orbitrap Exploris 120): LC / Autosampler / TCC + ESI MS
#   * GC-HRMS (Orbitrap Exploris GC):      GC oven/inlet / TriPlus RSH + EI MS
#
# Usage (command line): python instrument_method_report.py <raw_file> <output_dir>
# Usage (interactive):  Set raw_file and output_dir below, then run.
#
# Requires: pip install fisher_py

import sys
import os
import re
from datetime import datetime
from fisher_py import RawFile

# ── USER SETTINGS (for interactive use) ───────────────────────────────────────
# Set these if running interactively. Command line args override these.

raw_file   = r"C:\path\to\your_file.raw"
output_dir = r"C:\path\to\output"

# ── END USER SETTINGS ─────────────────────────────────────────────────────────

# Command line args override interactive settings
if len(sys.argv) >= 3:
    raw_file   = sys.argv[1]
    output_dir = sys.argv[2]
elif len(sys.argv) == 2:
    raw_file   = sys.argv[1]

WIDTH = 72

def divider(char="="):
    return char * WIDTH

def section_header(title, char="-"):
    return f"\n{divider(char)}\n  {title.upper()}\n{divider(char)}\n"

def top_header(title):
    return f"{divider('=')}\n   {title.upper()}\n{divider('=')}"

def clean_text(text):
    """Fix mangled unit symbols that fisher_py returns as the replacement char.

    In the raw method text the degree and micro signs come back as U+FFFD
    ('\ufffd', shown as '?'). Restore them based on the trailing unit letter."""
    if text is None:
        return ""
    return (text.replace("\ufffd" + "C", "\u00b0C")   # ?C  -> °C
                .replace("\ufffd" + "L", "\u00b5L"))   # ?L  -> µL  (also µL/sec)

# ── Instrument-type detection ─────────────────────────────────────────────────

def detect_instrument_type(all_method_text):
    """Return 'GC' or 'LC' based on markers in the combined method text."""
    if ("TriPlus RSH Method" in all_method_text
            or "Orbitrap Exploris GC" in all_method_text
            or re.search(r"(?m)^\s*GC\.", all_method_text)):
        return "GC"
    return "LC"

# ── MS Section Parsing (generic, used for the MS method) ──────────────────────
# Method 0 = LC/GC front end; Method 1 = MS method

SECTION_PATTERNS = [
    # LC Method sections
    (r"^COMMENT:", "Comment"),
    (r"^LC METHOD", "LC Method"),
    (r"^AUTOSAMPLER METHOD", "Autosampler Method"),
    (r"^TCC:", "Column Compartment (TCC)"),

    # MS Method sections
    (r"^Orbitrap .+ Method Summary", "MS Method Summary"),
    (r"^Creator:", "Method Author"),
    (r"^Global Settings", "Global Settings"),
    (r"^Experiment\s+\d+", None),  # Dynamic name — handled below
    (r"^\s+Scan\s+\w+", None),     # Dynamic name — handled below

    # Generic Thermo patterns
    (r"^Source Settings", "Source Settings"),
    # Anchored so it only matches a standalone header, not parameter lines like
    # "Ion Source Temperature (C) = 280" that legitimately live inside a section.
    (r"^Ion Source(\s+Settings)?\s*$", "Ion Source Settings"),
    (r"^Tune Settings", "Tune Settings"),
    (r"^Inclusion List", "Inclusion List"),
    (r"^Exclusion List", "Exclusion List"),
    (r"^Mass List", "Mass List"),
    (r"^FAIMS", "Advanced MS Settings"),
    (r"^Data Dependent Settings", "Data Dependent Settings"),
    (r"^Dynamic Exclusion", "Dynamic Exclusion"),
]

def parse_method_into_sections(method_text):
    """Parse method text into labeled sections based on known header patterns."""
    lines = method_text.splitlines()
    sections = []
    current_name = "Header"
    current_lines = []

    for line in lines:
        stripped = line.strip()
        matched = False

        # Check for Experiment headers (dynamic naming)
        exp_match = re.match(r"^(Experiment\s+\d+.*)", stripped)
        if exp_match:
            if current_lines or current_name == "Header":
                sections.append((current_name, current_lines))
            current_name = exp_match.group(1).strip()
            current_lines = []
            matched = True

        # Check for Scan headers inside experiments (space- OR tab-indented).
        # A real scan header is e.g. "Scan FullScan"; exclude parameter lines
        # that merely start with the word "Scan" (e.g. "Scan Range (m/z) = ...",
        # "Scan Description = "), which always contain an '=' sign.
        if not matched and "=" not in line:
            scan_match = re.match(r"^[ \t]{2,}(Scan\s+\w+.*)", line)
            if scan_match:
                if current_lines:
                    sections.append((current_name, current_lines))
                current_name = scan_match.group(1).strip()
                current_lines = []
                matched = True

        # Check known patterns
        if not matched:
            for pattern, name in SECTION_PATTERNS:
                if name and re.match(pattern, stripped, re.IGNORECASE):
                    if current_lines or current_name == "Header":
                        sections.append((current_name, current_lines))
                    current_name = name
                    current_lines = []
                    matched = True
                    break

        if not matched:
            current_lines.append(line)

    # Last section
    if current_lines:
        sections.append((current_name, current_lines))

    return sections

def format_section_content(lines):
    """Clean up and indent section content."""
    # Strip leading/trailing blank lines
    while lines and lines[0].strip() == "":
        lines = lines[1:]
    while lines and lines[-1].strip() == "":
        lines = lines[:-1]

    if not lines:
        return ["  (no details)"]

    # Expand tabs so nested tables line up in a plain-text viewer
    return [f"  {line.expandtabs(4)}" for line in lines]

# ── LC Method Formatters ──────────────────────────────────────────────────────

def format_lc_method(method_text):
    """Parse the LC method text into a clean, readable format."""
    result = []

    header_params = [
        ("Column",          r"Column 1:\s*(.+)"),
        ("Column 2",        r"Column 2:\s*(.+)"),
        ("Solvent A1",      r"Loading Solvent A1:\s*(.+)"),
        ("Solvent A2",      r"Loading Solvent A2:\s*(.+)"),
        ("Solvent A3",      r"Loading Solvent A3:\s*(.+)"),
        ("Solvent B1",      r"Loading Solvent B1:\s*(.+)"),
        ("Solvent B2",      r"Loading Solvent B2:\s*(.+)"),
        ("Solvent B3",      r"Loading Solvent B3:\s*(.+?)(?:Method Comment|$)"),
        ("Pump Type",       r"Loading Pump Type:\s*(.+)"),
        ("Plumbing Mode",   r"Plumbing Mode:\s*(.+)"),
        ("Data Window",     r"Data Window Start:\s*([\d.]+\s*min)"),
        ("Window Duration", r"Data Window Duration:\s*([\d.]+\s*min)"),
    ]

    for name, pattern in header_params:
        m = re.search(pattern, method_text)
        if m:
            val = m.group(1).strip()
            if val == "N/A" and name in ("Column 2", "Solvent A2", "Solvent A3",
                                          "Solvent B2", "Solvent B3"):
                continue
            result.append(f"  {name:<20} {val}")

    result.append("")

    steps = re.findall(
        r"Step:\s*(\d+)\s+Start:\s*([\d.]+)\s*min\s+Time:\s*([\d.]+)\s*min.*?"
        r"Flow Rate:\s*(?:Ramp to\s+)?([\d.]+)\s*ml/min.*?"
        r"Grad Type:\s*(\w+).*?"
        r"%A:\s*([\d.]+)\s+%B:\s*([\d.]+)\s+%C\s+([\d.]+)\s+%D\s+([\d.]+)",
        method_text, re.DOTALL
    )

    if steps:
        result.append("  Gradient Program:")
        result.append("")
        result.append("  Step  Start   Duration  Flow       Type    %A      %B      %C      %D")
        result.append("        (min)   (min)     (mL/min)")
        result.append("  " + "-" * 68)
        for s in steps:
            result.append(
                f"  {s[0]:>4}  {s[1]:>5}   {s[2]:>8}  {s[3]:>9}   {s[4]:<6} {s[5]:>5}   {s[6]:>5}   {s[7]:>5}   {s[8]:>5}"
            )
        result.append("")

    mc = re.search(r"Method Comment:\s*(.+)", method_text)
    if mc and mc.group(1).strip() != "N/A":
        result.append(f"  Method Comment:    {mc.group(1).strip()}")
        result.append("")

    return result


def format_autosampler_method(method_text):
    """Parse LC autosampler section into clean format."""
    result = []
    params = [
        ("Wait for Detector", r"Wait for Detector:\s*(.+)"),
        ("Stroke Syncing",    r"Stroke Syncing:\s*(.+)"),
        ("Cycle Type",        r"STEP#\d+:\s*(.+)"),
        ("Draw Speed",        r"Draw Speed:\s*(.+)"),
        ("Draw Delay",        r"Draw Delay:\s*(.+)"),
        ("Dispense Speed",    r"Dispense Speed:\s*(.+)"),
        ("Bypass After",      r"Bypass After:\s*(.+)"),
        ("Pre Sample Airgap", r"Pre Sample Airgap:\s*(.+)"),
        ("Post Sample Airgap",r"Post Sample Airgap:\s*(.+)"),
        ("Wash Mode",         r"Wash Mode:\s*(.+)"),
        ("Wash Time",         r"Wash Time:\s*(.+)"),
        ("Wash Speed",        r"Wash Speed:\s*(.+)"),
        ("Pre Wash Airgap",   r"Pre Wash Airgap:\s*(.+)"),
    ]
    for name, pattern in params:
        m = re.search(pattern, method_text)
        if m:
            result.append(f"  {name:<22} {m.group(1).strip()}")
    return result


def format_tcc_method(method_text):
    """Parse LC TCC/column compartment section into clean format."""
    result = []
    text = method_text.replace("EnabledTemp:", "Enabled\n  Temperature:")
    params = [
        ("Temp Control",      r"Temp Ctrl:\s*(.+?)(?:\n|$)"),
        ("Temperature",       r"Temperature:\s*(.+)"),
        ("Temp",              r"(?<!Ready )Temp:\s*(\d+\s*Cdeg)"),
        ("Ready Temp Delta",  r"Ready Temp Delta:\s*(.+)"),
        ("Equilibrium Time",  r"Equilibrium Time:\s*(.+)"),
        ("Forced Air",        r"Forced Air:\s*(.+)"),
        ("Fan Speed",         r"Fan Speed:\s*(.+)"),
    ]
    for name, pattern in params:
        m = re.search(pattern, text)
        if m:
            result.append(f"  {name:<22} {m.group(1).strip()}")
    return result

# ── GC Method Formatters ──────────────────────────────────────────────────────

def format_gc_overview(overview_text):
    """Parse the '---- Overview ----' block of a GC method."""
    result = []
    params = [
        ("Method Name",  r"Name:\s*(.+)"),
        ("Comment",      r"Comment:\s*(.+)"),
        ("Run Time",     r"Run time:\s*(.+)"),
        ("Instrument",   r"Instrument:\s*(.+)"),
        ("Description",  r"Description:\s*(.+)"),
    ]
    for name, pattern in params:
        m = re.search(pattern, overview_text)
        if m and m.group(1).strip():
            result.append(f"  {name:<16} {m.group(1).strip()}")
    return result


def parse_oven_program(script_text):
    """Return a list of (time_min, temp_C) setpoints for the GC oven ramp,
    read in time order from the script's timed events."""
    program = []
    current_time = None
    for raw_line in script_text.splitlines():
        s = raw_line.strip()
        tm = re.match(r"^([\d.]+)\s*\[min\]", s)
        if tm:
            current_time = tm.group(1)
        temp = re.search(r"GC\.Temperature\.Nominal:\s*([\d.]+)", s)
        if temp and current_time is not None:
            program.append((current_time, temp.group(1)))
    return program


def format_gc_script(script_text):
    """Parse the '---- Script ----' block (inlet + oven program) of a GC method."""
    result = []

    gc_params = [
        ("Inlet Temperature",        r"GC\.BackInlet\.Temperature\.Nominal:\s*(.+)"),
        ("Inlet Split Mode",         r"GC\.BackInlet\.SplitMode:\s*(.+)"),
        ("Flow / Split Ratio Mode",  r"GC\.BackInlet\.FlowOrSplitRatio:\s*(.+)"),
        ("Split Flow",               r"GC\.BackInlet\.SplitFlow\.Nominal:\s*(.+)"),
        ("Split Ratio",              r"GC\.BackInlet\.SplitRatioSet\.Nominal:\s*(.+)"),
        ("Splitless Time",           r"GC\.BackInlet\.SplitlessTime:\s*(.+)"),
        ("Surge/Pulse Pressure",     r"GC\.BackInlet\.PulsePressure:\s*(.+)"),
        ("Pulse Time",               r"GC\.BackInlet\.PulseTime:\s*(.+)"),
        ("Purge Flow",               r"GC\.BackInlet\.PurgeFlow\.Nominal:\s*(.+)"),
        ("Gas Saver Flow",           r"GC\.BackInlet\.GasSaverFlow:\s*(.+)"),
        ("Gas Saver Time",           r"GC\.BackInlet\.GasSaverTime:\s*(.+)"),
        ("Column Flow",              r"GC\.BackInlet\.Flow\.Nominal:\s*(.+)"),
        ("Transfer Line Temp (Heater 1)", r"GC\.Heater1\.Temperature\.Nominal:\s*(.+)"),
        ("Aux Heater Temp (Heater 2)",     r"GC\.Heater2\.Temperature\.Nominal:\s*(.+)"),
        ("Equilibration Time",       r"GC\.EquilibrationTime:\s*(.+)"),
        ("Ready Delay",              r"GC\.ReadyDelay:\s*(.+)"),
    ]

    result.append("  Inlet / Flow Settings:")
    result.append("")
    for name, pattern in gc_params:
        m = re.search(pattern, script_text)
        if m:
            result.append(f"    {name:<32} {m.group(1).strip()}")
    result.append("")

    # --- Oven temperature program ---
    program = parse_oven_program(script_text)
    if program:
        result.append("  Oven Temperature Program:")
        result.append("")
        result.append("    Time (min)   Temp (°C)   Ramp (°C/min)")
        result.append("    " + "-" * 42)
        prev = None
        for t_str, temp_str in program:
            try:
                t = float(t_str)
                temp = float(temp_str)
            except ValueError:
                continue
            rate = ""
            if prev is not None:
                dt = t - prev[0]
                dT = temp - prev[1]
                if dt > 0:
                    if abs(dT) < 1e-9:
                        rate = "hold"
                    else:
                        rate = f"{dT / dt:.1f}"
                elif abs(dT) < 1e-9:
                    rate = "initial"
            else:
                rate = "initial"
            result.append(f"    {t:>7.2f}     {temp:>7.1f}     {rate:>10}")
            prev = (t, temp)
        result.append("")

    return result


def format_triplus_method(triplus_text):
    """Reproduce the TriPlus RSH autosampler section faithfully (it is already
    hierarchically organized), with light cleanup and consistent indentation."""
    lines = triplus_text.splitlines()
    while lines and lines[0].strip() == "":
        lines = lines[1:]
    while lines and lines[-1].strip() == "":
        lines = lines[:-1]
    if not lines:
        return ["  (no details)"]
    return [f"  {line.expandtabs(4).rstrip()}" for line in lines]

# ── Main ──────────────────────────────────────────────────────────────────────

if not os.path.exists(raw_file):
    print(f"Error: Raw file not found: {raw_file}")
    sys.exit(1)

if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# Open raw file
raw = RawFile(raw_file)
rfa = raw._raw_file_access

n_methods = rfa.instrument_methods_count

# Read (and clean) all method texts once
method_texts = [clean_text(rfa.get_instrument_method(i)) for i in range(n_methods)]
all_method_text = "\n".join(method_texts)
inst_type = detect_instrument_type(all_method_text)

# --- File metadata ---
basename = os.path.splitext(os.path.basename(raw_file))[0]
out_file = os.path.join(output_dir, f"{basename}_method_report.txt")

report = []
report.append(top_header("INSTRUMENT METHOD REPORT"))
report.append("")

# File information
report.append(section_header("File Information"))
report.append(f"  File Name:            {os.path.basename(raw_file)}")
report.append(f"  Full Path:            {raw_file}")
report.append(f"  Front-End Type:       {inst_type}")
report.append(f"  Creation Date:        {rfa.creation_date}")
report.append(f"  Number of Scans:      {raw.number_of_scans}")
report.append(f"  First Scan:           {raw.first_scan}")
report.append(f"  Last Scan:            {raw.last_scan}")
report.append(f"  Total Time (min):     {raw.total_time_min:.2f}")
report.append("")

# Instrument information
report.append(section_header("Instrument Information"))
model = getattr(rfa.file_header, "InstrumentModel", None) if hasattr(rfa, "file_header") else None
report.append(f"  Instrument Model:     {model if model else 'N/A'}")

# Instrument name from the MS method summary (Orbitrap Exploris 120 / GC / ...)
for mt in method_texts:
    m = re.match(r"^(Orbitrap .+?) Method Summary", mt, re.MULTILINE)
    if m:
        report.append(f"  Instrument Name:      {m.group(1)}")
        break

# Method creator and last modified
for mt in method_texts:
    cr = re.search(r"Creator:\s*(.+?)\s{2,}Last Modified:\s*(.+)", mt)
    if cr:
        report.append(f"  Method Creator:       {cr.group(1).strip()}")
        report.append(f"  Last Modified:        {cr.group(2).strip()}")
        break

report.append(f"  Computer Name:        {rfa.computer_name}")
report.append(f"  Creator ID:           {rfa.creator_id}")
report.append("")

# Sample information
report.append(section_header("Sample Information"))
try:
    si = rfa.sample_information
    if si:
        sample_fields = [
            ("Sample Name",        si.sample_name),
            ("Sample ID",          si.sample_id),
            ("Comment",            si.comment),
            ("Vial",               si.vial),
            ("Injection Volume",   si.injection_volume),
            ("Sample Volume",      si.sample_volume),
            ("Sample Type",        str(si.sample_type).replace("SampleType.", "")),
            ("Barcode",            si.barcode),
            ("Method File",        si.instrument_method_file),
            ("Calibration Level",  si.calibration_level),
            ("Dilution Factor",    si.dilution_factor),
        ]
        for name, val in sample_fields:
            if val is not None and str(val).strip() and str(val).strip() != "0" and str(val).strip() != "0.0":
                report.append(f"  {name:<24}{val}")
except Exception:
    report.append("  (Could not retrieve sample information)")
report.append("")

# --- Method details ---
report.append(top_header(f"METHOD DETAILS ({n_methods} instrument method(s) found)"))

if inst_type == "GC":
    METHOD_LABELS = {
        0: "GC / AUTOSAMPLER METHOD",
        1: "MASS SPECTROMETER METHOD (EI)",
    }
else:
    METHOD_LABELS = {
        0: "LC / AUTOSAMPLER / COLUMN OVEN METHOD",
        1: "MASS SPECTROMETER METHOD",
    }

for i in range(n_methods):
    method_text = method_texts[i]

    label = METHOD_LABELS.get(i, f"INSTRUMENT METHOD {i + 1}")
    report.append("")
    report.append(top_header(label))

    if i == 0 and inst_type == "GC":
        # ── GC front end: Overview / Script / TriPlus RSH ──
        def _split_after(text, marker):
            return text.split(marker, 1)[1] if marker in text else ""

        overview_text = ""
        script_text = ""
        triplus_text = ""

        if "---- Overview ----" in method_text:
            overview_text = _split_after(method_text, "---- Overview ----")
            overview_text = overview_text.split("---- Script ----", 1)[0]
        if "---- Script ----" in method_text:
            script_text = _split_after(method_text, "---- Script ----")
            script_text = script_text.split("---- TriPlus RSH Method ----", 1)[0]
        if "---- TriPlus RSH Method ----" in method_text:
            triplus_text = _split_after(method_text, "---- TriPlus RSH Method ----")

        if overview_text:
            report.append(section_header("Overview"))
            report.extend(format_gc_overview(overview_text))
            report.append("")

        if script_text:
            report.append(section_header("GC Method (Inlet & Oven Program)"))
            report.extend(format_gc_script(script_text))
        else:
            # Fallback: dump the whole method if markers were not found
            report.append(section_header("GC Method"))
            report.extend(format_section_content(method_text.splitlines()))
            report.append("")

        if triplus_text:
            report.append(section_header("Autosampler (TriPlus RSH)"))
            report.extend(format_triplus_method(triplus_text))
            report.append("")

    elif i == 0:
        # ── LC front end: LC / Autosampler / TCC ──
        lc_text = method_text.split("AUTOSAMPLER METHOD")[0] if "AUTOSAMPLER METHOD" in method_text else method_text
        as_text = ""
        tcc_text = ""

        if "AUTOSAMPLER METHOD" in method_text:
            remainder = method_text.split("AUTOSAMPLER METHOD", 1)[1]
            if "TCC:" in remainder:
                as_text = remainder.split("TCC:", 1)[0]
                tcc_text = remainder.split("TCC:", 1)[1]
            else:
                as_text = remainder

        report.append(section_header("LC Method"))
        report.extend(format_lc_method(lc_text))

        if as_text:
            report.append(section_header("Autosampler Method"))
            report.extend(format_autosampler_method(as_text))
            report.append("")

        if tcc_text:
            report.append(section_header("Column Compartment (TCC)"))
            report.extend(format_tcc_method(tcc_text))
            report.append("")

    else:
        # ── MS method: use generic section parser (works for ESI and EI) ──
        sections = parse_method_into_sections(method_text)

        for sec_name, sec_lines in sections:
            content = format_section_content(sec_lines)
            if len(content) == 1 and content[0].strip() == "(no details)":
                continue
            report.append(section_header(sec_name))
            report.extend(content)
            report.append("")

# --- Quick Reference ---
report.append("")
report.append(top_header("QUICK REFERENCE - KEY PARAMETERS"))

def find_param(text, pattern):
    m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else None

report.append("")
report.append("  Source Parameters:")

if inst_type == "GC":
    source_params = [
        ("Ionization Mode",         r"Ionization Mode\s*=\s*(.+)"),
        ("Ion Source Temperature",  r"Ion Source Temperature\s*\([^)]*\)\s*=\s*(.+)"),
        ("Filament",                r"(?m)^\s*Filament\s*=\s*(.+)"),
        ("Calibration Gas",         r"(?m)^\s*Calibration Gas\s*=\s*(.+)"),
        ("C-Trap Offset",           r"C-Trap Offset\s*=\s*(.+)"),
        ("Internal Mass Calibration", r"Internal Mass Calibration\s*=\s*(.+)"),
        ("Mass Tolerance (ppm)",    r"Mass Tolerance\s*\(ppm\)\s*=\s*(.+)"),
        ("Acquisition Delay (min)", r"Acquisition Delay\s*\(min\)\s*=\s*(.+)"),
    ]
else:
    source_params = [
        ("Spray Voltage (+)",       r"Spray Voltage:\s*Positive Ion\s*\(V\)\s*=\s*(.+)"),
        ("Spray Voltage (-)",       r"Spray Voltage:\s*Negative Ion\s*\(V\)\s*=\s*(.+)"),
        ("Ion Source Type",         r"Ion Source Type\s*=\s*(.+)"),
        ("Sheath Gas (Arb)",        r"Sheath Gas\s*\(Arb\)\s*=\s*(.+)"),
        ("Aux Gas (Arb)",           r"Aux Gas\s*\(Arb\)\s*=\s*(.+)"),
        ("Sweep Gas (Arb)",         r"Sweep Gas\s*\(Arb\)\s*=\s*(.+)"),
        ("Ion Transfer Tube Temp",  r"Ion Transfer Tube Temp\s*\([^)]*\)\s*=\s*(.+)"),
        ("Vaporizer Temp",          r"Vaporizer Temp\s*\([^)]*\)\s*=\s*(.+)"),
        ("RF Lens (%)",             r"RF Lens\s*\(%\)\s*=\s*(.+)"),
    ]

for name, pattern in source_params:
    val = find_param(all_method_text, pattern)
    if val:
        report.append(f"    {name:<28} {val}")

report.append("")
report.append("  MS Scan Parameters:")

ms_params = [
    ("Orbitrap Resolution",    r"Orbitrap Resolution\s*=\s*(.+)"),
    ("Scan Range (m/z)",       r"Scan Range\s*\(m/z\)\s*=\s*(.+)"),
    ("AGC Target",             r"(?<!Normalized )(?<!Absolute )AGC Target\s*=\s*(.+)"),
    ("Absolute AGC Target",    r"Absolute AGC Target\s*=\s*(.+)"),
    ("Normalized AGC (%)",     r"Normalized AGC Target\s*\(%\)\s*=\s*(.+)"),
    ("Maximum Injection Time", r"Maximum Injection Time Mode\s*=\s*(.+)"),
    ("Microscans",             r"Microscans\s*=\s*(.+)"),
    ("Polarity",               r"Polarity\s*=\s*(.+)"),
    ("Data Type",              r"DataType\s*=\s*(.+)"),
    ("EASY-IC",                r"EASY-IC\s*=\s*(.+)"),
    ("Application Mode",       r"Application Mode\s*=\s*(.+)"),
]

for name, pattern in ms_params:
    val = find_param(all_method_text, pattern)
    if val:
        report.append(f"    {name:<28} {val}")

report.append("")

if inst_type == "GC":
    report.append("  GC Parameters:")
    gc_ref_params = [
        ("Method Duration (min)",  r"Method Duration\s*\(min\)\s*=\s*(.+)"),
        ("Inlet Temperature",      r"GC\.BackInlet\.Temperature\.Nominal:\s*(.+)"),
        ("Inlet Split Mode",       r"GC\.BackInlet\.SplitMode:\s*(.+)"),
        ("Split Flow",             r"GC\.BackInlet\.SplitFlow\.Nominal:\s*(.+)"),
        ("Split Ratio",            r"GC\.BackInlet\.SplitRatioSet\.Nominal:\s*(.+)"),
        ("Column Flow",            r"GC\.BackInlet\.Flow\.Nominal:\s*(.+)"),
        ("Transfer Line Temp",     r"GC\.Heater1\.Temperature\.Nominal:\s*(.+)"),
    ]
    for name, pattern in gc_ref_params:
        val = find_param(all_method_text, pattern)
        if val:
            report.append(f"    {name:<28} {val}")

    # Oven ramp summary (initial / final from the program)
    program = parse_oven_program(method_texts[0]) if n_methods else []
    if program:
        report.append(f"    {'Oven Initial Temp':<28} {program[0][1]} °C")
        report.append(f"    {'Oven Final Temp':<28} {program[-1][1]} °C")
else:
    report.append("  LC Parameters:")
    lc_params = [
        ("Column",                 r"Column 1:\s*(.+)"),
        ("Solvent A",              r"Loading Solvent A1:\s*(.+)"),
        ("Solvent B",              r"Loading Solvent B1:\s*(.+)"),
        ("Column Temp",            r"Temp:\s*(\d+\s*Cdeg)"),
        ("Method Duration (min)",  r"Method Duration\s*\(min\)\s*=\s*(.+)"),
    ]
    for name, pattern in lc_params:
        val = find_param(all_method_text, pattern)
        if val:
            report.append(f"    {name:<28} {val}")

# Footer
report.append("")
report.append(divider("="))
report.append(f"  Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
report.append(divider("="))
report.append("  END OF REPORT")
report.append(divider("="))

# --- Write (UTF-8 so ° and µ symbols survive) ---
with open(out_file, "w", encoding="utf-8") as f:
    f.write("\n".join(report))

print(f"Method report saved: {out_file}")

# Cleanup
raw = None
