# mapfile_crosscheck.py
# Cross-check a sequence-derived sample mapfile against the metadata embedded in
# the actual Thermo .raw files. Each raw file's sample info (Sample ID, Comment,
# Sample Name) is written at acquisition time, so it is immune to sequence-CSV
# export mistakes (mis-saved / mis-named / clobbered exports). This builds a
# raw-derived mapfile and a discrepancy + batch-order report.
#
# Usage:
#   python mapfile_crosscheck.py <raw_input> <sequence_mapfile> <output_prefix>
#
#     <raw_input>        directory holding Batch_* subfolders with .raw files,
#                        OR a text file listing .raw paths (one per line)
#     <sequence_mapfile> tab-delimited mapfile built from the sequence CSVs
#                        (columns include File.Name, Sample.ID, Batch, Sample_type)
#     <output_prefix>    output path prefix; writes:
#                          <prefix>_mapfile_from_raw.txt   (raw-derived, sorted by File.Name)
#                          <prefix>_mapfile_crosscheck.txt (discrepancy + order report)
#
# Requires: pip install fisher_py

import sys
import os
import re
import csv
from fisher_py import RawFile


def batch_folder_of(path):
    """Nearest ancestor directory whose name starts with 'Batch'."""
    p = os.path.dirname(os.path.abspath(path))
    while True:
        name = os.path.basename(p)
        if re.match(r'(?i)^batch', name):
            return name
        parent = os.path.dirname(p)
        if parent == p:
            return ""
        p = parent


def num(s):
    m = re.search(r'\d+', s or "")
    return int(m.group(0)) if m else None


def collect_raw(inp):
    if os.path.isdir(inp):
        out = []
        for root, _, files in os.walk(inp):
            for f in files:
                if f.lower().endswith(".raw"):
                    out.append(os.path.join(root, f))
        return out
    with open(inp, encoding="utf-8", errors="replace") as fh:
        return [ln.strip().strip('"') for ln in fh
                if ln.strip() and ln.strip().strip('"').lower().endswith(".raw")]


def read_raw_rows(paths):
    rows = {}
    errs = 0
    for path in paths:
        base = os.path.splitext(os.path.basename(path))[0]
        bf = batch_folder_of(path)
        try:
            si = RawFile(path)._raw_file_access.sample_information
            sid = (si.sample_id or "").strip()
            batch = str(si.comment).strip() if si.comment not in (None, "") else ""
            stype = (si.sample_name or "").strip()
        except Exception:
            sid = batch = stype = ""
            errs += 1
        fb = num(bf)
        rows[base] = dict(file=base, sid=sid, batch=batch, stype=stype,
                          folder=bf, folderbatch=(str(fb) if fb is not None else ""))
    return rows, errs


def read_seq_mapfile(path):
    rows = []
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        rdr = csv.reader(fh, delimiter="\t")
        header = next(rdr, None)
        idx = {name.strip(): i for i, name in enumerate(header)} if header else {}

        def col(r, name):
            i = idx.get(name)
            return r[i].strip() if (i is not None and i < len(r)) else ""

        for r in rdr:
            if not r or not any(c.strip() for c in r):
                continue
            fn = col(r, "File.Name")
            base = os.path.splitext(os.path.basename(fn))[0]
            rows.append(dict(file=base, sid=col(r, "Sample.ID"),
                             batch=col(r, "Batch"), stype=col(r, "Sample_type")))
    return rows


def main():
    if len(sys.argv) < 4:
        print("Usage: python mapfile_crosscheck.py <raw_input> <sequence_mapfile> <output_prefix>")
        sys.exit(2)
    raw_input, seq_map, prefix = sys.argv[1], sys.argv[2], sys.argv[3]

    raw_paths = collect_raw(raw_input)
    raw_rows, errs = read_raw_rows(raw_paths)

    out_dir = os.path.dirname(os.path.abspath(prefix))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # --- raw-derived mapfile, sorted by File.Name ---
    raw_out = prefix + "_mapfile_from_raw.txt"
    with open(raw_out, "w", encoding="utf-8", newline="") as fh:
        fh.write("File.Name\tSample.ID\tBatch\tSample_type\tBatchFolder\tFolderBatch\n")
        for base in sorted(raw_rows):
            r = raw_rows[base]
            fh.write(f"{r['file']}\t{r['sid']}\t{r['batch']}\t{r['stype']}\t{r['folder']}\t{r['folderbatch']}\n")

    # --- read sequence-derived mapfile ---
    seq_rows = read_seq_mapfile(seq_map) if os.path.exists(seq_map) else []
    seq_by_file = {}
    dup_files = set()
    for r in seq_rows:
        if r["file"] in seq_by_file:
            dup_files.add(r["file"])
        else:
            seq_by_file[r["file"]] = r

    raw_files = set(raw_rows)
    seq_files = set(seq_by_file)
    missing_from_seq = sorted(raw_files - seq_files)
    extra_in_seq = sorted(seq_files - raw_files)
    common = sorted(raw_files & seq_files)

    batch_mismatch = []
    for f in common:
        sb, rb, fb = seq_by_file[f]["batch"], raw_rows[f]["batch"], raw_rows[f]["folderbatch"]
        if num(sb) is not None and num(rb) is not None and num(sb) != num(rb):
            batch_mismatch.append((f, sb, rb, fb))

    # --- batch-order check on the sequence mapfile, in filename-sorted order ---
    order_issues = []
    prev, prev_file = None, None
    for r in sorted(seq_rows, key=lambda r: r["file"]):
        b = num(r["batch"])
        if b is None:
            continue
        if prev is not None and b < prev:
            order_issues.append((prev_file, prev, r["file"], b))
        prev, prev_file = b, r["file"]

    cc = prefix + "_mapfile_crosscheck.txt"
    with open(cc, "w", encoding="utf-8", newline="") as fh:
        w = fh.write
        w("# Mapfile cross-check: sequence-derived mapfile vs. raw-file metadata\n")
        w(f"# Sequence mapfile : {seq_map}\n")
        w(f"# Raw files scanned: {len(raw_rows)} ({errs} read errors)\n")
        w(f"# Sequence rows    : {len(seq_rows)} ({len(seq_files)} unique files)\n#\n")
        w("## SUMMARY\n")
        w(f"  Files in raw but MISSING from sequence mapfile : {len(missing_from_seq)}\n")
        w(f"  Files in sequence mapfile with NO raw file     : {len(extra_in_seq)}\n")
        w(f"  Batch label MISMATCH (sequence vs raw)         : {len(batch_mismatch)}\n")
        w(f"  Duplicate File.Name in sequence mapfile        : {len(dup_files)}\n")
        w(f"  Batch out-of-order inversions (by filename)    : {len(order_issues)}\n\n")

        def section(title, lines):
            w(f"## {title} ({len(lines)})\n")
            for ln in lines:
                w(f"  {ln}\n")
            if not lines:
                w("  (none)\n")
            w("\n")

        section("MISSING FROM SEQUENCE MAPFILE (present in raw data)",
                [f"{f}   raw Batch={raw_rows[f]['batch']}  folder={raw_rows[f]['folder']}"
                 for f in missing_from_seq])
        section("IN SEQUENCE MAPFILE BUT NO MATCHING RAW FILE", extra_in_seq)
        section("BATCH MISMATCH  (file: sequence -> raw [folder])",
                [f"{f}: {sb} -> {rb} [{fb}]" for (f, sb, rb, fb) in batch_mismatch])
        section("DUPLICATE File.Name IN SEQUENCE MAPFILE", sorted(dup_files))
        section("BATCH ORDER INVERSIONS (sequence mapfile sorted by filename)",
                [f"after {pf} (batch {pb}), {cf} has batch {cb}"
                 for (pf, pb, cf, cb) in order_issues])

    print(f"Raw-derived mapfile: {raw_out}")
    print(f"Cross-check report : {cc}")
    print(f"SUMMARY  missing_from_seq={len(missing_from_seq)}  extra_in_seq={len(extra_in_seq)}  "
          f"batch_mismatch={len(batch_mismatch)}  dup={len(dup_files)}  order_inversions={len(order_issues)}")


if __name__ == "__main__":
    main()
