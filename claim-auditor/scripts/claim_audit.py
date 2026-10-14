#!/usr/bin/env python3
"""
claim_audit.py: check a repository's README claims against the code behind them.

Usage:
    python3 claim_audit.py --repo PATH [--json] [--fail-on review]

Reads README files and Python source. Never executes the code it reads, makes
no network calls, and changes nothing. Python 3.8+, standard library only.

Every finding is a lead for a human to check, not a verdict. A typed-in number
can be legitimate and a computed one can still be wrong.

Checks
  typed-literal        A percentage typed into a displayed string or a metric-named
                       variable, instead of computed.
  library-not-imported A package in requirements that no file imports, but whose
                       import or use appears inside a string literal (for example a
                       demo that only prints example code).
  token-estimate       A "token" count computed as len(text) // 4.
  mixed-labels         The same percentage called a token saving in one place and a
                       size saving in another.
  unsourced-figure     A README figure, next to savings or performance wording, with
                       no hint of where it came from.
  strong-wording       "verified", "proven", "real API calls" and similar in a repo
                       with no tests, evals or benchmarks.
  unparsed-file        A Python file that could not be parsed, so it was skipped.
"""

import argparse
import ast
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

VERSION = "1.0.0"
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", "dist", "build", ".next"}
MAX_FILE_BYTES = 1_000_000

PCT_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d+)?)(?:\s*[-–]\s*(\d{1,3}(?:\.\d+)?))?\s*%")
MONEY_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")
MULT_RE = re.compile(
    r"(?<![\w.])\d+(?:\.\d+)?\s?[x×]\s+(?:faster|slower|cheaper|fewer|smaller|lower|less|better|more efficient)\b", re.I
)
CSS_RE = re.compile(r"(width|height|padding|margin|opacity|font-size|flex|top|left|right|bottom|min-|max-|translate)[^;\"']*%", re.I)

DISPLAY_CALLS = {
    "print", "metric", "write", "markdown", "success", "info", "warning", "error", "caption",
    "text", "subheader", "header", "title", "code", "echo", "display", "log", "debug",
}
METRIC_NAME_RE = re.compile(r"(saving|reduc|improv|speedup|accuracy|benchmark|metric|percent|pct|stat|result)", re.I)

PROVENANCE_RE = re.compile(
    r"(report(?:s|ed)|according to|claimed|claims|measured|benchmark|illustrative|estimate|sample|reproduce|"
    r"run it yourself|as of|not re-?run|not reproduced|their own|project-reported)",
    re.I,
)
CLAIM_RE = re.compile(
    r"(sav(?:e|es|ed|ing|ings)|reduc|faster|slower|speed|cheaper|cost|fewer|less than|improv|accura|boost|gain|lower|"
    r"overhead|latency|compress|throughput|win rate|precision|recall|efficien)",
    re.I,
)
STRONG_RE = re.compile(
    r"\b(verified|proven|proof|guarantee[sd]?|real api calls?|not estimates|production[- ]ready|battle[- ]tested)\b", re.I
)
TOKEN_WORD = re.compile(r"\btokens?\b", re.I)
SIZE_WORD = re.compile(r"\b(size|bytes?|characters?|chars|payload|file size)\b", re.I)

# Packages that are tools, not libraries a demo would import.
TOOL_PACKAGES = {"pytest", "black", "ruff", "mypy", "flake8", "pylint", "uvicorn", "gunicorn", "pip", "setuptools", "wheel", "build", "twine"}
ALIASES = {
    "pillow": ["PIL"], "opencv-python": ["cv2"], "scikit-learn": ["sklearn"], "python-dotenv": ["dotenv"],
    "beautifulsoup4": ["bs4"], "pyyaml": ["yaml"], "google-genai": ["google"], "google-adk": ["google"],
    "mem0ai": ["mem0"], "python-multipart": ["multipart"], "headroom-ai": ["headroom"], "firecrawl-py": ["firecrawl"],
    "openai-agents": ["agents"], "faiss-cpu": ["faiss"], "attrs": ["attr"], "protobuf": ["google"],
}


class Finding:
    def __init__(self, check, severity, file, line, evidence, why, fix):
        self.check, self.severity, self.file, self.line = check, severity, file, line
        self.evidence, self.why, self.fix = evidence, why, fix

    def as_dict(self):
        return dict(self.__dict__)


# --------------------------------------------------------------------------- files

def read_text(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def walk_repo(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            yield Path(dirpath) / name


def is_readme(path: Path) -> bool:
    return bool(re.match(r"^readme(\..+)?$", path.name, re.I)) and path.suffix.lower() in {".md", ".markdown", ".rst", ".txt", ""}


def has_tests(root: Path, files) -> bool:
    for path in files:
        rel = path.relative_to(root)
        parts = [p.lower() for p in rel.parts]
        if any(p.startswith(("test", "eval", "bench")) or p.endswith("_test.py") for p in parts):
            return True
    return False


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


# --------------------------------------------------------------------------- python

def parse_python(root: Path, files, findings):
    trees = {}
    for path in files:
        if path.suffix != ".py":
            continue
        text = read_text(path)
        try:
            trees[path] = (ast.parse(text), text)
        except (SyntaxError, ValueError) as exc:
            findings.append(Finding(
                "unparsed-file", "NOTE", rel(root, path), getattr(exc, "lineno", 0) or 0, str(exc)[:120],
                "This file could not be parsed, so its claims were not checked.", "Check it by hand.",
            ))
    return trees


def docstring_nodes(tree):
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                skip.add(id(body[0].value))
    return skip


def call_name(node):
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def target_names(stmt):
    names = []
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [getattr(stmt, "target", None)]
    for t in targets:
        if isinstance(t, ast.Name):
            names.append(t.id)
        elif isinstance(t, ast.Attribute):
            names.append(t.attr)
        elif isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and isinstance(t.slice.value, str):
            names.append(t.slice.value)
    return names


QUOTED_MARK = "claim-audit: quoted"
# Wording that credits someone else. "measured" is deliberately absent: a typed-in number
# that says "measured" is exactly what typed-literal exists to catch.
ATTRIBUTED_RE = re.compile(r"(report(?:s|ed)|according to|claim(?:s|ed)|quoted|vendor|authors?'s? )", re.I)


def check_typed_literals(root, path, tree, text, findings):
    lines = text.splitlines()
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    docs = docstring_nodes(tree)
    seen = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)) or id(node) in docs:
            continue
        for m in PCT_RE.finditer(node.value):
            values = [v for v in m.groups() if v]
            if all(float(v) in (0, 100) for v in values) or CSS_RE.search(node.value):
                continue
            how = None
            cur = node
            while cur in parents:
                cur = parents[cur]
                if isinstance(cur, ast.Call) and call_name(cur) in DISPLAY_CALLS:
                    how = f"shown by {call_name(cur)}()"
                    break
                if isinstance(cur, ast.Dict) and node in cur.values:
                    key = cur.keys[cur.values.index(node)]
                    if isinstance(key, ast.Constant) and isinstance(key.value, str) and METRIC_NAME_RE.search(key.value):
                        how = f"dict value for {key.value!r}"
                        break
                if isinstance(cur, ast.stmt):
                    if isinstance(cur, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and any(METRIC_NAME_RE.search(n) for n in target_names(cur)):
                        how = "assigned to " + ", ".join(target_names(cur))
                    break
            if not how:
                continue
            line = node.lineno + node.value[: m.start()].count("\n")
            if 0 < line <= len(lines) and QUOTED_MARK in lines[line - 1]:
                continue  # the author marked this figure as quoted, not measured
            if ATTRIBUTED_RE.search(node.value):
                continue  # the text itself credits the figure to someone else
            key = (path, line, m.group(0))
            if key in seen:
                continue
            seen.add(key)
            findings.append(Finding(
                "typed-literal", "REVIEW", rel(root, path), line, f"{m.group(0).strip()} ({how})",
                "This figure is typed into the code, so it cannot change when the code runs.",
                "Compute it from real measurements, or label it as a quoted figure.",
            ))


def check_token_estimates(root, path, tree, findings):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, (ast.FloorDiv, ast.Div))
            and isinstance(node.right, ast.Constant)
            and node.right.value == 4
            and isinstance(node.left, ast.Call)
            and call_name(node.left) == "len"
        ):
            findings.append(Finding(
                "token-estimate", "NOTE", rel(root, path), node.lineno, "len(...) // 4 used as a token count",
                "Characters divided by 4 is a rough rule of thumb, not a token count.",
                "Use the model's tokenizer (for example tiktoken) before quoting savings.",
            ))


def imported_modules(trees):
    mods = set()
    for tree, _ in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods.add(node.module.split(".")[0])
    return mods


def string_literals(trees):
    out = []
    for path, (tree, _) in trees.items():
        docs = docstring_nodes(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                out.append((path, node.lineno, node.value))
    return out


def requirement_names(root, files):
    names = {}
    for path in files:
        if re.match(r"^requirements.*\.txt$", path.name, re.I):
            for i, line in enumerate(read_text(path).splitlines(), 1):
                line = line.split("#")[0].strip()
                if not line or line.startswith("-"):
                    continue
                name = re.split(r"[\[<>=!~;\s@]", line, maxsplit=1)[0].strip()
                if name:
                    names.setdefault(name, (path, i))
    return names


def module_candidates(package):
    base = package.lower()
    cands = set(ALIASES.get(base, []))
    cands.add(base.replace("-", "_").replace(".", "_"))
    for suffix in ("-ai", "-py", "-sdk", "-python"):
        if base.endswith(suffix):
            cands.add(base[: -len(suffix)].replace("-", "_"))
    if base.startswith("python-"):
        cands.add(base[len("python-"):].replace("-", "_"))
    cands.add(base.split("-")[0])
    return {c for c in cands if c}


def check_libraries(root, files, trees, findings):
    imported = {m.lower() for m in imported_modules(trees)}
    literals = string_literals(trees)
    for package, (req_path, req_line) in requirement_names(root, files).items():
        if package.lower() in TOOL_PACKAGES:
            continue
        cands = module_candidates(package)
        if any(c.lower() in imported for c in cands):
            continue
        specific = [c for c in cands if len(c) >= 4]
        for path, line, value in literals:
            # Only a string that contains an import or use of the library counts, not a bare mention.
            if any(re.search(rf"\b(?:import|from)\s+{re.escape(c)}\b|\b{re.escape(c)}\.[A-Za-z_]\w*", value, re.I) for c in specific):
                findings.append(Finding(
                    "library-not-imported", "REVIEW", rel(root, path), line,
                    f"{package} is in {rel(root, req_path)}:{req_line} but no file imports it; its import or use appears only inside a string",
                    "A demo that only prints code about a library is not exercising the library.",
                    "Call the library for real, or say the demo is illustrative.",
                ))
                break


# --------------------------------------------------------------------------- readme

def readme_lines(root, files):
    for path in files:
        if is_readme(path):
            lines = read_text(path).splitlines()
            for i, line in enumerate(lines, 1):
                yield path, i, line, lines


def table_start(lines, index):
    """Index of the first row of the markdown table containing lines[index], or None."""
    if not lines[index].lstrip().startswith("|"):
        return None
    start = index
    while start > 0 and lines[start - 1].lstrip().startswith("|"):
        start -= 1
    return start


def context_lines(lines, index):
    """The line, its table header if it is a table row, and up to 4 non-empty lines above."""
    start = table_start(lines, index)
    top = index if start is None else start
    window = [lines[index]]
    if start is not None:
        window.append(lines[start])
    seen, j = 0, top - 1
    while j >= 0 and seen < 4:
        if lines[j].strip():
            window.append(lines[j])
            seen += 1
        j -= 1
    return window


def provenance_nearby(lines, index):
    return any(PROVENANCE_RE.search(w) for w in context_lines(lines, index))


def claimish(lines, index):
    """True when the line, or the header of its table, uses savings or performance wording."""
    start = table_start(lines, index)
    texts = [lines[index]] + ([lines[start]] if start is not None else [])
    return any(CLAIM_RE.search(t) for t in texts)


def check_readmes(root, files, trees, tests_exist, findings):
    claims = defaultdict(lambda: defaultdict(list))  # number -> kind -> [(path, line)]
    reported = set()
    for path, i, line, lines in readme_lines(root, files):
        tokenish, sizeish = bool(TOKEN_WORD.search(line)), bool(SIZE_WORD.search(line))
        for m in PCT_RE.finditer(line):
            values = [v for v in m.groups() if v]
            if all(float(v) in (0, 100) for v in values):
                continue
            for v in values:
                if tokenish and not sizeish:
                    claims[v]["token"].append((path, i))
                elif sizeish and not tokenish:
                    claims[v]["size"].append((path, i))
            if claimish(lines, i - 1) and not provenance_nearby(lines, i - 1) and (path, i) not in reported:
                reported.add((path, i))
                findings.append(Finding(
                    "unsourced-figure", "NOTE", rel(root, path), i, line.strip()[:140],
                    "A figure with no hint of whether it was measured here, quoted from elsewhere, or estimated.",
                    "Say where it comes from, for example 'reported by the project' or 'measured with <command>'.",
                ))
        for m in MONEY_RE.finditer(line):
            if claimish(lines, i - 1) and (path, i) not in reported and not provenance_nearby(lines, i - 1):
                reported.add((path, i))
                findings.append(Finding(
                    "unsourced-figure", "NOTE", rel(root, path), i, line.strip()[:140],
                    "A cost figure with no stated basis.", "State the pricing and volume assumptions, or label it illustrative.",
                ))
        for m in MULT_RE.finditer(line):
            # The comparative ("cheaper", "faster") makes this a claim without further wording.
            if (path, i) not in reported and not provenance_nearby(lines, i - 1):
                reported.add((path, i))
                findings.append(Finding(
                    "unsourced-figure", "NOTE", rel(root, path), i, line.strip()[:140],
                    f"A comparison ({m.group(0).strip()}) with no stated source or baseline.",
                    "Say what it is compared against and where the figure comes from.",
                ))
        if not tests_exist and STRONG_RE.search(line):
            findings.append(Finding(
                "strong-wording", "NOTE", rel(root, path), i, line.strip()[:140],
                "Strong wording, but this repository has no tests, evals or benchmarks to back it.",
                "Add the test or benchmark, or soften the wording.",
            ))
    for number, kinds in claims.items():
        if "token" in kinds and "size" in kinds:
            tpath, tline = kinds["token"][0]
            spath, sline = kinds["size"][0]
            findings.append(Finding(
                "mixed-labels", "REVIEW", rel(root, tpath), tline,
                f"{number}% is called a token saving at {rel(root, tpath)}:{tline} and a size saving at {rel(root, spath)}:{sline}",
                "Bytes and tokens are different measures, and cost follows tokens.",
                "Use each label for the figure it describes.",
            ))


# --------------------------------------------------------------------------- main

SEVERITY_ORDER = {"REVIEW": 0, "NOTE": 1}


def audit(repo) -> dict:
    root = Path(repo).resolve()
    files = list(walk_repo(root))
    findings = []
    trees = parse_python(root, files, findings)
    for path, (tree, text) in trees.items():
        check_typed_literals(root, path, tree, text, findings)
        check_token_estimates(root, path, tree, findings)
    check_libraries(root, files, trees, findings)
    check_readmes(root, files, trees, has_tests(root, files), findings)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.file, f.line, f.check))
    counts = defaultdict(int)
    for f in findings:
        counts[f.check] += 1
    return {
        "version": VERSION,
        "repo": str(root),
        "python_files": len(trees),
        "readmes": sum(1 for p in files if is_readme(p)),
        "summary": dict(counts),
        "review": sum(1 for f in findings if f.severity == "REVIEW"),
        "notes": sum(1 for f in findings if f.severity == "NOTE"),
        "findings": [f.as_dict() for f in findings],
    }


def render_text(report: dict) -> str:
    out = [
        f"claim-auditor {report['version']}: {report['repo']}",
        f"Read {report['readmes']} README file(s) and {report['python_files']} Python file(s).",
        f"{report['review']} to review, {report['notes']} notes. These are leads, not verdicts.",
    ]
    for f in report["findings"]:
        out += ["", f"[{f['severity']}] {f['check']}  {f['file']}:{f['line']}", f"  evidence: {f['evidence']}", f"  why: {f['why']}", f"  fix: {f['fix']}"]
    return "\n".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check README claims against the code behind them.")
    parser.add_argument("--repo", default=".", help="Repository path (default: current directory)")
    parser.add_argument("--json", action="store_true", help="Print JSON")
    parser.add_argument("--fail-on", choices=["review", "note"], help="Exit 1 if a finding of this level or worse exists")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # README text can hold emoji a Windows console cannot print
    if not Path(args.repo).is_dir():
        print(f"error: {args.repo} is not a directory", file=sys.stderr)
        return 2
    report = audit(args.repo)
    print(json.dumps(report, indent=2) if args.json else render_text(report))
    if args.fail_on == "review" and report["review"]:
        return 1
    if args.fail_on == "note" and (report["review"] or report["notes"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
