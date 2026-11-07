"""
Unit tests for lc_sequence_mapfile.build (pure logic; no RAW files, no network).
Run:  python -m unittest discover -s tests -v      (from the LC-HRMS_v2.4 folder)
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lc_sequence_mapfile as sm  # noqa: E402

NOW = time.time()
OLD = NOW - 24 * 3600
P = "E:\\Projects\\S_HILIC\\1-Raw_Files\\"


def raw(rel, mtime=OLD):
    parts = rel.split("/")
    bm = sm.BATCH_DIR_RE.match(parts[0]) if len(parts) > 1 else None
    loc = ("batch" if bm and len(parts) == 2 else
           "batch/MSMS" if bm and len(parts) == 3 and parts[1].lower() == "msms" else "outside_batch_folders")
    return dict(path="X:/" + rel, rel=rel, base=os.path.splitext(parts[-1])[0], batch_folder=parts[0] if bm else "",
                batch_num=int(bm.group(1)) if bm else None, location=loc, size=1, mtime=mtime)


def row(fn, sid="S", stype="Study_Sample", comment="1", method="260702_HILICpos_Ch1-5min", path=P + "Batch_01",
        csvn="S_01_260820_HILIC.csv"):
    return (csvn, 0, {"File Name": fn, "Sample ID": sid, "Comment": comment, "Sample Name": stype,
                      "Instrument Method": "C:\\Xcalibur\\methods\\" + method, "Path": path})


def run(files, seq, **kw):
    seq = [(c, i + 1, r) for i, (c, _, r) in enumerate(seq)]
    rows, unlisted, extra = sm.build(files, seq, "HILIC", now=NOW, **kw)
    return rows, {u["RAW_RelPath"]: u for u in unlisted}, extra


class PolarityAndOrder(unittest.TestCase):
    def test_polarity_from_method_not_row_order(self):
        # rows listed neg, neg, pos, pos: a row-parity split would mislabel half of them
        seq = [row("N_HILICneg_001", method="m_HILICneg_Ch2"), row("N_HILICneg_002", method="m_HILICneg_Ch2"),
               row("N_HILICpos_001", method="m_HILICpos_Ch1"), row("N_HILICpos_002", method="m_HILICpos_Ch1")]
        rows, _, _ = run([], seq)
        self.assertEqual([r["Polarity"] for r in rows], ["neg", "neg", "pos", "pos"])
        self.assertTrue(all(r["In_Mapfile"] for r in rows))

    def test_file_name_fallback_and_disagreement_flag(self):
        rows, _, _ = run([], [row("N_HILICneg_003", method="custom_method"),
                              row("N_HILICneg_004", method="m_HILICpos_Ch1"),
                              row("N_mystery_005", method="custom_method")])
        self.assertEqual(rows[0]["Polarity"], "neg")
        self.assertIn("polarity_method(pos)!=file_name(neg)", rows[1]["Flags"])
        self.assertEqual(rows[1]["Polarity"], "pos")
        self.assertEqual(rows[2]["In_Mapfile"], 0)
        self.assertIn("polarity unknown", rows[2]["Status"])

    def test_sequence_order_and_csv_batch_order(self):
        seq = [row("B_x_pos", csvn="S_10_261001_HILIC.csv"), row("A_x_pos", csvn="S_02_260901_HILIC.csv")]
        # load_sequences sorts CSVs by batch number; build keeps the given order
        self.assertLess(sm.csv_sort_key("S_02_260901_HILIC.csv"), sm.csv_sort_key("S_10_261001_HILIC.csv"))
        rows, _, _ = run([], seq)
        self.assertEqual([r["Seq_Order"] for r in rows], [1, 2])


class Matching(unittest.TestCase):
    def test_match_and_convert(self):
        f = raw("Batch_01/N_HILICpos_001.raw")
        rows, unl, _ = run([f], [row("N_HILICpos_001")])
        self.assertEqual((rows[0]["RAW_Found"], rows[0]["Convert"], rows[0]["In_Mapfile"]), (1, 1, 1))
        self.assertEqual(unl, {})

    def test_row_without_raw_kept_in_mapfile(self):
        rows, _, _ = run([], [row("N_HILICpos_009")])
        self.assertEqual((rows[0]["RAW_Found"], rows[0]["Convert"], rows[0]["In_Mapfile"]), (0, 0, 1))
        self.assertIn("no RAW file", rows[0]["Status"])

    def test_unlisted_raw_not_converted(self):
        a, b = raw("Batch_01/N_HILICpos_001.raw"), raw("Batch_01_260818/S_aborted_pos_001.raw")
        rows, unl, _ = run([a, b], [row("N_HILICpos_001")])
        self.assertEqual(unl[b["rel"]]["Status"], "not listed in any sequence CSV")
        self.assertEqual(unl[b["rel"]]["Convert"], 0)

    def test_outside_batch_not_used(self):
        t = raw("Temp/N_HILICpos_001.raw")
        rows, unl, _ = run([t], [row("N_HILICpos_001")])
        self.assertEqual(rows[0]["RAW_Found"], 0)
        self.assertIn("found only in Temp/", rows[0]["Status"])
        self.assertIn("not in a Batch", unl[t["rel"]]["Status"])

    def test_xcalibur_rename_assigned_to_second_row(self):
        a, b = raw("Batch_01/N_pos_198.raw"), raw("Batch_01/N_pos_198_20260821005445.raw")
        rows, unl, _ = run([b, a], [row("N_pos_198", sid="Q1"), row("N_pos_198", sid="Q1")])
        self.assertEqual([r["File.Name"] for r in rows], ["N_pos_198", "N_pos_198_20260821005445"])
        self.assertIn("xcalibur_renamed_file", rows[1]["Flags"])
        self.assertEqual(unl, {})

    def test_duplicate_copy_prefers_sequence_path_folder(self):
        a, b = raw("Batch_02/N_pos_003.raw"), raw("Batch_01/N_pos_003.raw")
        rows, unl, _ = run([a, b], [row("N_pos_003", path=P + "Batch_01")])
        self.assertEqual(rows[0]["RAW_RelPath"], "Batch_01/N_pos_003.raw")
        self.assertIn("duplicate copy", unl[a["rel"]]["Status"])

    def test_folder_mismatch_and_comment_batch_flags(self):
        a = raw("Batch_02/N_pos_004.raw")
        rows, _, _ = run([a], [row("N_pos_004", comment="1", path=P + "Batch_01")])
        self.assertIn("in_folder(Batch_02)!=sequence_path(Batch_01)", rows[0]["Flags"])
        self.assertIn("comment_batch(1)!=folder_batch(2)", rows[0]["Flags"])

    def test_recent_raw_deferred(self):
        a = raw("Batch_01/N_pos_001.raw", mtime=NOW - 60)
        rows, _, _ = run([a], [row("N_pos_001")])
        self.assertEqual((rows[0]["RAW_Found"], rows[0]["Convert"], rows[0]["In_Mapfile"]), (1, 0, 1))


class KindsAndExclusions(unittest.TestCase):
    def test_msms_rows_converted_not_mapped(self):
        m = raw("Batch_01/MSMS/N_pos_A_MSMS.raw")
        rows, _, _ = run([m], [row("N_pos_A_MSMS", stype="MSMS", method="m_HILICpos_HRE_MSMS", path=P + "Batch_01\\MSMS")])
        self.assertEqual((rows[0]["Kind"], rows[0]["Convert"], rows[0]["In_Mapfile"]), ("MSMS", 1, 0))
        self.assertEqual(rows[0]["Flags"], "")

    def test_excluded_type_converted_not_mapped(self):
        a = raw("Batch_01/N_pos_cal.raw")
        rows, _, _ = run([a], [row("N_pos_cal", stype="Cal_Std")], exclude_types=["MSMS", "Cal_Std"])
        self.assertEqual((rows[0]["Convert"], rows[0]["In_Mapfile"]), (1, 0))

    def test_other_lc_method_kept_out(self):
        rows, _, _ = run([], [row("N_pos_x", method="250101_C18pos_Ch1")])
        self.assertEqual(rows[0]["In_Mapfile"], 0)
        self.assertIn("method_LC(C18)!=study_LC(HILIC)", rows[0]["Flags"])

    def test_methods_table_representative(self):
        a = raw("Batch_01/N_HILICpos_002.raw")
        rows, _, _ = run([a], [row("N_HILICpos_001"), row("N_HILICpos_002")])
        mt = sm.methods_table(rows)
        self.assertEqual(len(mt), 1)
        self.assertEqual((mt[0]["Injections"], mt[0]["RepresentativeFile"]), (2, "N_HILICpos_002"))


class Helpers(unittest.TestCase):
    def test_text_helpers(self):
        self.assertEqual(sm.pol_from_text("260702_HILICneg_Ch2-5min"), "neg")
        self.assertEqual(sm.pol_from_text("N260101_CLU0000_C18pos_001"), "pos")
        self.assertEqual(sm.pol_from_text("Positive_and_negative"), "")
        self.assertEqual(sm.lc_from_text("C18_to_HILIC"), "")
        self.assertEqual(sm.method_name("C:\\Xcalibur\\methods\\A\\260702_HILICneg.meth"), "260702_HILICneg")

    def test_read_sequence_header_detection(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "S_01_x.csv")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("Bracket Type=4,,,\nSample Type,File Name,Sample ID,Comment\nUnknown,F1,ID1,1\n,,,\n")
            self.assertEqual([r["File Name"] for r in sm.read_sequence(p)], ["F1"])


if __name__ == "__main__":
    unittest.main()
