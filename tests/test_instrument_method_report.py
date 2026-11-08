"""
Unit tests for the parsers in instrument_method_report.py (no RAW files, no fisher_py).
Run:  python -m unittest discover -s tests -v

Fixtures (tests/fixtures/): the instrument method texts of two CLUES DDA injections (C18, dual-column
system), as embedded in their RAW files: method 0 = LC (pos: ..._Ch1-5min_HRE_MSMS, neg:
..._Ch2-5min_HRE_MSMS), method 1 = MS (neg; mass list table cut to its first 3 of 884 rows).
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import instrument_method_report as imr  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8", newline="") as fh:
        return fh.read()


LC_POS = fixture("C18pos_Ch1_HRE_MSMS_method0_LC.txt")
LC_NEG = fixture("C18neg_Ch2_HRE_MSMS_method0_LC.txt")
MS_NEG = fixture("C18neg_Ch2_HRE_MSMS_method1_MS_masslist3rows.txt")
METH_POS = r"C:\Xcalibur\methods\Aria_Methods\5min_Methods-C18\251027_C18pos_Ch1-5min_HRE_MSMS.meth"
METH_NEG = r"C:\Xcalibur\methods\Aria_Methods\5min_Methods-C18\251027_C18neg_Ch2-5min_HRE_MSMS.meth"


class Gradient(unittest.TestCase):
    def test_binary_pump_neg(self):
        steps, n = imr.parse_lc_gradient(LC_NEG)
        self.assertEqual((n, len(steps)), (6, 6))
        self.assertEqual([(s["start_min"], s["duration_min"], s["flow_ml_min"], s["type"]) for s in steps],
                         [(0.0, 0.1, 0.45, "Step"), (0.1, 3.4, 0.45, "Ramp"), (3.5, 2.0, 0.45, "Step"),
                          (5.5, 2.0, 0.8, "Step"), (7.5, 0.5, 0.45, "Ramp"), (8.0, 2.0, 0.45, "Step")])
        self.assertEqual([s["percent"] for s in steps][:2], [{"A1": 10.0, "B1": 90.0}, {"A1": 100.0, "B1": 0.0}])
        self.assertEqual([s["flow_ramp"] for s in steps], [False, False, False, False, True, False])

    def test_binary_pump_pos(self):
        steps, n = imr.parse_lc_gradient(LC_POS)
        self.assertEqual((n, len(steps)), (7, 7))
        self.assertEqual([s["percent"]["A1"] for s in steps], [5.0, 20.0, 100.0, 100.0, 100.0, 5.0, 5.0])
        self.assertEqual({s["flow_ml_min"] for s in steps}, {0.5, 0.8})

    def test_quaternary_pump(self):
        text = ("Step:  1     Start:  0.00 min     Time:   1.00 min\r\nFlow Rate:  0.300 ml/min\r\n"
                "Grad Type: Step\r\n%A:  95.0  %B:   5.0  %C   0.0  %D   0.0\r\n")
        steps, n = imr.parse_lc_gradient(text)
        self.assertEqual((n, len(steps)), (1, 1))
        self.assertEqual(steps[0]["percent"], {"A": 95.0, "B": 5.0, "C": 0.0, "D": 0.0})

    def test_unreadable_step_is_counted(self):
        text = LC_NEG.replace("%A1: 10.00    %B1: 90.00", "composition missing", 1)
        steps, n = imr.parse_lc_gradient(text)
        self.assertEqual((n, len(steps)), (6, 5))
        self.assertTrue(any("WARNING: 6 gradient step(s)" in ln for ln in imr.format_lc_method(text, METH_NEG)))


class ColumnSetup(unittest.TestCase):
    def test_dual_column_neg(self):
        header = imr.parse_lc_header(LC_NEG)
        self.assertEqual((header["Solvent A1"], header["Solvent B1"]), ("95:5 Acetonitrile/water", "N/A"))
        steps, _ = imr.parse_lc_gradient(LC_NEG)
        s = imr.lc_column_setup(header, steps, METH_NEG)
        self.assertEqual((s["channel"], s["data_window_start_min"], s["data_window_end_min"], s["lc_program_min"],
                          s["dual_column"]), (2, 0.0, 5.0, 10.0, True))
        self.assertIn("0.00-5.00 min", s["description"])
        self.assertIn("From 5.00 to 10.00 min this column is washed", s["description"])

    def test_channel_1_pos(self):
        header = imr.parse_lc_header(LC_POS)
        steps, _ = imr.parse_lc_gradient(LC_POS)
        self.assertEqual(imr.lc_column_setup(header, steps, METH_POS)["channel"], 1)

    def test_no_channel_in_name(self):
        header = imr.parse_lc_header(LC_NEG)
        steps, _ = imr.parse_lc_gradient(LC_NEG)
        s = imr.lc_column_setup(header, steps, r"C:\methods\plain_method.meth")
        self.assertEqual((s["channel"], s["dual_column"], s["description"]), (None, False, None))


class Json(unittest.TestCase):
    def test_lc_front_end(self):
        lc = imr.lc_front_end_json(LC_NEG, METH_NEG)
        self.assertEqual(lc["autosampler"]["Draw Speed"], "5.000 ul/s")
        self.assertEqual(lc["column_compartment"]["Temperature"], "30 Cdeg")
        self.assertEqual(len(lc["gradient"]), 6)

    def test_ms_sections(self):
        secs = {s["section"]: s for s in imr.ms_method_json(MS_NEG)}
        dd = secs["Scan ddMSnScan"]["groups"][0]["settings"]
        self.assertEqual((dd["Isolation Window (m/z)"], dd["HCD Collision Energies (%)"], dd["Orbitrap Resolution"]),
                         ("1", "20,40,60", "15000"))
        self.assertEqual(secs["Scan MasterScan"]["groups"][0]["settings"]["Orbitrap Resolution"], "60000")
        ml = secs["Mass List"]["groups"][0]["mass_list"]
        self.assertEqual((ml["columns"], ml["n_rows"]), (["CompoundName", "m/z", "t start (min)", "t stop (min)"], 3))

    def test_quick_reference_lc(self):
        lc = imr.lc_front_end_json(LC_NEG, METH_NEG)
        qr = dict(imr.quick_reference(LC_NEG + "\n" + MS_NEG, [LC_NEG, MS_NEG], "LC", lc))
        lcq = dict(qr["LC Parameters"])
        self.assertEqual((lcq["Flow Rate, separation (mL/min)"], lcq["MS Data Window (min)"], lcq["LC Program (min)"],
                          lcq["Column Channel"]), ("0.450", "0.00-5.00", "10.00", "2 (dual-column)"))
        self.assertEqual(dict(qr["MS Scan Parameters"])["Polarity"], "Negative")


class SolventsAndInjectionVolume(unittest.TestCase):
    def test_na_solvent_replaced_with_channel_default(self):
        lc = imr.lc_front_end_json(LC_NEG, METH_NEG)        # C18neg fixture: Solvent B1 N/A
        self.assertEqual(lc["header"]["Solvent B1"], imr.DEFAULT_SOLVENTS[("C18", 2)]["Solvent B1"])
        self.assertEqual(lc["solvent_defaults_applied"]["Solvent B1"]["method_value"], "N/A")
        self.assertEqual(list(lc["header"])[:3], ["Column", "Solvent A1", "Solvent B1"])
        text = "\n".join(imr.format_lc_method(LC_NEG, METH_NEG))
        self.assertIn("[default for C18 channel 2; method file: N/A]", text)

    def test_solvent_in_method_kept(self):
        lc = imr.lc_front_end_json(LC_POS, METH_POS)
        self.assertEqual(lc["solvent_defaults_applied"], {})
        self.assertEqual(lc["header"]["Solvent B1"], "0.1% FA in water")

    def test_no_default_without_mode_or_channel(self):
        lc = imr.lc_front_end_json(LC_NEG, r"C:\methods\some_method.meth")
        self.assertEqual((lc["header"]["Solvent B1"], lc["solvent_defaults_applied"]), ("N/A", {}))
        self.assertEqual(imr.lc_mode_and_channel(METH_POS), ("C18", 1))
        self.assertEqual(imr.lc_mode_and_channel("260702_HILICneg_Ch2-5min"), ("HILIC", 2))

    def test_injection_volume_from_sequence(self):
        lc = imr.lc_front_end_json(LC_NEG, METH_NEG, 10.0)
        self.assertEqual((lc["injection_volume_ul"], lc["injection_volume_source"]), (10.0, "sequence"))
        qr = dict(imr.quick_reference(LC_NEG + "\n" + MS_NEG, [LC_NEG, MS_NEG], "LC", lc))
        lcq = dict(qr["LC Parameters"])
        self.assertEqual(lcq["Injection Volume (uL)"], "10 (sequence)")
        self.assertEqual(lcq["Solvent B"], imr.DEFAULT_SOLVENTS[("C18", 2)]["Solvent B1"])
        self.assertIn("Injection Volume     10 uL   [from the sequence]",
                      "\n".join(imr.format_lc_method(LC_NEG, METH_NEG, 10.0)))
        lc0 = imr.lc_front_end_json(LC_NEG, METH_NEG)
        self.assertNotIn("Injection Volume (uL)", dict(dict(imr.quick_reference(LC_NEG, [LC_NEG], "LC", lc0))["LC Parameters"]))


class Summary(unittest.TestCase):
    def test_summary_pairs_channels(self):
        with tempfile.TemporaryDirectory() as d:
            tsv = os.path.join(d, "S_C18_methods.tsv")
            with open(tsv, "w", encoding="utf-8") as fh:
                fh.write("Method\tCategory\tPolarity\tInjections\tSampleTypes\tRepresentativeFile\tRepresentative"
                         "\tInjVol\tInjVolCounts\n"
                         "M_C18pos_Ch1-5min\tMS1\tpos\t10\tBlank; Study_Sample\tf1\tX:\\f1.raw\t7.5\t7.5 x8; 0 x2\n"
                         "M_C18neg_Ch2-5min\tMS1\tneg\t10\tBlank; Study_Sample\tf2\tX:\\f2.raw\n"
                         "M_C18neg_Ch2-5min_HRE_MSMS\tMSMS\tneg\t2\tMSMS\t\t\n")
            # neg: no method path in the report (sample information not readable) -> channel from the table
            for meth, text, path in (("M_C18pos_Ch1-5min", LC_POS, "M_C18pos_Ch1-5min.meth"),
                                     ("M_C18neg_Ch2-5min", LC_NEG, None)):
                with open(os.path.join(d, f"S_{meth}_method_report.json"), "w", encoding="utf-8") as fh:
                    json.dump({"lc": imr.lc_front_end_json(text, path)}, fh)
            out = imr.write_method_summary(tsv, d, "S", "C18")
            with open(out, encoding="utf-8") as fh:
                s = json.load(fh)
        self.assertEqual(os.path.basename(out), "S_C18_method_summary.json")
        self.assertEqual(s["n_methods"], {"total": 3, "MS1": 2, "MSMS": 1, "with_report": 2})
        self.assertTrue(s["lc_system"]["dual_column"])
        self.assertEqual(sorted(s["lc_system"]["channels"]), ["1", "2"])
        self.assertIn("channel 1: M_C18pos_Ch1-5min (pos)", s["lc_system"]["description"])
        self.assertIsNone(s["methods"][2]["report"])
        self.assertEqual((s["methods"][0]["injection_volume_ul"], s["methods"][0]["injection_volume_counts"]),
                         (7.5, "7.5 x8; 0 x2"))
        self.assertIsNone(s["methods"][1]["injection_volume_ul"])
        self.assertEqual(s["methods"][1]["report"]["lc"]["column_setup"]["channel_from"], "methods table")


if __name__ == "__main__":
    unittest.main()
