#!/usr/bin/env python3
"""Deterministic tests for claim-auditor's script. Standard library only; exits 0 on success, 1 on failure.

Run: python3 evals/claim-auditor/test_claim_audit.py
"""

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent.parent / "claim-auditor" / "scripts" / "claim_audit.py"
sys.path.insert(0, str(SCRIPT.parent))
import claim_audit  # noqa: E402


def make_repo(files):
    root = Path(tempfile.mkdtemp(prefix="claim_audit_"))
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def audit(files):
    return claim_audit.audit(make_repo(files))


def checks(report, check):
    return [f for f in report["findings"] if f["check"] == check]


class TypedLiteral(unittest.TestCase):
    def test_flags_typed_metric_and_print(self):
        r = audit({"app.py": 'import streamlit as st\nst.metric("Savings", "63.9%")\nprint("Savings: 93.7%")\n'})
        self.assertEqual(len(checks(r, "typed-literal")), 2)

    def test_computed_values_are_not_flagged(self):
        r = audit({"app.py": 'import streamlit as st\npct = 1.0\nst.metric("Savings", f"{pct:.1f}%")\nprint(f"Savings: {pct}%")\n'})
        self.assertEqual(checks(r, "typed-literal"), [])

    def test_assignment_to_metric_named_variable_and_dict(self):
        r = audit({"a.py": 'savings = "47%"\nname = "47%"\nstats = {"savings": "93%", "title": "93%"}\n'})
        lines = sorted(f["line"] for f in checks(r, "typed-literal"))
        self.assertEqual(lines, [1, 3])

    def test_ignores_docstrings_css_and_100_percent(self):
        src = '"""Cuts cost by 93%."""\ndef f():\n    """Also 50%."""\nimport streamlit as st\nst.markdown("<div style=\'width: 80%\'>x</div>")\nprint("100% done")\n'
        self.assertEqual(checks(audit({"a.py": src}), "typed-literal"), [])

    def test_quoted_marker_on_the_line_acknowledges_a_figure(self):
        src = (
            "import streamlit as st\n"
            'st.metric("Reported", "63.9%")  # claim-audit: quoted\n'
            'st.metric("Other", "54.1%")\n'
        )
        found = checks(audit({"a.py": src}), "typed-literal")
        self.assertEqual([f["line"] for f in found], [3])

    def test_text_that_credits_someone_else_is_accepted_but_measured_is_not(self):
        src = (
            "import streamlit as st\n"
            'st.markdown("The project reports roughly 30-60% fewer tokens.")\n'
            'st.markdown("According to the vendor: 47% savings")\n'
            'st.markdown("Measured saving: 93.7%")\n'
        )
        found = checks(audit({"a.py": src}), "typed-literal")
        self.assertEqual([f["line"] for f in found], [4])

    def test_range_is_reported(self):
        r = audit({"a.py": 'print("Reduce costs by 50-90% today")\n'})
        self.assertEqual(len(checks(r, "typed-literal")), 1)


class LibraryNotImported(unittest.TestCase):
    DEMO = 'print("""\nfrom headroom.integrations import HeadroomChatModel\n""")\n'

    def test_flags_library_only_used_inside_a_string(self):
        r = audit({"requirements.txt": "headroom-ai[all]>=0.2\nopenai\n", "demo.py": self.DEMO})
        found = checks(r, "library-not-imported")
        self.assertEqual(len(found), 1)
        self.assertIn("headroom-ai", found[0]["evidence"])

    def test_not_flagged_when_really_imported(self):
        r = audit({"requirements.txt": "headroom-ai[all]\n", "demo.py": "import headroom\n" + self.DEMO})
        self.assertEqual(checks(r, "library-not-imported"), [])

    def test_package_name_differs_from_module_name(self):
        files = {
            "requirements.txt": "pillow>=10\ntoonify>=1.4  # compact format\npython-dotenv\n",
            "a.py": 'from PIL import Image\nfrom toon import encode\nfrom dotenv import load_dotenv\nprint("Run toonify_demo.py")\n',
        }
        self.assertEqual(checks(audit(files), "library-not-imported"), [])

    def test_bare_mention_or_tool_package_is_not_flagged(self):
        files = {"requirements.txt": "somelib\npytest\n", "a.py": 'print("somelib is great")\nprint("pip install somelib")\n'}
        self.assertEqual(checks(audit(files), "library-not-imported"), [])


class TokenEstimate(unittest.TestCase):
    def test_len_div_4_is_flagged_others_are_not(self):
        r = audit({"a.py": "t = 'x'\na = len(t) // 4\nb = len(t) / 4\nc = len(t) // 3\nd = 8 // 4\n"})
        self.assertEqual(sorted(f["line"] for f in checks(r, "token-estimate")), [2, 3])


class MixedLabels(unittest.TestCase):
    def test_same_number_called_token_and_size(self):
        r = audit({"README.md": "- 63.9% average token reduction\n\nLater:\n- 63.9% average size reduction vs JSON\n"})
        self.assertEqual(len(checks(r, "mixed-labels")), 1)

    def test_consistent_labels_or_ambiguous_lines_are_not_flagged(self):
        r = audit({"README.md": "- 54.1% token reduction\n- 54.1% fewer tokens\n- 40% token and size reduction\n- 40% size reduction\n"})
        self.assertEqual(checks(r, "mixed-labels"), [])


class UnsourcedFigure(unittest.TestCase):
    def test_bare_figure_is_noted(self):
        r = audit({"README.md": "Saves 40% of tokens.\n"})
        self.assertEqual(len(checks(r, "unsourced-figure")), 1)

    def test_provenance_on_the_line_or_just_above_silences_it(self):
        md = (
            "Reported by the project: 40% fewer tokens.\n\n"
            "These numbers are reported by the vendor and were not re-run:\n\n"
            "| Case | Savings |\n|---|---|\n| A | 47% |\n| B | 73% |\n\n"
            "Measured here with `python demo.py`: 40.5% saved.\n"
        )
        self.assertEqual(checks(audit({"README.md": md}), "unsourced-figure"), [])

    def test_multiplier_claims_are_noted_unless_sourced(self):
        md = (
            "The model that is 20x cheaper now.\n\n"
            "Runs 3.5× faster than the baseline.\n\n"
            "Reported by the vendor: 10x fewer calls.\n\n"
            "A 3x3 grid of 4x4 tiles.\n"
        )
        found = checks(audit({"README.md": md}), "unsourced-figure")
        self.assertEqual(sorted(f["line"] for f in found), [1, 3])

    def test_100_percent_is_ignored_and_money_is_checked(self):
        r = audit({"README.md": "100% local.\n\nSaves $2,147 per million requests.\n\nIllustrative estimate: saves $5,000.\n"})
        found = checks(r, "unsourced-figure")
        self.assertEqual(len(found), 1)
        self.assertIn("$2,147", found[0]["evidence"])


class StrongWording(unittest.TestCase):
    MD = "Savings verified across real workloads.\n\nThese are real API calls, not estimates.\n"

    def test_flagged_without_tests(self):
        self.assertEqual(len(checks(audit({"README.md": self.MD}), "strong-wording")), 2)

    def test_not_flagged_when_tests_exist(self):
        r = audit({"README.md": self.MD, "tests/test_x.py": "def test_x():\n    pass\n"})
        self.assertEqual(checks(r, "strong-wording"), [])


class Robustness(unittest.TestCase):
    def test_syntax_error_is_noted_and_others_still_checked(self):
        r = audit({"bad.py": "def (:\n", "good.py": 'print("Saves 50%")\n'})
        self.assertEqual(len(checks(r, "unparsed-file")), 1)
        self.assertEqual(len(checks(r, "typed-literal")), 1)

    def test_vendored_and_hidden_dirs_are_skipped(self):
        r = audit({"node_modules/x/a.py": 'print("Saves 50%")\n', ".venv/b.py": 'print("Saves 50%")\n', "ok.py": "x = 1\n"})
        self.assertEqual(r["python_files"], 1)
        self.assertEqual(r["findings"], [])

    def test_empty_repo(self):
        r = audit({})
        self.assertEqual((r["review"], r["notes"], r["findings"]), (0, 0, []))

    def test_run_does_not_modify_the_repo(self):
        root = make_repo({"README.md": "Saves 40%.\n", "a.py": 'print("Saves 50%")\n'})
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
        claim_audit.audit(root)
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
        self.assertEqual(before, after)


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8")

    def test_json_output_and_exit_codes(self):
        root = make_repo({"a.py": 'print("Saves 50%")\n'})
        out = self.run_cli("--repo", str(root), "--json")
        self.assertEqual(out.returncode, 0)
        self.assertEqual(json.loads(out.stdout)["review"], 1)
        self.assertEqual(self.run_cli("--repo", str(root), "--fail-on", "review").returncode, 1)
        clean = make_repo({"a.py": "x = 1\n"})
        self.assertEqual(self.run_cli("--repo", str(clean), "--fail-on", "note").returncode, 0)

    def test_bad_path_is_a_usage_error(self):
        self.assertEqual(self.run_cli("--repo", str(HERE / "does-not-exist")).returncode, 2)

    def test_text_report_says_leads_not_verdicts(self):
        root = make_repo({"a.py": 'print("Saves 50%")\n'})
        buf = io.StringIO()
        with redirect_stdout(buf):
            claim_audit.main(["--repo", str(root)])
        self.assertIn("leads, not verdicts", buf.getvalue())


class ClaimContext(unittest.TestCase):
    """Figures only count as claims next to savings or performance wording."""

    def test_dialogue_and_specs_are_not_claims(self):
        md = (
            '> "$11,500 seems fair for a car like this."\n\n'
            "| Personality | Style |\n|---|---|\n| Shark | Never drops more than 5% |\n\n"
            "Top 5% of users get early access.\n"
        )
        self.assertEqual(checks(audit({"README.md": md}), "unsourced-figure"), [])

    def test_claim_wording_still_flags(self):
        md = "Buyer saved: $2,250 off the asking price.\n\nLatency improved by 30%.\n"
        self.assertEqual(len(checks(audit({"README.md": md}), "unsourced-figure")), 2)


class Tables(unittest.TestCase):
    ROWS = "".join(f"| Case {i} | {40 + i}% |\n" for i in range(8))

    def test_one_provenance_line_above_covers_every_row(self):
        md = "Reported by the vendor and not re-run here:\n\n| Case | Savings |\n|---|---|\n" + self.ROWS
        self.assertEqual(checks(audit({"README.md": md}), "unsourced-figure"), [])

    def test_table_with_a_savings_header_and_no_source_is_flagged(self):
        md = "Results\n\n| Case | Savings |\n|---|---|\n" + self.ROWS
        self.assertEqual(len(checks(audit({"README.md": md}), "unsourced-figure")), 8)

    def test_provenance_in_the_header_covers_the_rows(self):
        md = "Results\n\n| Case | Reported savings |\n|---|---|\n" + self.ROWS
        self.assertEqual(checks(audit({"README.md": md}), "unsourced-figure"), [])


class ConsoleEncoding(unittest.TestCase):
    def test_emoji_in_a_readme_does_not_crash_a_legacy_console(self):
        root = make_repo({"README.md": "\U0001f988 Saves 40% of tokens.\n"})
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        out = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(root)], capture_output=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr.decode("utf-8", "replace"))
        self.assertIn(b"claim-auditor", out.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=1)
