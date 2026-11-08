#!/usr/bin/env python
"""
lc_sequence_mapfile.py - sample mapfiles, conversion list, methods table and QC
for one LC mode of a CLUES LC-HRMS study in the standard folder layout, built
from the Xcalibur SEQUENCE FILES.

Companion to LC-HRMS_parallel_msconvert_v2.4.ps1 (run by it; can also be run alone).
Python standard library only. RAW files are never opened here: they are only
listed (name, folder, size, modification time) so each sequence row can be
matched to its file. The driver converts them with msconvert, and reads one RAW
file per distinct method for the method reports.

Mapfile (same columns and sources as v2.3 and the original R scripts):
    File.Name   <- sequence "File Name" (the RAW file's actual name when Xcalibur renamed
                   a repeated name to name_yyyymmddhhmmss)
    Sample.ID   <- sequence "Sample ID"
    Batch       <- sequence "Comment"
    Sample_type <- sequence "Sample Name"
    Polarity    <- sequence "Instrument Method" (…pos… / …neg…), else the File Name.
                   NEVER row order (v2.3's sort-then-alternate split mislabels about half
                   the rows when file names contain pos/neg).
    Order       <- sequence order: CSVs by the batch number in their name, rows as listed.

Rules:
    - Every row of every top-level CSV in 3-Sequence_Files is used (Archive\\ is ignored).
    - Rows whose Sample Name is in --exclude-types are left out of the mapfiles.
    - Rows with no RAW file stay in the mapfiles and are reported (missing-files report).
    - Only RAW files listed in a sequence are converted. RAW files in Batch folders that
      no sequence lists are reported and not converted.
    - RAW files modified less than --min-age-minutes ago (still being acquired) are left
      for the next run.

Layout (one LC mode):
    <study>_<LC>\\1-Raw_Files\\Batch_*\\*.raw            MS1   -> 1a-<LC>_mzML
    <study>_<LC>\\1-Raw_Files\\Batch_*\\MSMS\\*.raw       MSMS  -> 1a-<LC>_mzML\\<LC>_MSMS
    <study>_<LC>\\3-Sequence_Files\\*.csv

Outputs (in --out-dir, normally <OutputDirectory>\\<LC>):
    <ID>_<LC>pos_sample_mapfile.txt, <ID>_<LC>neg_sample_mapfile.txt
                                         File.Name, Sample.ID, Batch, Sample_type (sequence order)
    <ID>_<LC>_sample_mapfile.txt         both polarities + Polarity, Seq_Order, Seq_File, Instrument_Method, RAW_Found
    <ID>_<LC>_sequence_check.tsv         every sequence row (status, RAW match, flags) + every unlisted RAW file
    <ID>_<LC>_conversion_manifest.tsv    RAW files to convert (RawPath, Kind, File.Name)
    <ID>_<LC>_methods.tsv                distinct methods + one representative RAW file each, and the
                                         injection volume from the sequence "Inj Vol" column
    <ID>_<LC>_mapfile_QC.txt             human-readable QC report
    <ID>_<LC>_mapfile_summary.json       machine-readable summary

Usage:
    python lc_sequence_mapfile.py --raw-dir <...\\1-Raw_Files> --seq-dir <...\\3-Sequence_Files>
        --out-dir <out> --study-id <ID> --lc-mode <HILIC|C18>
        [--exclude-types MSMS,PFAS-MSMS,AMAP,PFAS_Spike,Cal_Std] [--min-age-minutes 15]

Exit codes: 0 ok, 2 usage error, 3 no sequence rows found.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

VERSION = "2.4.1"

BATCH_DIR_RE = re.compile(r"^batch[_\- ]?(\d+)", re.I)
TS_SUFFIX_RE = re.compile(r"_(\d{14})$")          # Xcalibur rename of a repeated file name
CSV_BATCH_RE = re.compile(r"_(\d+)_")              # batch number in a sequence CSV name (as v2.3)
LC_RE = re.compile(r"(C18|HILIC)", re.I)
POL_WORD_RE = re.compile(r"(?<![a-z])(pos|neg)(?![a-z])|(?:C18|HILIC)(pos|neg)", re.I)

MAPFILE_CORE = ["File.Name", "Sample.ID", "Batch", "Sample_type"]
MAPFILE_EXTRA = ["Polarity", "Seq_Order", "Seq_File", "Instrument_Method", "RAW_Found"]
CHECK_COLS = ["Source", "Seq_Order", "Seq_File", "Seq_Row", "Seq_File_Name", "File.Name", "Sample.ID", "Batch",
              "Sample_type", "Polarity", "Instrument_Method", "Seq_Path", "Kind", "In_Mapfile", "RAW_Found",
              "Convert", "Status", "Flags", "RAW_RelPath", "RAW_Modified", "Inj_Vol"]


# ----------------------------------------------------------------------------
# file system (listing only; RAW files are never opened)
# ----------------------------------------------------------------------------
def discover(raw_dir):
    files = []
    for root, dirs, names in os.walk(raw_dir):
        dirs.sort()
        for nm in sorted(names):
            if not nm.lower().endswith(".raw"):
                continue
            p = os.path.join(root, nm)
            rel = os.path.relpath(p, raw_dir)
            parts = rel.split(os.sep)
            bm = BATCH_DIR_RE.match(parts[0]) if len(parts) > 1 else None
            if bm and len(parts) == 2:
                loc = "batch"
            elif bm and len(parts) == 3 and parts[1].lower() == "msms":
                loc = "batch/MSMS"
            else:
                loc = "outside_batch_folders"
            try:
                st = os.stat(p)
                size, mtime = st.st_size, st.st_mtime
            except OSError:
                size, mtime = -1, 0
            files.append(dict(path=p, rel=rel.replace(os.sep, "/"), base=os.path.splitext(nm)[0],
                              batch_folder=parts[0] if bm else "", batch_num=int(bm.group(1)) if bm else None,
                              location=loc, size=size, mtime=mtime))
    return files


def read_sequence(csv_path):
    """Xcalibur sequence export. Header = first line containing 'File Name' (line 2 after 'Bracket Type=')."""
    with open(csv_path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        lines = fh.read().splitlines()
    hdr = next((i for i, ln in enumerate(lines[:10]) if "File Name" in ln), None)
    if hdr is None:
        return []
    rows = list(csv.DictReader(lines[hdr:]))
    return [{(k or "").strip(): (v or "").strip() for k, v in r.items() if k} for r in rows
            if (r.get("File Name") or "").strip()]


def csv_sort_key(name):
    m = CSV_BATCH_RE.search(name)
    return (int(m.group(1)) if m else sys.maxsize, name)


def load_sequences(seq_dir):
    """[(csv name, row number in that csv (1-based), row dict)] in sequence order."""
    out = []
    if seq_dir and os.path.isdir(seq_dir):
        for nm in sorted((n for n in os.listdir(seq_dir) if n.lower().endswith(".csv")
                          and os.path.isfile(os.path.join(seq_dir, n))), key=csv_sort_key):
            for i, r in enumerate(read_sequence(os.path.join(seq_dir, nm)), 1):
                out.append((nm, i, r))
    return out


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def pol_from_text(s):
    if not s:
        return ""
    found = {(m.group(1) or m.group(2)).lower() for m in POL_WORD_RE.finditer(s)}
    return found.pop() if len(found) == 1 else ""


def lc_from_text(s):
    found = {m.group(1).upper() for m in LC_RE.finditer(s or "")}
    return found.pop() if len(found) == 1 else ""


def method_name(s):
    return os.path.splitext(os.path.basename((s or "").replace("\\", "/")))[0]


def path_parts(p):
    return [x for x in re.split(r"[\\/]+", p or "") if x]


def as_int(s):
    s = (s or "").strip()
    return int(s) if re.fullmatch(r"\d+", s) else None


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, float):
        return "%g" % v
    return str(v)


def inj_vol(s):
    """Sequence 'Inj Vol' as a string without trailing zeros ('7.50' -> '7.5'); '' when blank."""
    s = (s or "").strip()
    try:
        return "%g" % float(s)
    except ValueError:
        return s


def write_tsv(path, cols, data):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        w.writerow(cols)
        for x in data:
            w.writerow([fmt(x.get(c, "")) for c in cols])


# ----------------------------------------------------------------------------
# core logic (pure; unit-tested)
# ----------------------------------------------------------------------------
def build(files, seq_rows, lc_mode, exclude_types=(), min_age_minutes=15, now=None):
    """
    files    : discover() output (listing only)
    seq_rows : load_sequences() output, in sequence order
    Returns (rows, unlisted, extra): one record per sequence row, the RAW files no
    sequence row uses, and QC lists.
    """
    now = now or time.time()
    excl = {t.strip() for t in exclude_types if t and t.strip()}
    usable = [f for f in files if f["location"] != "outside_batch_folders"]
    exact, renamed = defaultdict(list), defaultdict(list)
    for f in usable:
        m = TS_SUFFIX_RE.search(f["base"])
        if m:
            renamed[f["base"][:m.start()].lower()].append(f)
        exact[f["base"].lower()].append(f)
    outside = defaultdict(list)
    for f in files:
        if f["location"] == "outside_batch_folders":
            outside[TS_SUFFIX_RE.sub("", f["base"]).lower()].append(f)

    used = set()
    name_csvs = defaultdict(set)
    for csvn, _, r in seq_rows:
        name_csvs[r["File Name"].lower()].add(csvn)

    rows = []
    for order, (csvn, rown, r) in enumerate(seq_rows, 1):
        fn = r["File Name"]
        meth = method_name(r.get("Instrument Method", ""))
        seq_path = r.get("Path", "")
        pp = path_parts(seq_path)
        flags = []
        # expected location from the sequence Path column (…\Batch_NN_x or …\Batch_NN_x\MSMS)
        exp_msms = bool(pp) and pp[-1].lower() == "msms"
        exp_folder = (pp[-2] if exp_msms and len(pp) > 1 else (pp[-1] if pp else "")).lower()

        # --- match the RAW file: exact name first, then Xcalibur-renamed copies; prefer the
        #     folder named in the sequence Path ---
        cands = [f for f in exact.get(fn.lower(), []) + renamed.get(fn.lower(), []) if f["path"] not in used]
        cands.sort(key=lambda f: (bool(TS_SUFFIX_RE.search(f["base"])) and f["base"].lower() != fn.lower(),
                                  f["base"].lower(), f["batch_folder"].lower() != exp_folder, f["rel"]))
        raw = cands[0] if cands else None
        if raw:
            used.add(raw["path"])
            if raw["base"].lower() != fn.lower():
                flags.append("xcalibur_renamed_file")
            if exp_folder and raw["batch_folder"].lower() != exp_folder:
                flags.append(f"in_folder({raw['batch_folder']})!=sequence_path({pp[-2] if exp_msms else pp[-1]})")
        if len(name_csvs[fn.lower()]) > 1:
            flags.append("file_name_in_more_than_one_csv")

        kind = "MSMS" if (exp_msms or (raw and raw["location"] == "batch/MSMS")
                          or (not pp and "MSMS" in meth.upper())) else "MS1"

        # --- polarity: Instrument Method, then File Name ---
        p_meth, p_name = pol_from_text(meth), pol_from_text(fn)
        pol = p_meth or p_name
        if p_meth and p_name and p_meth != p_name:
            flags.append(f"polarity_method({p_meth})!=file_name({p_name})")
        lc_meth = lc_from_text(meth)
        lc_mismatch = bool(lc_meth and lc_meth != lc_mode.upper())
        if lc_mismatch:
            flags.append(f"method_LC({lc_meth})!=study_LC({lc_mode})")

        batch = r.get("Comment", "")
        b_com = as_int(batch)
        if b_com is None and kind == "MS1":
            flags.append("comment_not_numeric")
        if raw and b_com is not None and raw["batch_num"] is not None and b_com != raw["batch_num"]:
            flags.append(f"comment_batch({b_com})!=folder_batch({raw['batch_num']})")

        status, convert = [], False
        if raw:
            age = (now - raw["mtime"]) / 60.0 if raw["mtime"] else 1e9
            if age < min_age_minutes:
                status.append(f"RAW modified {age:.0f} min ago (may still be acquiring); converted on a later run")
            else:
                convert = True
        else:
            o = outside.get(fn.lower())
            status.append("no RAW file in the Batch folders" + (f" (found only in {o[0]['rel']})" if o else ""))

        stype = r.get("Sample Name", "")
        in_map = kind == "MS1"
        if in_map and stype in excl:
            in_map = False
            status.append(f"Sample_type '{stype}' excluded (ExcludeSampleTypes)")
        if in_map and lc_mismatch:
            in_map = False
            status.append(f"method is {lc_meth}, study is {lc_mode}")
        if in_map and pol not in ("pos", "neg"):
            in_map = False
            status.append("polarity unknown from Instrument Method and File Name")

        rows.append({
            "Source": "sequence", "Seq_Order": order, "Seq_File": csvn, "Seq_Row": rown, "Seq_File_Name": fn,
            "File.Name": raw["base"] if raw else fn, "Sample.ID": r.get("Sample ID", ""), "Batch": batch,
            "Sample_type": stype, "Polarity": pol, "Instrument_Method": meth, "Seq_Path": seq_path, "Kind": kind,
            "In_Mapfile": int(in_map), "RAW_Found": int(bool(raw)), "Convert": int(convert),
            "Status": "; ".join(status), "Flags": ";".join(flags),
            "RAW_RelPath": raw["rel"] if raw else "", "RAW_Path": raw["path"] if raw else "",
            "RAW_Modified": dt.datetime.fromtimestamp(raw["mtime"]).strftime("%Y-%m-%d %H:%M:%S") if raw and raw["mtime"] else "",
            "_batch_folder": raw["batch_folder"] if raw else "", "Inj_Vol": inj_vol(r.get("Inj Vol", "")),
        })

    unlisted = []
    for f in files:
        if f["path"] in used:
            continue
        if f["location"] == "outside_batch_folders":
            why = "not in a Batch_*/ or Batch_*/MSMS/ folder"
        elif TS_SUFFIX_RE.sub("", f["base"]).lower() in name_csvs or f["base"].lower() in name_csvs:
            why = "another file with this name was used for the sequence row (duplicate copy)"
        else:
            why = "not listed in any sequence CSV"
        unlisted.append({"Source": "raw_not_used", "File.Name": f["base"], "Kind": "MSMS" if f["location"] == "batch/MSMS"
                         else ("MS1" if f["location"] == "batch" else ""), "Convert": 0, "In_Mapfile": 0,
                         "RAW_Found": 1, "Status": why, "RAW_RelPath": f["rel"],
                         "RAW_Modified": dt.datetime.fromtimestamp(f["mtime"]).strftime("%Y-%m-%d %H:%M:%S") if f["mtime"] else ""})

    mp = [r for r in rows if r["In_Mapfile"]]
    extra = dict(
        dup_mapfile_names=[(p, k, v) for p in ("pos", "neg")
                           for k, v in Counter(r["File.Name"] for r in mp if r["Polarity"] == p).items() if v > 1],
        dup_sample_ids=[(p, k, v) for p in ("pos", "neg")
                        for k, v in Counter(r["Sample.ID"] for r in mp if r["Polarity"] == p).items() if v > 1],
    )
    return rows, unlisted, extra


def methods_table(rows):
    """Distinct instrument methods (from the sequence) + the first listed RAW file that will be converted.

    InjVol is the method's injection volume from the sequence 'Inj Vol' column: the most common
    non-zero value over its rows (blanks are often run at 0). InjVolCounts lists every value with its
    count, most common first, e.g. '7.5 x1150; 0 x8'. Both are '' when the sequence has no Inj Vol."""
    meth, vols = {}, defaultdict(Counter)
    for r in rows:
        if not r["Instrument_Method"]:
            continue
        k = (r["Kind"], r["Instrument_Method"])
        e = meth.setdefault(k, dict(Method=r["Instrument_Method"], Category=r["Kind"], Polarity=r["Polarity"],
                                    Injections=0, SampleTypes=set(), Representative="", RepresentativeFile=""))
        e["Injections"] += 1
        if r.get("Inj_Vol"):
            vols[k][r["Inj_Vol"]] += 1
        if r["Sample_type"]:
            e["SampleTypes"].add(r["Sample_type"])
        if not e["Representative"] and r["Convert"]:
            e["Representative"], e["RepresentativeFile"] = r["RAW_Path"], r["File.Name"]
    out = []
    for k, e in meth.items():
        e["SampleTypes"] = "; ".join(sorted(e["SampleTypes"]))
        c = vols[k]
        ranked = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))
        nonzero = [v for v, _ in ranked if v not in ("0", "")]
        e["InjVol"] = nonzero[0] if nonzero else (ranked[0][0] if ranked else "")
        e["InjVolCounts"] = "; ".join(f"{v} x{n}" for v, n in ranked)
        out.append(e)
    return sorted(out, key=lambda e: (e["Category"], e["Method"]))


# ----------------------------------------------------------------------------
# QC report
# ----------------------------------------------------------------------------
def qc_report(rows, unlisted, extra, methods, study_id, lc_mode, raw_dir, seq_dir):
    L = []
    mp = [r for r in rows if r["In_Mapfile"]]
    conv = [r for r in rows if r["Convert"]]
    missing = [r for r in rows if not r["RAW_Found"]]
    deferred = [r for r in rows if r["RAW_Found"] and not r["Convert"]]
    csvs = list(dict.fromkeys(r["Seq_File"] for r in rows))
    L.append(f"Sequence mapfile QC - {study_id} {lc_mode}   (lc_sequence_mapfile.py v{VERSION}, "
             f"{dt.datetime.now():%Y-%m-%d %H:%M:%S})")
    L.append("=" * 78)
    L.append(f"Sequence folder: {seq_dir}")
    L.append(f"RAW folder:      {raw_dir}   (files listed only; never opened here)")
    L.append("")
    L.append(f"Sequence CSVs: {len(csvs)}   rows: {len(rows)}   (MS1 {sum(r['Kind'] == 'MS1' for r in rows)}, "
             f"MSMS {sum(r['Kind'] == 'MSMS' for r in rows)})")
    L.append(f"In mapfiles: {len(mp)}   pos {sum(r['Polarity'] == 'pos' for r in mp)}   "
             f"neg {sum(r['Polarity'] == 'neg' for r in mp)}   (of which no RAW file yet: {sum(not r['RAW_Found'] for r in mp)})")
    L.append(f"To convert: MS1 {sum(r['Kind'] == 'MS1' for r in conv)}   MSMS {sum(r['Kind'] == 'MSMS' for r in conv)}")
    L.append(f"Sequence rows with no RAW file: {len(missing)}   RAW still being written (later run): {len(deferred)}")
    L.append(f"RAW files not used (not converted): {len(unlisted)}")
    L.append("")

    warn = []
    if missing:
        warn.append(f"{len(missing)} sequence row(s) have no RAW file (kept in the mapfiles if mapped; "
                    "see the *_missing_files.txt reports after conversion)")
    nl = [u for u in unlisted if u["Status"] == "not listed in any sequence CSV"]
    if nl:
        warn.append(f"{len(nl)} RAW file(s) in Batch folders are not listed in any sequence CSV (not converted)")
    dup = [u for u in unlisted if u["Status"].startswith("another file")]
    if dup:
        warn.append(f"{len(dup)} duplicate RAW file(s) with a name already used (not converted)")
    unk = [r for r in rows if "polarity unknown" in r["Status"]]
    if unk:
        warn.append(f"{len(unk)} MS1 row(s) with unknown polarity (left out of the mapfiles)")
    for key, text in (("polarity_method", "row(s) whose method and file name give different polarities"),
                      ("method_LC", "row(s) acquired with the other LC mode's method (left out of the mapfiles)"),
                      ("comment_batch", "row(s) whose Comment batch differs from the Batch folder number"),
                      ("in_folder", "row(s) whose RAW file is in a different folder than the sequence Path"),
                      ("file_name_in_more_than_one_csv", "row(s) whose File Name is in more than one CSV")):
        n = sum(key in r["Flags"] for r in rows)
        if n:
            warn.append(f"{n} {text}")
    if extra["dup_mapfile_names"]:
        warn.append(f"{len(extra['dup_mapfile_names'])} File.Name value(s) repeated in a mapfile")
    if extra["dup_sample_ids"]:
        warn.append(f"{len(extra['dup_sample_ids'])} Sample.ID value(s) repeated in a mapfile (re-injections?)")
    L.append("WARNINGS: " + ("none" if not warn else ""))
    L += ["  - " + w for w in warn]
    L.append("")

    L.append("Sequence files (in mapfile order):")
    L.append(f"  {'csv':<36}{'rows':>5}{'MS1':>5}{'MSMS':>5}{'noRAW':>6}  {'Comment':<9}RAW folder(s)")
    for c in csvs:
        g = [r for r in rows if r["Seq_File"] == c]
        com = ",".join(sorted({r["Batch"] for r in g if r["Kind"] == "MS1"}, key=lambda x: (len(x), x)))
        fold = ",".join(sorted({r["_batch_folder"] for r in g if r["_batch_folder"]}))
        L.append(f"  {c:<36}{len(g):>5}{sum(r['Kind'] == 'MS1' for r in g):>5}{sum(r['Kind'] == 'MSMS' for r in g):>5}"
                 f"{sum(not r['RAW_Found'] for r in g):>6}  {com:<9}{fold}")
    L.append("")

    L.append("Sample types in mapfiles (pos / neg):")
    st = Counter((r["Sample_type"], r["Polarity"]) for r in mp)
    for t in sorted({k[0] for k in st}):
        L.append(f"  {t or '(blank)':<30}{st[(t, 'pos')]:>6}{st[(t, 'neg')]:>6}")
    ex = Counter(r["Sample_type"] for r in rows if "ExcludeSampleTypes" in r["Status"])
    if ex:
        L.append("  excluded by ExcludeSampleTypes: " + ", ".join(f"{k} ({v})" for k, v in sorted(ex.items())))
    L.append("")

    L.append("Instrument methods (from the sequence):")
    for e in methods:
        L.append(f"  {e['Category']:<5}{e['Polarity']:<5}{e['Method']:<50} n={e['Injections']:<5} "
                 f"inj {e.get('InjVol') or '?':<5} rep: {e['RepresentativeFile'] or '(no RAW file yet)'}")
    L.append("")

    def listing(title, items, limit=150):
        L.append(f"{title}: {len(items)}")
        for it in items[:limit]:
            L.append("  " + it)
        if len(items) > limit:
            L.append(f"  ... and {len(items) - limit} more (see the sequence check TSV)")
        L.append("")

    listing("Sequence rows with no RAW file", [f"{r['Seq_File']} row {r['Seq_Row']}: {r['Seq_File_Name']}  ({r['Status']})"
                                               for r in missing])
    listing("RAW files not converted", [f"{u['RAW_RelPath']}  -> {u['Status']}" for u in unlisted]
            + [f"{r['RAW_RelPath']}  -> {r['Status']}" for r in deferred])
    listing("Flagged sequence rows", [f"{r['Seq_File']} row {r['Seq_Row']}: {r['Seq_File_Name']}: {r['Flags']}"
                                      for r in rows if set(r["Flags"].split(";")) - {"", "xcalibur_renamed_file"}], 100)
    listing("Xcalibur-renamed files (name repeated in a sequence)",
            [f"{r['Seq_File_Name']} -> {r['File.Name']}" for r in rows if "xcalibur_renamed_file" in r["Flags"]], 50)
    listing("Repeated File.Name in a mapfile", [f"{p}: {k} x{v}" for p, k, v in extra["dup_mapfile_names"]], 50)
    listing("Repeated Sample.ID in a mapfile", [f"{p}: {k} x{v}" for p, k, v in extra["dup_sample_ids"]], 50)
    return L


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Sequence-based mapfiles for one LC mode (CLUES standard layout)")
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--seq-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--study-id", required=True)
    ap.add_argument("--lc-mode", required=True)
    ap.add_argument("--exclude-types", default="MSMS")
    ap.add_argument("--min-age-minutes", type=float, default=15)
    a = ap.parse_args(argv)

    seq_rows = load_sequences(a.seq_dir)
    if not seq_rows:
        print(f"ERROR: no sequence rows found in {a.seq_dir}")
        return 3
    files = discover(a.raw_dir) if os.path.isdir(a.raw_dir) else []
    os.makedirs(a.out_dir, exist_ok=True)
    pre = os.path.join(a.out_dir, f"{a.study_id}_{a.lc_mode}")

    rows, unlisted, extra = build(files, seq_rows, a.lc_mode, a.exclude_types.split(","), a.min_age_minutes)
    methods = methods_table(rows)
    mp = [r for r in rows if r["In_Mapfile"]]
    for pol in ("pos", "neg"):
        write_tsv(f"{pre}{pol}_sample_mapfile.txt", MAPFILE_CORE, [r for r in mp if r["Polarity"] == pol])
    write_tsv(pre + "_sample_mapfile.txt", MAPFILE_CORE + MAPFILE_EXTRA, mp)
    write_tsv(pre + "_sequence_check.tsv", CHECK_COLS, rows + unlisted)
    with open(pre + "_conversion_manifest.tsv", "w", encoding="utf-8", newline="") as fh:
        fh.write("RawPath\tKind\tFile.Name\n")
        for r in rows:
            if r["Convert"]:
                fh.write(f"{r['RAW_Path']}\t{r['Kind']}\t{r['File.Name']}\n")
    write_tsv(pre + "_methods.tsv", ["Method", "Category", "Polarity", "Injections", "SampleTypes",
                                     "RepresentativeFile", "Representative", "InjVol", "InjVolCounts"], methods)
    L = qc_report(rows, unlisted, extra, methods, a.study_id, a.lc_mode, a.raw_dir, a.seq_dir)
    with open(pre + "_mapfile_QC.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    with open(pre + "_mapfile_summary.json", "w", encoding="utf-8") as fh:
        json.dump(dict(version=VERSION, study_id=a.study_id, lc_mode=a.lc_mode, seq_dir=a.seq_dir, raw_dir=a.raw_dir,
                       generated=dt.datetime.now().isoformat(timespec="seconds"), sequence_rows=len(rows),
                       mapfile_pos=sum(r["Polarity"] == "pos" for r in mp), mapfile_neg=sum(r["Polarity"] == "neg" for r in mp),
                       convert_ms1=sum(r["Convert"] and r["Kind"] == "MS1" for r in rows),
                       convert_msms=sum(r["Convert"] and r["Kind"] == "MSMS" for r in rows),
                       rows_without_raw=sum(not r["RAW_Found"] for r in rows),
                       raw_not_used=[dict(raw=u["RAW_RelPath"], reason=u["Status"]) for u in unlisted]), fh, indent=2)
    end = next((i for i, ln in enumerate(L) if ln.startswith("Sequence files (")), 14)
    print("\n".join(L[:end]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
