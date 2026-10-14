#!/usr/bin/env python3
"""
quickstart_check.py: check whether a README's quick start can work, without running anything.

Usage:
    python3 quickstart_check.py --repo PATH [--json] [--fail-on review|note]

Reads README files, package.json, requirements files and Python source. Never executes
anything it reads, makes no network calls and changes nothing. Python 3.8+, standard
library only.

Every finding is a lead for a human to check, not a verdict.

Checks
  missing-path        A file or folder named in a README command does not exist.
  missing-script      `npm run X` where package.json has no script X.
  clones-other-repo   The README tells you to clone a different repository than the one
                      it lives in, so the steps may not use this code.
  python-version      The README promises a Python version older than the syntax needs.
  missing-requirement Code imports a third-party package that requirements does not list.
  undocumented-env    Code reads an environment variable that no README or .env file mentions.
"""

import argparse
import ast
import json
import os
import re
import shlex
import sys
from pathlib import Path

VERSION = "1.0.0"
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", "dist", "build", ".next"}
MAX_FILE_BYTES = 1_000_000

SHELL_LANGS = {"", "bash", "sh", "shell", "console", "zsh", "powershell", "ps1", "cmd", "bat", "terminal", "shell-session"}
GENERATED = {".env", "venv", ".venv", "env", "node_modules", "dist", "build", ".git", "__pycache__"}
SYSTEM_ENV = {"PATH", "HOME", "USER", "USERNAME", "PWD", "SHELL", "LANG", "TERM", "TMPDIR", "TEMP", "TMP", "TZ", "CI", "PYTHONPATH", "PYTHONIOENCODING", "COLUMNS", "LINES"}
ALIASES = {
    "pillow": ["PIL"], "opencv-python": ["cv2"], "scikit-learn": ["sklearn"], "python-dotenv": ["dotenv"],
    "beautifulsoup4": ["bs4"], "pyyaml": ["yaml"], "google-genai": ["google"], "google-adk": ["google"],
    "mem0ai": ["mem0"], "python-multipart": ["multipart"], "headroom-ai": ["headroom"], "firecrawl-py": ["firecrawl"],
    "openai-agents": ["agents"], "faiss-cpu": ["faiss"], "attrs": ["attr"], "protobuf": ["google"],
    "toonify": ["toon"], "ag-ui-adk": ["ag_ui_adk"], "ag-ui-protocol": ["ag_ui"], "autogen": ["autogen"],
    "pyautogen": ["autogen"], "docker": ["docker"], "python-chess": ["chess"], "newspaper4k": ["newspaper"],
    "duckduckgo-search": ["duckduckgo_search", "ddgs"], "ddgs": ["ddgs"], "langchain-openai": ["langchain_openai"],
}
COMMAND_STARTS = {"cd", "python", "python3", "py", "pip", "pip3", "streamlit", "node", "npm", "yarn", "pnpm", "cp", "git", "mkdir", "bash", "sh", "source"}
PY_CLAIM_RES = [
    re.compile(r"python\s*v?(3\.\d{1,2})\s*(?:\+|or\s+(?:higher|newer|later|above)|and\s+(?:above|up))", re.I),
    re.compile(r"(?:requires?|needs?|prerequisites?:?)\s+python\s*v?(3\.\d{1,2})\b", re.I),
]
BUILTIN_GENERICS = {"list", "dict", "tuple", "set", "frozenset", "type"}


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


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def is_readme(path: Path) -> bool:
    return bool(re.match(r"^readme(\..+)?$", path.name, re.I)) and path.suffix.lower() in {".md", ".markdown", ".rst", ".txt", ""}


def checkout_root(root: Path) -> Path:
    """The folder holding .git when root is inside a checkout, so auditing a subfolder still knows its repo."""
    for folder in [root, *root.parents]:
        if (folder / ".git").exists():
            return folder
    return root


def repo_name(root: Path) -> str:
    top = checkout_root(root)
    cfg = top / ".git" / "config"
    if cfg.is_file():
        m = re.search(r"url\s*=\s*\S*?/([^/\s]+?)(?:\.git)?\s*$", read_text(cfg), re.M)
        if m:
            return m.group(1)
    return top.name


# --------------------------------------------------------------------------- README commands

def shell_blocks(text: str):
    """Yield (start_line, [(line_no, command_line)]) for each shell-like fenced block."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"^\s*```+\s*([\w-]*)", lines[i])
        if m:
            lang = m.group(1).lower()
            j = i + 1
            block = []
            while j < len(lines) and not re.match(r"^\s*```", lines[j]):
                block.append((j + 1, lines[j]))
                j += 1
            if lang in SHELL_LANGS:
                yield i + 1, block
            i = j + 1
        else:
            i += 1


def commands(block):
    """Turn raw block lines into (line_no, [tokens]) commands: joins continuations, splits on && and ;."""
    out, pending = [], ""
    pending_no = None
    for no, raw in block:
        line = re.sub(r"^\s*(?:\$|>|PS>|PS [^>]*>)\s+", "", raw.strip())
        if not line or line.startswith("#"):
            continue
        if pending == "":
            pending_no = no
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        full = (pending + line).strip()
        pending = ""
        for part in re.split(r"\s*(?:&&|;)\s*", full):
            part = part.split(" | ")[0].strip()
            if not part:
                continue
            try:
                tokens = shlex.split(part)
            except ValueError:
                tokens = part.split()
            while tokens and re.match(r"^[A-Za-z_]\w*=", tokens[0]):
                tokens = tokens[1:]
            if tokens:
                out.append((pending_no, tokens))
    return out


def pathlike(token: str) -> bool:
    if not token or token.startswith(("-", "<", "$", "~", "%", "http", "git@")) or any(c in token for c in "*?{}<>$"):
        return False
    return not os.path.isabs(token) and not re.match(r"^[A-Za-z]:[\\/]", token)


def check_readme_commands(root, readme: Path, findings):
    text = read_text(readme)
    base_dir = readme.parent
    me = repo_name(root)
    top = checkout_root(root)
    for _, block in shell_blocks(text):
        cwd = base_dir
        created = set()
        unknown_cwd = False
        own_clone = None  # folder name a clone of this very repository would create

        def candidates(token):
            if own_clone and (token == own_clone or token.startswith(own_clone + "/")):
                sub = token[len(own_clone):].lstrip("/")
                yield top / sub if sub else top
            for base in (cwd, base_dir, root):
                yield base / token
            # "run from the folder that contains this one": a path that starts with this README's own folder name
            if base_dir != root and token.startswith(base_dir.name + "/"):
                yield base_dir.parent / token

        def exists(token):
            if token in GENERATED or token.strip("./") in GENERATED:
                return True
            if Path(token).name in created or token in created:
                return True
            return any(c.exists() for c in candidates(token))

        def resolve(token):
            return next((c for c in candidates(token) if c.exists()), None)

        for no, tokens in commands(block):
            cmd = tokens[0].lower()
            args = tokens[1:]
            if cmd not in COMMAND_STARTS and not cmd.startswith("./"):
                continue

            def missing(token, kind):
                findings.append(Finding(
                    "missing-path", "REVIEW", rel(root, readme), no, f"{kind}: {token}",
                    "The README names a path that does not exist, so this step fails as written.",
                    "Fix the path, or add the file. If a copy or move changed the layout, update the instructions.",
                ))

            if cmd == "git" and args[:1] == ["clone"]:
                rest = [a for a in args[1:] if not a.startswith("-")]
                url = rest[0] if rest else ""
                name = re.sub(r"\.git$", "", url.rstrip("/").split("/")[-1]) if url else ""
                if name and name == me:
                    # Later steps start from the clone, which has the same layout as this checkout.
                    own_clone = rest[1] if len(rest) > 1 else name
                    continue
                if name:
                    findings.append(Finding(
                        "clones-other-repo", "NOTE", rel(root, readme), no, f"git clone {url}",
                        f"This README lives in '{me}' but tells readers to clone '{name}', so the steps may not use this code.",
                        "Point the clone and cd steps at this repository, or say that the instructions are for the original project.",
                    ))
                unknown_cwd = True  # later paths are relative to a clone we cannot see
                if len(rest) > 1:
                    created.add(rest[1])
                continue
            if unknown_cwd:
                continue
            if cmd == "cd" and args:
                target = args[0]
                if target == "..":
                    cwd = cwd.parent
                    continue
                if not pathlike(target) or target == "-":
                    unknown_cwd = True  # a placeholder or variable: where this leads is unknown
                    continue
                found = resolve(target)
                if found is None and not exists(target):
                    missing(target, "cd")
                    unknown_cwd = True
                elif found is not None and found.is_dir():
                    cwd = found
            elif cmd in ("python", "python3", "py") and args:
                if args[0] == "-m" and len(args) >= 3 and args[1] == "venv":
                    created.add(args[2])
                    continue
                if args[0] == "-m" and len(args) >= 2 and args[1] == "pip":
                    args = ["pip"] + args[2:]
                    cmd = "pip"
                else:
                    first = next((a for a in args if not a.startswith("-")), None)
                    if args[0] not in ("-m", "-c") and first and pathlike(first) and (first.endswith(".py") or "/" in first) and not exists(first):
                        missing(first, "python")
                    continue
            if cmd in ("pip", "pip3") and args:
                if "-r" in args and args.index("-r") + 1 < len(args):
                    target = args[args.index("-r") + 1]
                    if pathlike(target) and not exists(target):
                        missing(target, "pip -r")
            elif cmd == "streamlit" and args[:1] == ["run"] and len(args) > 1 and pathlike(args[1]) and not exists(args[1]):
                missing(args[1], "streamlit run")
            elif cmd == "node" and args and pathlike(args[0]) and not exists(args[0]):
                missing(args[0], "node")
            elif cmd in ("bash", "sh") and args and pathlike(args[0]) and not exists(args[0]):
                missing(args[0], cmd)
            elif cmd == "cp" and len(args) >= 2:
                src = args[0]
                if pathlike(src) and not exists(src):
                    missing(src, "cp")
                created.add(Path(args[-1]).name)
            elif cmd == "mkdir" and args:
                created.update(Path(a).name for a in args if not a.startswith("-"))
            elif cmd in ("npm", "yarn", "pnpm"):
                script = None
                if cmd == "npm" and args[:1] == ["run"] and len(args) > 1:
                    script = args[1]
                elif cmd in ("yarn", "pnpm") and args and args[0] not in ("install", "add", "run", "test", "start", "build", "dev"):
                    script = args[0]
                elif cmd in ("yarn", "pnpm") and args[:1] == ["run"] and len(args) > 1:
                    script = args[1]
                if script:
                    pkg = next((b / "package.json" for b in (cwd, base_dir, root) if (b / "package.json").is_file()), None)
                    if pkg is not None:
                        try:
                            scripts = json.loads(read_text(pkg)).get("scripts", {})
                        except ValueError:
                            scripts = {}
                        if script not in scripts:
                            findings.append(Finding(
                                "missing-script", "REVIEW", rel(root, readme), no, f"{cmd} run {script}  (not in {rel(root, pkg)})",
                                "package.json has no script with this name, so the command fails.",
                                "Add the script, or fix the name in the README.",
                            ))


# --------------------------------------------------------------------------- python source

def parse_python(root, files, findings):
    trees = {}
    for path in files:
        if path.suffix != ".py":
            continue
        text = read_text(path)
        try:
            trees[path] = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
    return trees


def has_future_annotations(tree):
    return any(isinstance(n, ast.ImportFrom) and n.module == "__future__" and any(a.name == "annotations" for a in n.names) for n in tree.body)


def required_python(tree):
    """Return a list of ((major, minor), line, reason) features that need a newer Python."""
    found = []
    future = has_future_annotations(tree)
    match_node = getattr(ast, "Match", None)
    star_node = getattr(ast, "TryStar", None)

    def annotation_features(ann, line):
        for n in ast.walk(ann):
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr):
                found.append(((3, 10), line, "'X | Y' in a type annotation"))
                return
            if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id in BUILTIN_GENERICS:
                found.append(((3, 9), line, f"'{n.value.id}[...]' in a type annotation"))
                return

    for node in ast.walk(tree):
        if match_node is not None and isinstance(node, match_node):
            found.append(((3, 10), node.lineno, "a match statement"))
        elif star_node is not None and isinstance(node, star_node):
            found.append(((3, 11), node.lineno, "except*"))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("removeprefix", "removesuffix"):
            found.append(((3, 9), node.lineno, f".{node.func.attr}()"))
        elif not future and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            anns = [a.annotation for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs if a.annotation is not None]
            if node.returns is not None:
                anns.append(node.returns)
            for ann in anns:
                annotation_features(ann, node.lineno)
    return found


def check_python_versions(root, files, trees, findings):
    readmes = [p for p in files if is_readme(p)]
    readme_dirs = {p.parent for p in readmes}
    for readme in readmes:
        text = read_text(readme)
        claim = None
        for line_no, line in enumerate(text.splitlines(), 1):
            for pattern in PY_CLAIM_RES:
                m = pattern.search(line)
                if m:
                    claim = (tuple(int(x) for x in m.group(1).split(".")), line_no, m.group(0).strip())
                    break
            if claim:
                break
        if not claim:
            continue
        for path, tree in trees.items():
            if readme.parent not in path.parents and path.parent != readme.parent:
                continue
            # Skip code that belongs to a nested project with its own README.
            nested = any(d != readme.parent and d in path.parents and readme.parent in d.parents for d in readme_dirs)
            if nested:
                continue
            feats = [f for f in required_python(tree) if f[0] > claim[0]]
            if feats:
                (ver, line, why) = max(feats, key=lambda f: f[0])
                findings.append(Finding(
                    "python-version", "REVIEW", rel(root, path), line,
                    f"needs Python {ver[0]}.{ver[1]}+ ({why}), but {rel(root, readme)}:{claim[1]} says \"{claim[2]}\"",
                    "On the promised Python version this file fails to import or run.",
                    "Raise the stated minimum version, or rewrite the syntax for the older version.",
                ))


def stdlib_names():
    names = getattr(sys, "stdlib_module_names", None)
    if names:
        return set(names)
    return {
        "abc", "argparse", "ast", "asyncio", "base64", "collections", "concurrent", "contextlib", "copy", "csv", "dataclasses",
        "datetime", "enum", "functools", "glob", "hashlib", "heapq", "html", "http", "importlib", "inspect", "io", "itertools",
        "json", "logging", "math", "multiprocessing", "operator", "os", "pathlib", "pickle", "platform", "queue", "random", "re",
        "shutil", "signal", "socket", "sqlite3", "ssl", "statistics", "string", "subprocess", "sys", "tempfile", "textwrap",
        "threading", "time", "traceback", "types", "typing", "unittest", "urllib", "uuid", "warnings", "weakref", "xml", "zipfile",
    }


def module_candidates(package):
    base = package.lower()
    cands = {m.lower() for m in ALIASES.get(base, [])}
    cands.add(base.replace("-", "_").replace(".", "_"))
    for suffix in ("-ai", "-py", "-sdk", "-python"):
        if base.endswith(suffix):
            cands.add(base[: -len(suffix)].replace("-", "_"))
    if base.startswith("python-"):
        cands.add(base[len("python-"):].replace("-", "_"))
    cands.add(base.split("-")[0])
    return cands


def requirement_names(path: Path):
    names = set()
    for line in read_text(path).splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith("-"):
            name = re.split(r"[\[<>=!~;\s@]", line, maxsplit=1)[0].strip()
            if name:
                names.add(name)
    return names


def project_dir(path: Path, root: Path, markers):
    """Nearest ancestor directory of path (inside root) that contains a file matching markers."""
    for d in [path.parent] + list(path.parents):
        if root not in (d, *d.parents):
            break
        if any(markers(f) for f in d.iterdir() if f.is_file()):
            return d
    return None


def is_test_file(path: Path):
    return any(p.lower().startswith("test") for p in path.parts) or path.name.startswith("test_") or path.name.endswith("_test.py")


def check_requirements(root, files, trees, findings):
    # Anything the repo itself provides: a module file, or a folder that holds Python files.
    local = {p.stem for p in files if p.suffix == ".py"} | {p.parent.name for p in files if p.suffix == ".py"}
    std = stdlib_names()
    is_req = lambda f: bool(re.match(r"^requirements.*\.txt$", f.name, re.I))
    reported = set()
    for path, tree in trees.items():
        if is_test_file(path.relative_to(root)):
            continue
        pdir = project_dir(path, root, is_req)
        if pdir is None:
            continue
        reqs = set()
        for f in pdir.iterdir():
            if f.is_file() and is_req(f):
                reqs |= requirement_names(f)
        cands = set()
        for r in reqs:
            cands |= module_candidates(r)
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods = [node.module.split(".")[0]]
            for mod in mods:
                low = mod.lower()
                if mod in std or mod == "__future__" or low in cands or mod in local:
                    continue
                key = (pdir, low)
                if key in reported:
                    continue
                reported.add(key)
                findings.append(Finding(
                    "missing-requirement", "NOTE", rel(root, path), node.lineno, f"imports '{mod}', which {rel(root, pdir)}/requirements*.txt does not list",
                    "Installing only the listed requirements would leave this import failing, unless another package pulls it in.",
                    "Add it to requirements, or confirm another listed package provides it.",
                ))


# Only reads that must succeed count. Assignments (os.environ["X"] = key) set a variable
# rather than read one, and a read with a default is optional by construction.
ENV_RES = [
    re.compile(r"""os\.environ\.get\(\s*["']([A-Z][A-Z0-9_]+)["']\s*\)"""),
    re.compile(r"""os\.environ\[\s*["']([A-Z][A-Z0-9_]+)["']\s*\](?!\s*=[^=])"""),
    re.compile(r"""os\.getenv\(\s*["']([A-Z][A-Z0-9_]+)["']\s*\)"""),
]


def check_env(root, files, findings):
    docs_cache = {}

    def docs_for(pdir):
        if pdir not in docs_cache:
            text = ""
            for f in pdir.iterdir():
                if f.is_file() and (is_readme(f) or f.name.startswith(".env") or f.suffix.lower() == ".md"):
                    text += read_text(f) + "\n"
            docs_cache[pdir] = text
        return docs_cache[pdir]

    seen = set()
    for path in files:
        if path.suffix != ".py" or is_test_file(path.relative_to(root)):
            continue
        pdir = project_dir(path, root, is_readme)
        if pdir is None:
            continue
        text = read_text(path)
        for pattern in ENV_RES:
            for m in pattern.finditer(text):
                var = m.group(1)
                if var in SYSTEM_ENV or (pdir, var) in seen:
                    continue
                if re.search(rf"\b{re.escape(var)}\b", docs_for(pdir)):
                    continue
                seen.add((pdir, var))
                line = text[: m.start()].count("\n") + 1
                findings.append(Finding(
                    "undocumented-env", "NOTE", rel(root, path), line, f"reads {var}, which no README or .env file in {rel(root, pdir) or '.'} mentions",
                    "A new user cannot know to set it.",
                    "Document it in the README or add it to .env.example.",
                ))


# --------------------------------------------------------------------------- main

SEVERITY_ORDER = {"REVIEW": 0, "NOTE": 1}


def audit(repo) -> dict:
    root = Path(repo).resolve()
    files = list(walk_repo(root))
    findings = []
    for readme in (p for p in files if is_readme(p)):
        check_readme_commands(root, readme, findings)
    trees = parse_python(root, files, findings)
    check_python_versions(root, files, trees, findings)
    check_requirements(root, files, trees, findings)
    check_env(root, files, findings)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.file, f.line, f.check))
    counts = {}
    for f in findings:
        counts[f.check] = counts.get(f.check, 0) + 1
    return {
        "version": VERSION,
        "repo": str(root),
        "readmes": sum(1 for p in files if is_readme(p)),
        "python_files": len(trees),
        "summary": counts,
        "review": sum(1 for f in findings if f.severity == "REVIEW"),
        "notes": sum(1 for f in findings if f.severity == "NOTE"),
        "findings": [f.as_dict() for f in findings],
    }


def render_text(report: dict) -> str:
    out = [
        f"quickstart-checker {report['version']}: {report['repo']}",
        f"Read {report['readmes']} README file(s) and {report['python_files']} Python file(s).",
        f"{report['review']} to review, {report['notes']} notes. These are leads, not verdicts.",
    ]
    for f in report["findings"]:
        out += ["", f"[{f['severity']}] {f['check']}  {f['file']}:{f['line']}", f"  evidence: {f['evidence']}", f"  why: {f['why']}", f"  fix: {f['fix']}"]
    return "\n".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check whether a README quick start can work, without running it.")
    parser.add_argument("--repo", default=".", help="Repository path (default: current directory)")
    parser.add_argument("--json", action="store_true", help="Print JSON")
    parser.add_argument("--fail-on", choices=["review", "note"], help="Exit 1 if a finding of this level or worse exists")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
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
