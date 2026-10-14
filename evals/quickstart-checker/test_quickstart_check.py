#!/usr/bin/env python3
"""Deterministic tests for quickstart-checker's script. Standard library only; exits 0 on success, 1 on failure.

Run: python3 evals/quickstart-checker/test_quickstart_check.py
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent.parent / "quickstart-checker" / "scripts" / "quickstart_check.py"
sys.path.insert(0, str(SCRIPT.parent))
import quickstart_check  # noqa: E402


def make_repo(files, name="mine"):
    root = Path(tempfile.mkdtemp(prefix="qs_check_")) / name
    root.mkdir()
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def audit(files, name="mine"):
    return quickstart_check.audit(make_repo(files, name))


def checks(report, check):
    return [f for f in report["findings"] if f["check"] == check]


def sh(*lines):
    return "# App\n\n```bash\n" + "\n".join(lines) + "\n```\n"


class MissingPath(unittest.TestCase):
    def test_cd_into_missing_folder(self):
        r = audit({"README.md": sh("cd nowhere", "python app.py")})
        found = checks(r, "missing-path")
        self.assertEqual(len(found), 1)  # after a failed cd the rest is not guessed at
        self.assertIn("nowhere", found[0]["evidence"])

    def test_paths_resolve_relative_to_cd(self):
        r = audit({"README.md": sh("cd app", "pip install -r requirements.txt", "streamlit run main.py"),
                   "app/requirements.txt": "x\n", "app/main.py": "x = 1\n"})
        self.assertEqual(checks(r, "missing-path"), [])

    def test_commands_that_name_missing_files(self):
        r = audit({"README.md": sh("pip install -r requirements.txt", "streamlit run app.py", "python server.py", "node index.js", "bash setup.sh")})
        self.assertEqual(len(checks(r, "missing-path")), 5)

    def test_existing_files_are_fine_and_readme_folder_is_the_base(self):
        r = audit({"sub/README.md": sh("python run.py", "pip install -r requirements.txt"), "sub/run.py": "", "sub/requirements.txt": ""})
        self.assertEqual(checks(r, "missing-path"), [])

    def test_things_the_steps_create_are_not_missing(self):
        r = audit({"README.md": sh("python -m venv venv", "source venv/bin/activate", "mkdir data", "cp .env.example .env", "streamlit run app.py"),
                   ".env.example": "K=1\n", "app.py": ""})
        self.assertEqual(checks(r, "missing-path"), [])

    def test_cp_checks_its_source_but_not_its_destination(self):
        r = audit({"README.md": sh("cp config.sample.yml config.yml")})
        found = checks(r, "missing-path")
        self.assertEqual(len(found), 1)
        self.assertIn("config.sample.yml", found[0]["evidence"])

    def test_placeholders_urls_prompts_comments_and_chains(self):
        md = sh("$ cd <your-folder>", "cd $HOME/work", "pip install -r ~/x.txt", "# python nope.py", "python app.py && echo done",
                "pip install \\", "   -r requirements.txt")
        r = audit({"README.md": md, "app.py": "", "requirements.txt": ""})
        self.assertEqual(checks(r, "missing-path"), [])

    def test_path_that_starts_with_the_readmes_own_folder_means_run_from_its_parent(self):
        files = {"tools/skill/README.md": sh("python3 skill/scripts/run.py", "python3 skill/scripts/nope.py"), "tools/skill/scripts/run.py": ""}
        found = checks(audit(files), "missing-path")
        self.assertEqual(len(found), 1)
        self.assertIn("nope.py", found[0]["evidence"])

    def test_after_a_placeholder_cd_the_directory_is_unknown(self):
        for cd in ("cd <your-folder>", "cd $PROJECT_DIR", "cd ~/work/app"):
            r = audit({"README.md": sh(cd, "pip install -r requirements.txt", "streamlit run app.py")})
            self.assertEqual(checks(r, "missing-path"), [], cd)

    def test_after_cloning_this_repo_a_placeholder_cd_also_stops_guessing(self):
        md = sh("git clone https://github.com/me/mine.git", "cd mine/agents/<agent-folder>", "pip install -r requirements.txt")
        self.assertEqual(checks(audit({"README.md": md}, name="mine"), "missing-path"), [])

    def test_cd_dotdot_moves_to_the_parent(self):
        # mod.py exists only in a/, so it is found only if "cd .." really moved up from a/b.
        files = {"README.md": sh("cd a/b", "cd ..", "python mod.py"), "a/b/x.py": "", "a/mod.py": ""}
        self.assertEqual(checks(audit(files), "missing-path"), [])
        broken = {"README.md": sh("cd a/b", "cd ..", "python x.py"), "a/b/x.py": "", "a/mod.py": ""}
        self.assertEqual(len(checks(audit(broken), "missing-path")), 1)  # x.py is in a/b, not a/

    def test_only_shell_blocks_are_read(self):
        md = "```python\nimport os\nos.system('python nope.py')\n```\n\n```json\n{\"cd\": \"nowhere\"}\n```\n"
        self.assertEqual(checks(audit({"README.md": md}), "missing-path"), [])

    def test_after_a_clone_the_cwd_is_unknown_so_nothing_is_guessed(self):
        r = audit({"README.md": sh("git clone https://github.com/someone/other.git", "cd other/sub", "python app.py")})
        self.assertEqual(checks(r, "missing-path"), [])


class ClonesOtherRepo(unittest.TestCase):
    def test_clone_of_a_different_repo_is_noted(self):
        r = audit({"README.md": sh("git clone https://github.com/someone/original.git")}, name="mine")
        found = checks(r, "clones-other-repo")
        self.assertEqual(len(found), 1)
        self.assertIn("original", found[0]["why"])

    def test_clone_of_this_repo_is_fine(self):
        r = audit({"README.md": sh("git clone https://github.com/me/mine.git", "cd mine")}, name="mine")
        self.assertEqual(checks(r, "clones-other-repo"), [])

    def test_repo_name_comes_from_the_git_remote_when_present(self):
        root = make_repo({"README.md": sh("git clone https://github.com/me/real-name.git")}, name="checkout-dir")
        (root / ".git").mkdir()
        (root / ".git" / "config").write_text('[remote "origin"]\n\turl = https://github.com/me/real-name.git\n', encoding="utf-8")
        self.assertEqual(checks(quickstart_check.audit(root), "clones-other-repo"), [])


class CloneOfThisRepo(unittest.TestCase):
    """After cloning this repo, paths are checked against this repo's own layout."""

    def clone_steps(self, cd, *more):
        return sh("git clone https://github.com/me/mine.git", f"cd {cd}", *more)

    def test_correct_path_after_cloning_this_repo_passes(self):
        files = {"README.md": self.clone_steps("mine/apps/web", "pip install -r requirements.txt", "streamlit run app.py"),
                 "apps/web/requirements.txt": "", "apps/web/app.py": ""}
        self.assertEqual(audit(files, name="mine")["findings"], [])

    def test_wrong_path_after_cloning_this_repo_is_caught(self):
        r = audit({"README.md": self.clone_steps("mine/apps/typo"), "apps/web/app.py": ""}, name="mine")
        found = checks(r, "missing-path")
        self.assertEqual(len(found), 1)
        self.assertIn("mine/apps/typo", found[0]["evidence"])

    def test_files_are_checked_inside_the_folder_the_steps_cd_into(self):
        files = {"README.md": self.clone_steps("mine/apps/web", "streamlit run app.py"), "apps/web/other.py": ""}
        found = checks(audit(files, name="mine"), "missing-path")
        self.assertEqual(len(found), 1)
        self.assertIn("app.py", found[0]["evidence"])

    def test_clone_into_a_named_folder(self):
        md = sh("git clone https://github.com/me/mine.git custom", "cd custom/apps/web")
        self.assertEqual(checks(audit({"README.md": md, "apps/web/x.py": ""}, name="mine"), "missing-path"), [])

    def test_other_repos_are_still_not_guessed_at(self):
        md = sh("git clone https://github.com/me/other.git", "cd other/anything", "python nope.py")
        r = audit({"README.md": md}, name="mine")
        self.assertEqual(checks(r, "missing-path"), [])
        self.assertEqual(len(checks(r, "clones-other-repo")), 1)


class AuditingASubfolder(unittest.TestCase):
    """Pointing the tool at a folder inside a checkout must still know which repository it belongs to."""

    def checkout(self, readme):
        top = make_repo({"apps/web/README.md": readme, "apps/web/app.py": "", "apps/web/requirements.txt": ""}, name="mine")
        (top / ".git").mkdir()
        (top / ".git" / "config").write_text('[remote "origin"]\n\turl = https://github.com/me/mine.git\n', encoding="utf-8")
        return top

    def test_cloning_the_enclosing_repo_is_not_foreign_and_its_paths_resolve(self):
        top = self.checkout(sh("git clone https://github.com/me/mine.git", "cd mine/apps/web", "pip install -r requirements.txt", "streamlit run app.py"))
        self.assertEqual(quickstart_check.audit(top / "apps" / "web")["findings"], [])

    def test_a_wrong_path_is_still_caught_from_the_subfolder(self):
        top = self.checkout(sh("git clone https://github.com/me/mine.git", "cd mine/apps/typo"))
        found = checks(quickstart_check.audit(top / "apps" / "web"), "missing-path")
        self.assertEqual(len(found), 1)

    def test_a_foreign_clone_is_still_foreign(self):
        top = self.checkout(sh("git clone https://github.com/me/other.git"))
        self.assertEqual(len(checks(quickstart_check.audit(top / "apps" / "web"), "clones-other-repo")), 1)


class MissingScript(unittest.TestCase):
    PKG = json.dumps({"scripts": {"start": "node x.js", "build": "vite build"}})

    def test_missing_script_is_flagged_and_present_ones_are_not(self):
        r = audit({"README.md": sh("npm run build", "npm run dev"), "package.json": self.PKG})
        found = checks(r, "missing-script")
        self.assertEqual(len(found), 1)
        self.assertIn("dev", found[0]["evidence"])

    def test_no_package_json_means_nothing_to_check(self):
        self.assertEqual(checks(audit({"README.md": sh("npm run dev")}), "missing-script"), [])

    def test_script_found_via_cd(self):
        r = audit({"README.md": sh("cd web", "npm run dev"), "web/package.json": json.dumps({"scripts": {"dev": "vite"}})})
        self.assertEqual(checks(r, "missing-script"), [])


class PythonVersion(unittest.TestCase):
    def test_builtin_generics_need_3_9(self):
        r = audit({"README.md": "Requires Python 3.8+\n", "a.py": "def f() -> tuple[int, str]:\n    return 1, 'x'\n"})
        found = checks(r, "python-version")
        self.assertEqual(len(found), 1)
        self.assertIn("3.9", found[0]["evidence"])

    def test_union_syntax_needs_3_10(self):
        r = audit({"README.md": "Python 3.9 or higher\n", "a.py": "def f(x: str | None = None):\n    return x\n"})
        self.assertIn("3.10", checks(r, "python-version")[0]["evidence"])

    def test_future_annotations_removes_the_problem(self):
        src = "from __future__ import annotations\n\ndef f(x: str | None) -> tuple[int, str]:\n    return 1, 'x'\n"
        self.assertEqual(checks(audit({"README.md": "Python 3.8+\n", "a.py": src}), "python-version"), [])

    def test_typing_generics_and_new_enough_claims_are_fine(self):
        src = "from typing import Tuple\n\ndef f() -> Tuple[int, str]:\n    return 1, 'x'\n"
        self.assertEqual(checks(audit({"README.md": "Python 3.8+\n", "a.py": src}), "python-version"), [])
        self.assertEqual(checks(audit({"README.md": "Python 3.10+\n", "b.py": "def f(x: str | None): pass\n"}), "python-version"), [])

    def test_no_claim_means_no_finding(self):
        self.assertEqual(checks(audit({"README.md": "Hello\n", "a.py": "def f() -> tuple[int, str]: pass\n"}), "python-version"), [])

    def test_removeprefix_needs_3_9(self):
        r = audit({"README.md": "Requires Python 3.8\n", "a.py": "x = 'ab'.removeprefix('a')\n"})
        self.assertEqual(len(checks(r, "python-version")), 1)

    @unittest.skipUnless(sys.version_info >= (3, 10), "match statements need 3.10 to parse")
    def test_match_statement_needs_3_10(self):
        src = "def f(x):\n    match x:\n        case 1:\n            return 'one'\n"
        r = audit({"README.md": "Python 3.9+\n", "a.py": src})
        self.assertIn("match", checks(r, "python-version")[0]["evidence"])

    def test_claim_only_applies_to_code_under_that_readme(self):
        r = audit({"a/README.md": "Python 3.8+\n", "b/a.py": "def f() -> tuple[int, str]: pass\n"})
        self.assertEqual(checks(r, "python-version"), [])


class MissingRequirement(unittest.TestCase):
    def test_unlisted_third_party_import_is_noted(self):
        r = audit({"requirements.txt": "requests\n", "a.py": "import requests\nimport yaml\nimport os\n"})
        found = checks(r, "missing-requirement")
        self.assertEqual(len(found), 1)
        self.assertIn("yaml", found[0]["evidence"])

    def test_aliases_stdlib_and_local_modules_are_fine(self):
        files = {"requirements.txt": "pillow\npython-dotenv\ntoonify\n", "a.py": "from PIL import Image\nfrom dotenv import load_dotenv\nfrom toon import encode\nimport json, helper\n", "helper.py": ""}
        self.assertEqual(checks(audit(files), "missing-requirement"), [])

    def test_no_requirements_file_means_nothing_to_compare(self):
        self.assertEqual(checks(audit({"a.py": "import yaml\n"}), "missing-requirement"), [])

    def test_test_files_are_skipped(self):
        files = {"requirements.txt": "requests\n", "tests/test_a.py": "import pytest\n", "test_b.py": "import pytest\n"}
        self.assertEqual(checks(audit(files), "missing-requirement"), [])


def env_names(report):
    return sorted(re.match(r"reads (\w+)", f["evidence"]).group(1) for f in checks(report, "undocumented-env"))


class UndocumentedEnv(unittest.TestCase):
    def test_required_read_without_docs_is_noted(self):
        r = audit({"README.md": "# App\n", "a.py": 'import os\nkey = os.environ["MY_KEY"]\nother = os.getenv("OTHER_KEY")\n'})
        self.assertEqual(env_names(r), ["MY_KEY", "OTHER_KEY"])

    def test_documented_in_readme_or_env_file_is_fine(self):
        files = {"README.md": "Set `MY_KEY`.\n", ".env.example": "OTHER_KEY=\n", "a.py": 'import os\na = os.environ["MY_KEY"]\nb = os.getenv("OTHER_KEY")\n'}
        self.assertEqual(checks(audit(files), "undocumented-env"), [])

    def test_assignments_and_defaults_are_not_reads_that_must_succeed(self):
        src = 'import os\nos.environ["SET_ME"] = "x"\np = os.getenv("PORT_X", "8000")\nq = os.environ.get("OPT", "d")\nif os.environ["FLAG"] == "b": pass\n'
        r = audit({"README.md": "# App\n", "a.py": src})
        # A comparison is still a read; assignments and defaulted reads are not.
        self.assertEqual(env_names(r), ["FLAG"])

    def test_system_variables_are_ignored(self):
        self.assertEqual(checks(audit({"README.md": "x\n", "a.py": 'import os\nh = os.environ["HOME"]\n'}), "undocumented-env"), [])


class Robustness(unittest.TestCase):
    def test_empty_repo_and_syntax_errors(self):
        self.assertEqual(audit({})["findings"], [])
        r = audit({"README.md": sh("cd nowhere"), "bad.py": "def (:\n"})
        self.assertEqual(len(checks(r, "missing-path")), 1)

    def test_skipped_directories(self):
        r = audit({"node_modules/x/README.md": sh("cd nowhere"), ".venv/README.md": sh("cd nowhere")})
        self.assertEqual(r["readmes"], 0)

    def test_run_does_not_modify_the_repo(self):
        root = make_repo({"README.md": sh("cd nowhere"), "a.py": "x = 1\n"})
        before = {p.name: p.read_bytes() for p in root.iterdir()}
        quickstart_check.audit(root)
        self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})


class Cli(unittest.TestCase):
    def run_cli(self, *args, env=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, env=env)

    def test_json_and_exit_codes(self):
        root = make_repo({"README.md": sh("cd nowhere")})
        out = self.run_cli("--repo", str(root), "--json")
        self.assertEqual(out.returncode, 0)
        self.assertEqual(json.loads(out.stdout)["review"], 1)
        self.assertEqual(self.run_cli("--repo", str(root), "--fail-on", "review").returncode, 1)
        clean = make_repo({"README.md": "# Hi\n"})
        self.assertEqual(self.run_cli("--repo", str(clean), "--fail-on", "note").returncode, 0)

    def test_bad_path_is_a_usage_error(self):
        self.assertEqual(self.run_cli("--repo", str(HERE / "nope")).returncode, 2)

    def test_emoji_does_not_crash_a_legacy_console(self):
        root = make_repo({"README.md": "\U0001f988\n\n```bash\ncd \u2728nowhere\n```\n"})
        out = self.run_cli("--repo", str(root), env=dict(os.environ, PYTHONIOENCODING="cp1252"))
        self.assertEqual(out.returncode, 0, out.stderr.decode("utf-8", "replace"))
        self.assertIn(b"quickstart-checker", out.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=1)
