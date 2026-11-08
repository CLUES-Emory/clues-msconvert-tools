# instrument_method_report.py
# Extracts instrument method details from Thermo .raw files using fisher_py
# and outputs a formatted, easy-to-read text report with clearly separated
# sections for all method components, plus the same content as JSON.
#
# Supports BOTH front-end configurations, auto-detected from the method text:
#   * LC-MS  (e.g. Orbitrap Exploris 120): LC / Autosampler / TCC + ESI MS
#   * GC-HRMS (Orbitrap Exploris GC):      GC oven/inlet / TriPlus RSH + EI MS
#
# Usage (command line): python instrument_method_report.py <raw_file> <output_dir>
#   writes <output_dir>/<raw basename>_method_report.txt and _method_report.json
# Summary of all methods of one LC mode (used by the LC-HRMS driver):
#   python instrument_method_report.py --summary <methods.tsv> <report_dir> <study_id> <lc_mode>
#   reads <study_id>_<method>_method_report.json for each row of <methods.tsv> and writes
#   <report_dir>/<study_id>_<lc_mode>_method_summary.json (standard library only)
# Usage (interactive):  Set raw_file and output_dir below, then run.
#
# Requires: pip install fisher_py (not needed for --summary)
#
# 2026-11-08: LC gradient for binary pumps (%A1/%B1; the quaternary %A..%D pattern
#   alone matched no CLUES method, so the gradient was never printed); dual-column
#   (two-channel) description; JSON output; --summary mode. Parsers are importable
#   (tests/test_instrument_method_report.py).

import csv
import json
import sys
import os
import re
from datetime import datetime

REPORT_FORMAT = "clues-method-report 1"

# ── USER SETTINGS (for interactive use) ───────────────────────────────────────
# Set these if running interactively. Command line args override these.

raw_file   = r"C:\path\to\your_file.raw"
output_dir = r"C:\path\to\output"

# ── END USER SETTINGS ─────────────────────────────────────────────────────────

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

# ── LC Method Parsers / Formatters ────────────────────────────────────────────

LC_HEADER_PARAMS = [
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


def parse_lc_header(method_text):
    """Column, solvents, pump, plumbing and MS data window of the LC method text, as printed.
    The unused slots (Column 2, Solvent A2/A3/B2/B3) are left out when they read N/A."""
    out = {}
    for name, pattern in LC_HEADER_PARAMS:
        m = re.search(pattern, method_text)
        if m:
            val = m.group(1).strip()
            if val == "N/A" and name in ("Column 2", "Solvent A2", "Solvent A3",
                                          "Solvent B2", "Solvent B3"):
                continue
            out[name] = val
    mc = re.search(r"Method Comment:\s*(.+)", method_text)
    if mc and mc.group(1).strip() != "N/A":
        out["Method Comment"] = mc.group(1).strip()
    return out


def parse_lc_gradient(method_text):
    """Pump program of the LC method text, one dict per 'Step:' block.

    Composition keys are the channel labels as printed: A1/B1 on a binary pump
    ('%A1: 10.00    %B1: 90.00'), A/B/C/D on a quaternary pump ('%A: 5.0  %B: 95.0  %C 0.0  %D 0.0').
    'Flow Rate: Ramp to  0.450 ml/min' gives flow_ml_min 0.45 and flow_ramp True.
    Returns (steps, n_step_lines): a step block that lacks start/time, flow or composition is
    not returned, so n_step_lines > len(steps) means part of the program was not read."""
    n_step_lines = len(re.findall(r"Step:\s*\d+\s+Start:", method_text))
    steps = []
    for block in re.split(r"(?=Step:\s*\d+\s+Start:)", method_text)[1:]:
        head = re.search(r"Step:\s*(\d+)\s+Start:\s*([\d.]+)\s*min\s+Time:\s*([\d.]+)\s*min", block)
        flow = re.search(r"Flow Rate:\s*(Ramp to\s+)?([\d.]+)\s*ml/min", block, re.IGNORECASE)
        grad = re.search(r"Grad Type:\s*(\w+)", block)
        comp = re.findall(r"%([A-D]\d?):?\s*([\d.]+)", block)
        if not (head and flow and comp):
            continue
        steps.append({
            "step": int(head.group(1)),
            "start_min": float(head.group(2)),
            "duration_min": float(head.group(3)),
            "flow_ml_min": float(flow.group(2)),
            "flow_ramp": bool(flow.group(1)),
            "type": grad.group(1) if grad else None,
            "percent": {k: float(v) for k, v in comp},
        })
    return steps, n_step_lines


def _minutes(value):
    m = re.match(r"\s*([\d.]+)", value or "")
    return float(m.group(1)) if m else None


def lc_column_setup(header, steps, method_file=None):
    """MS data window vs LC program length, and the column channel from the method name.

    CLUES dual-column (two-channel) LC: the method names carry the channel (..._Ch1-5min for one
    column, ..._Ch2-5min for the other). The MS records only the data window of each injection; the
    rest of the LC program washes and re-equilibrates that column while the valve sends the other
    column's effluent to the MS. dual_column is True when the name has a channel AND the LC program
    runs past the end of the data window."""
    ws = _minutes(header.get("Data Window"))
    wd = _minutes(header.get("Window Duration"))
    we = ws + wd if ws is not None and wd is not None else None
    pe = max((s["start_min"] + s["duration_min"] for s in steps), default=None)
    name = os.path.splitext(os.path.basename((method_file or "").replace("\\", "/")))[0] or None
    ch = re.search(r"_Ch(\d+)", name or "")
    channel = int(ch.group(1)) if ch else None
    dual = bool(channel is not None and we is not None and pe is not None and pe > we + 1e-9)
    if dual:
        text = (f"Dual-column LC: column channel {channel} (from '_Ch{channel}' in the method name). "
                f"The analytical separation runs in the MS data window, {ws:.2f}-{we:.2f} min. "
                f"From {we:.2f} to {pe:.2f} min this column is washed and re-equilibrated while the valve "
                f"switches the MS to the other column, which runs the next injection with its own method.")
    elif channel is not None:
        text = f"Column channel {channel} (from '_Ch{channel}' in the method name); the LC program ends within the MS data window."
    else:
        text = None
    return {"method_name": name, "channel": channel, "data_window_start_min": ws, "data_window_end_min": we,
            "lc_program_min": pe, "dual_column": dual, "description": text}


def format_lc_method(method_text, method_file=None):
    """Parse the LC method text into a clean, readable format."""
    result = []
    header = parse_lc_header(method_text)
    for name, val in header.items():
        if name != "Method Comment":
            result.append(f"  {name:<20} {val}")
    result.append("")

    steps, n_step_lines = parse_lc_gradient(method_text)
    if steps:
        keys = sorted({k for s in steps for k in s["percent"]})
        result.append("  Gradient Program:")
        result.append("")
        result.append("  Step  Start   Duration  Flow          Type   " + "".join(f"{'%' + k:>8}" for k in keys))
        result.append("        (min)   (min)     (mL/min)")
        result.append("  " + "-" * (46 + 8 * len(keys)))
        for s in steps:
            flow = ("ramp to " if s["flow_ramp"] else "") + f"{s['flow_ml_min']:.3f}"
            result.append(f"  {s['step']:>4}  {s['start_min']:>5.2f}   {s['duration_min']:>8.2f}  {flow:>13} {s['type'] or '':<6} "
                          + "".join(f"{s['percent'].get(k, float('nan')):>8.2f}" for k in keys))
        result.append("")
    if n_step_lines > len(steps):
        result.append(f"  WARNING: {n_step_lines} gradient step(s) in the method text, {len(steps)} read; "
                      "the table above is incomplete; check the LC method.")
        result.append("")

    setup = lc_column_setup(header, steps, method_file)
    if setup["description"]:
        result.append("  Column Setup:")
        result.append(f"    {setup['description']}")
        result.append("")

    if "Method Comment" in header:
        result.append(f"  Method Comment:    {header['Method Comment']}")
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


# ── Structured (JSON) form of the method ──────────────────────────────────────

def _kv(line):
    """'key = value' / 'key= value' -> (key, value); None for other lines."""
    m = re.match(r"^\s*([^=|]+?)\s*=\s*(.*?)\s*$", line)
    return (m.group(1).strip(), m.group(2).strip()) if m else None


def ms_method_json(method_text):
    """MS method text -> list of sections, each a list of groups (the section itself, then each
    'Filter <name>' / 'Data Dependent Properties' block inside it) with their key = value settings.
    A mass list table is summarised as its column names and number of rows (the rows are in the
    text report)."""
    out = []
    for sec_name, sec_lines in parse_method_into_sections(method_text):
        groups = [{"group": sec_name, "settings": {}}]
        in_table, cols, n_rows = False, None, 0
        for line in sec_lines:
            s = line.strip()
            if "End Mass List Table" in s:
                groups[-1]["mass_list"] = {"columns": cols or [], "n_rows": n_rows}
                in_table = False
                continue
            if "Mass List Table" in s:
                in_table, cols, n_rows = True, None, 0
                continue
            if in_table:
                if cols is None:
                    cols = [c.strip() for c in s.split("|") if c.strip()]
                elif s:
                    n_rows += 1
                continue
            f = re.match(r"^Filter\s+(\w+)$", s)
            if f or s == "Data Dependent Properties":
                groups.append({"group": f"Filter {f.group(1)}" if f else s, "settings": {}})
                continue
            kv = _kv(line)
            if kv and kv[0] not in groups[-1]["settings"]:
                groups[-1]["settings"][kv[0]] = kv[1]
            elif s and not kv:
                groups[-1].setdefault("lines", []).append(s)
        groups = [g for g in groups if g["settings"] or g.get("lines") or g.get("mass_list")]
        if groups:
            out.append({"section": sec_name, "groups": groups})
    return out


def find_param(text, pattern):
    m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else None


def quick_reference(all_method_text, method_texts, inst_type, lc=None):
    """Key parameters as [(group, [(name, value), ...]), ...]; values as printed in the method."""
    groups = []
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
    groups.append(("Source Parameters", [(n, find_param(all_method_text, p)) for n, p in source_params]))

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
    groups.append(("MS Scan Parameters", [(n, find_param(all_method_text, p)) for n, p in ms_params]))

    if inst_type == "GC":
        gc_ref_params = [
            ("Method Duration (min)",  r"Method Duration\s*\(min\)\s*=\s*(.+)"),
            ("Inlet Temperature",      r"GC\.BackInlet\.Temperature\.Nominal:\s*(.+)"),
            ("Inlet Split Mode",       r"GC\.BackInlet\.SplitMode:\s*(.+)"),
            ("Split Flow",             r"GC\.BackInlet\.SplitFlow\.Nominal:\s*(.+)"),
            ("Split Ratio",            r"GC\.BackInlet\.SplitRatioSet\.Nominal:\s*(.+)"),
            ("Column Flow",            r"GC\.BackInlet\.Flow\.Nominal:\s*(.+)"),
            ("Transfer Line Temp",     r"GC\.Heater1\.Temperature\.Nominal:\s*(.+)"),
        ]
        vals = [(n, find_param(all_method_text, p)) for n, p in gc_ref_params]
        program = parse_oven_program(method_texts[0]) if method_texts else []
        if program:
            vals += [("Oven Initial Temp", f"{program[0][1]} °C"), ("Oven Final Temp", f"{program[-1][1]} °C")]
        groups.append(("GC Parameters", vals))
    else:
        lc_params = [
            ("Column",                 r"Column 1:\s*(.+)"),
            ("Solvent A",              r"Loading Solvent A1:\s*(.+)"),
            ("Solvent B",              r"Loading Solvent B1:\s*(.+)"),
            ("Column Temp",            r"Temp:\s*(\d+\s*Cdeg)"),
            ("Method Duration (min)",  r"Method Duration\s*\(min\)\s*=\s*(.+)"),
        ]
        vals = [(n, find_param(all_method_text, p)) for n, p in lc_params]
        if lc:
            setup, steps = lc["column_setup"], lc["gradient"]
            ws, we = setup["data_window_start_min"], setup["data_window_end_min"]
            if steps and we is not None:
                sep = sorted({s["flow_ml_min"] for s in steps if s["start_min"] < we and not s["flow_ramp"]})
                vals.append(("Flow Rate, separation (mL/min)", ", ".join(f"{f:.3f}" for f in sep) or None))
            if ws is not None and we is not None:
                vals.append(("MS Data Window (min)", f"{ws:.2f}-{we:.2f}"))
            if setup["lc_program_min"] is not None:
                vals.append(("LC Program (min)", f"{setup['lc_program_min']:.2f}"))
            if setup["channel"] is not None:
                vals.append(("Column Channel", f"{setup['channel']}" + (" (dual-column)" if setup["dual_column"] else "")))
        groups.append(("LC Parameters", vals))
    return [(g, [(n, v) for n, v in vals if v]) for g, vals in groups]


def lc_front_end_json(method_text, method_file=None):
    """LC front end (method 0) -> header, gradient, column setup, autosampler and TCC settings."""
    lc_text = method_text.split("AUTOSAMPLER METHOD")[0]
    as_text, tcc_text = "", ""
    if "AUTOSAMPLER METHOD" in method_text:
        remainder = method_text.split("AUTOSAMPLER METHOD", 1)[1]
        as_text, _, tcc_text = remainder.partition("TCC:")
    header = parse_lc_header(lc_text)
    steps, n_step_lines = parse_lc_gradient(lc_text)

    def lines_to_dict(lines):
        d = {}
        for ln in lines:
            m = re.match(r"^\s*(.+?)\s{2,}(.+?)\s*$", ln)
            if m:
                d[m.group(1)] = m.group(2)
        return d

    return {
        "header": header,
        "gradient": steps,
        "gradient_steps_in_text": n_step_lines,
        "column_setup": lc_column_setup(header, steps, method_file),
        "autosampler": lines_to_dict(format_autosampler_method(as_text)) if as_text else {},
        "column_compartment": lines_to_dict(format_tcc_method(tcc_text)) if tcc_text else {},
    }


# ── Report for one RAW file ───────────────────────────────────────────────────

def build_report(raw_path):
    """Read one RAW file with fisher_py; return (report lines, JSON dict)."""
    from fisher_py import RawFile   # imported here so the parsers above load without fisher_py

    raw = RawFile(raw_path)
    rfa = raw._raw_file_access
    n_methods = rfa.instrument_methods_count

    # Read (and clean) all method texts once
    method_texts = [clean_text(rfa.get_instrument_method(i)) for i in range(n_methods)]
    all_method_text = "\n".join(method_texts)
    inst_type = detect_instrument_type(all_method_text)

    data = {"format": REPORT_FORMAT, "generated": datetime.now().isoformat(timespec="seconds"),
            "front_end_type": inst_type}

    report = []
    report.append(top_header("INSTRUMENT METHOD REPORT"))
    report.append("")

    # File information
    report.append(section_header("File Information"))
    report.append(f"  File Name:            {os.path.basename(raw_path)}")
    report.append(f"  Full Path:            {raw_path}")
    report.append(f"  Front-End Type:       {inst_type}")
    report.append(f"  Creation Date:        {rfa.creation_date}")
    report.append(f"  Number of Scans:      {raw.number_of_scans}")
    report.append(f"  First Scan:           {raw.first_scan}")
    report.append(f"  Last Scan:            {raw.last_scan}")
    report.append(f"  Total Time (min):     {raw.total_time_min:.2f}")
    report.append("")
    data["file"] = {"file_name": os.path.basename(raw_path), "full_path": raw_path,
                    "creation_date": str(rfa.creation_date), "number_of_scans": raw.number_of_scans,
                    "total_time_min": round(raw.total_time_min, 4)}

    # Instrument information
    report.append(section_header("Instrument Information"))
    model = getattr(rfa.file_header, "InstrumentModel", None) if hasattr(rfa, "file_header") else None
    report.append(f"  Instrument Model:     {model if model else 'N/A'}")
    inst = {"instrument_model": model}

    # Instrument name from the MS method summary (Orbitrap Exploris 120 / GC / ...)
    for mt in method_texts:
        m = re.match(r"^(Orbitrap .+?) Method Summary", mt, re.MULTILINE)
        if m:
            report.append(f"  Instrument Name:      {m.group(1)}")
            inst["instrument_name"] = m.group(1)
            break

    # Method creator and last modified
    for mt in method_texts:
        cr = re.search(r"Creator:\s*(.+?)\s{2,}Last Modified:\s*(.+)", mt)
        if cr:
            report.append(f"  Method Creator:       {cr.group(1).strip()}")
            report.append(f"  Last Modified:        {cr.group(2).strip()}")
            inst["method_last_modified"] = cr.group(2).strip()
            break

    # Devices with a method in the RAW file's copy of the instrument method (e.g. the LC
    # controller and the MS); not every fisher_py build exposes this, so it is optional
    try:
        devices = [str(d) for d in rfa.get_all_instrument_names_from_instrument_method()]
    except Exception:
        devices = []
    if devices:
        report.append(f"  Method Devices:       {', '.join(devices)}")
    inst["method_devices"] = devices

    report.append(f"  Computer Name:        {rfa.computer_name}")
    report.append(f"  Creator ID:           {rfa.creator_id}")
    report.append("")
    data["instrument"] = inst

    # Sample information
    report.append(section_header("Sample Information"))
    sample = {}
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
                sample[name] = None if val is None else str(val)
                if val is not None and str(val).strip() and str(val).strip() != "0" and str(val).strip() != "0.0":
                    report.append(f"  {name:<24}{val}")
    except Exception:
        report.append("  (Could not retrieve sample information)")
    report.append("")
    data["sample"] = sample
    method_file = sample.get("Method File")

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

    lc = None
    data["ms_methods"] = []
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
            data["gc_oven_program"] = [{"time_min": t, "temp_c": v} for t, v in parse_oven_program(script_text)]

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
            report.extend(format_lc_method(lc_text, method_file))

            if as_text:
                report.append(section_header("Autosampler Method"))
                report.extend(format_autosampler_method(as_text))
                report.append("")

            if tcc_text:
                report.append(section_header("Column Compartment (TCC)"))
                report.extend(format_tcc_method(tcc_text))
                report.append("")

            lc = lc_front_end_json(method_text, method_file)
            if lc["gradient_steps_in_text"] > len(lc["gradient"]):
                print(f"WARNING: {os.path.basename(raw_path)}: {lc['gradient_steps_in_text']} gradient step(s) "
                      f"in the LC method, {len(lc['gradient'])} read", file=sys.stderr)

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
            data["ms_methods"].append(ms_method_json(method_text))

    data["lc"] = lc

    # --- Quick Reference ---
    report.append("")
    report.append(top_header("QUICK REFERENCE - KEY PARAMETERS"))
    qr = quick_reference(all_method_text, method_texts, inst_type, lc)
    for g, vals in qr:
        report.append("")
        report.append(f"  {g}:")
        for name, val in vals:
            report.append(f"    {name:<28} {val}")
    data["quick_reference"] = {g: dict(vals) for g, vals in qr}

    # Footer
    report.append("")
    report.append(divider("="))
    report.append(f"  Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(divider("="))
    report.append("  END OF REPORT")
    report.append(divider("="))
    return report, data


# ── Summary of all methods of one LC mode (standard library only) ─────────────

def write_method_summary(methods_tsv, report_dir, study_id, lc_mode):
    """Merge the per-method JSON reports listed in <methods_tsv> (lc_sequence_mapfile.py's
    methods table) into <report_dir>/<study_id>_<lc_mode>_method_summary.json."""
    with open(methods_tsv, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    methods = []
    for r in rows:
        rep = os.path.join(report_dir, f"{study_id}_{r['Method']}_method_report.json")
        entry = {"method": r["Method"], "category": r["Category"], "polarity": r["Polarity"],
                 "injections": int(r["Injections"]) if r.get("Injections", "").isdigit() else r.get("Injections"),
                 "sample_types": [s.strip() for s in (r.get("SampleTypes") or "").split(";") if s.strip()],
                 "representative_raw": r.get("Representative") or None,
                 "report_json": os.path.basename(rep) if os.path.exists(rep) else None}
        if os.path.exists(rep):
            with open(rep, encoding="utf-8") as fh:
                entry["report"] = json.load(fh)
        else:
            entry["report"] = None
            entry["note"] = "no report (no RAW file yet, fisher_py missing, or the report failed)"
        methods.append(entry)

    # Dual-column pairing of the MS1 methods by column channel. The report takes the channel from
    # the RAW file's method path; when that was not readable, use the method name of the table.
    channels = {}
    for m in methods:
        lc = (m["report"] or {}).get("lc") or {}
        setup = lc.get("column_setup") or {}
        if lc and setup.get("channel") is None:
            setup = lc_column_setup(lc.get("header") or {}, lc.get("gradient") or [], m["method"])
            setup["channel_from"] = "methods table"
            lc["column_setup"] = setup
        if m["category"] == "MS1" and setup.get("channel") is not None:
            channels.setdefault(str(setup["channel"]), []).append(
                {"method": m["method"], "polarity": m["polarity"], "dual_column": setup.get("dual_column"),
                 "data_window_start_min": setup.get("data_window_start_min"),
                 "data_window_end_min": setup.get("data_window_end_min"), "lc_program_min": setup.get("lc_program_min")})
    dual = any(x["dual_column"] for v in channels.values() for x in v)
    description = None
    if dual:
        parts = [f"channel {ch}: {', '.join(x['method'] + ' (' + x['polarity'] + ')' for x in v)}"
                 for ch, v in sorted(channels.items())]
        x0 = next(x for v in channels.values() for x in v if x["dual_column"])
        description = (f"Dual-column LC with {len(channels)} column channel(s) ({'; '.join(parts)}). Injections "
                       f"alternate between the columns: each is separated during the MS data window "
                       f"({x0['data_window_start_min']:.2f}-{x0['data_window_end_min']:.2f} min), then its column is "
                       f"washed and re-equilibrated (to {x0['lc_program_min']:.2f} min) while the valve sends the "
                       f"other column's injection to the MS.")
    summary = {
        "format": "clues-method-summary 1",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "study_id": study_id,
        "lc_mode": lc_mode,
        "sources": {"methods_table": os.path.basename(methods_tsv),
                    "reports": "<study_id>_<method>_method_report.json in this folder"},
        "n_methods": {"total": len(methods), "MS1": sum(m["category"] == "MS1" for m in methods),
                      "MSMS": sum(m["category"] == "MSMS" for m in methods),
                      "with_report": sum(m["report"] is not None for m in methods)},
        "lc_system": {"dual_column": dual, "channels": channels, "description": description},
        "methods": methods,
    }
    out = os.path.join(report_dir, f"{study_id}_{lc_mode}_method_summary.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return out


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv):
    if len(argv) >= 2 and argv[1] == "--summary":
        if len(argv) != 6:
            print("Usage: instrument_method_report.py --summary <methods.tsv> <report_dir> <study_id> <lc_mode>")
            return 2
        out = write_method_summary(argv[2], argv[3], argv[4], argv[5])
        print(f"Method summary saved: {out}")
        return 0

    rf, od = raw_file, output_dir
    if len(argv) >= 3:
        rf, od = argv[1], argv[2]
    elif len(argv) == 2:
        rf = argv[1]

    if not os.path.exists(rf):
        print(f"Error: Raw file not found: {rf}")
        return 1
    if not os.path.exists(od):
        os.makedirs(od)

    report, data = build_report(rf)
    basename = os.path.splitext(os.path.basename(rf))[0]
    out_file = os.path.join(od, f"{basename}_method_report.txt")
    # --- Write (UTF-8 so ° and µ symbols survive) ---
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    with open(os.path.join(od, f"{basename}_method_report.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Method report saved: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
