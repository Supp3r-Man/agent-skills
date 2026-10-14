# The checks

Every check produces a lead, not a verdict. Severity is how likely the lead is to stop a
new reader if it is real.

## What the script reads

Fenced code blocks in README files whose language is a shell (bash, sh, shell, console,
powershell, cmd, or no language). Each line is cleaned (prompt characters, comments and
backslash continuations removed) and split on `&&` and `;`. The script tracks `cd` as it
goes, so a path after `cd app` is looked for inside `app`. Paths are resolved against
that working directory, then the README's folder, then the repository root. A path that
starts with the README's own folder name (`python3 my-skill/run.py` in `my-skill/README.md`)
is also tried from that folder's parent, because it means "run this from the folder that
contains this one".

After a `git clone` of this repository's own URL, paths such as `cd mine/apps/web` are
checked against this repository's layout, and the files the following steps name are
checked inside the folder the steps `cd` into. After a clone of any other repository, or
after a `cd` to a placeholder or variable (`cd <folder>`, `cd $DIR`), the working directory
is unknown and the rest of that block is not guessed at.

Python code blocks, JSON blocks and prose are not read.

## missing-path (REVIEW)

A command names a file or folder that does not exist. Covered commands: `cd`,
`python X.py`, `pip install -r X`, `streamlit run X`, `node X`, `bash X`, and the source
of `cp`.

- **Why it matters:** the step fails as written.
- **Not flagged:** placeholders (`<your-folder>`), variables (`$HOME`), URLs, absolute and
  `~` paths, wildcards, commands that appear after `git clone` (the working directory is
  then a clone the script cannot see), and anything an earlier step in the same block
  creates (`mkdir`, `python -m venv`, the destination of `cp`). `.env`, `venv`, `.venv`,
  `node_modules`, `dist` and `build` are treated as generated.
- **After a failed `cd`:** the rest of that block is not checked, because the working
  directory is unknown. You get one finding, not a chain of consequences.
- **False positives:** a file that the setup downloads or generates in a way the script
  cannot see.
- **Resolve:** fix the path or add the file. After copying a project out of a larger repo,
  update every `cd` to the new layout.

## missing-script (REVIEW)

`npm run X` (or `yarn X`, `pnpm run X`) where the nearest `package.json` has no script `X`.

- **Why it matters:** the command fails.
- **Not checked:** repositories with no `package.json`, and the built-ins (`npm start`,
  `npm test`, `npm install`).
- **Resolve:** add the script or correct the name.

## clones-other-repo (NOTE)

The README tells you to `git clone` a repository whose name is not the one it lives in.
The repository's own name comes from `.git/config` when present, otherwise from the
folder name.

- **Why it matters:** a reader who follows the steps gets the original project, not this
  copy. Any fixes made here are never used.
- **Real example:** an app copied out of a collection whose README still says to clone
  the collection and `cd` into the app's old folder.
- **False positives:** a project that really does depend on cloning a second repository
  (a data set, a plugin, a submodule).
- **Resolve:** point the clone and `cd` steps at this repository, or say plainly that the
  steps are for the original project.

## python-version (REVIEW)

The README promises a minimum Python version ("Python 3.8+", "requires Python 3.9", "3.10
or higher"), and code under it uses syntax that needs a newer one. Detected:

| Needs | Feature |
|---|---|
| 3.9 | `list[int]`, `dict[...]`, `tuple[...]` in a function's annotations; `.removeprefix()` / `.removesuffix()` |
| 3.10 | `X \| Y` in a function's annotations; `match` statements |
| 3.11 | `except*` |

Annotation features are ignored when the file has `from __future__ import annotations`,
because the annotations are then never evaluated at definition time.

- **Why it matters:** on the promised version the file fails to import.
- **False positives:** a version claim that is only a recommendation; a file that is not part
  of the quick start.
- **Not checked:** features not in the table, and claims in `pyproject.toml`.
- **Resolve:** raise the stated minimum, or rewrite the syntax (`Tuple[...]`, `Optional[...]`).

## missing-requirement (NOTE)

A Python file imports a third-party package that no `requirements*.txt` in its project
folder lists. Standard-library modules, modules the repository itself provides, and test
files are skipped. Package names are mapped to import names with a small alias table
(`pillow` to `PIL`, `python-dotenv` to `dotenv`, and so on).

- **Why it matters:** installing only the listed requirements leaves the import failing.
- **False positives:** a package installed as a dependency of another listed package (a
  reasonable thing to rely on, but fragile); a package whose import name is not in the
  alias table.
- **Resolve:** list it, or confirm which package provides it.

## undocumented-env (NOTE)

Code reads an environment variable that no README or `.env*` file in the same project
folder mentions. Only reads that must succeed count: `os.environ["X"]`,
`os.environ.get("X")` and `os.getenv("X")` with no default.

- **Not flagged:** assignments (`os.environ["X"] = key` sets a variable, it does not read
  one), reads with a default (optional by construction), and common system variables
  (`PATH`, `HOME`, `USER`, and similar).
- **False positives:** a variable documented in a file the script does not read, such as a
  docs folder or a wiki.
- **Resolve:** document it, or add it to `.env.example`.

## What the skill cannot tell you

- Whether the steps actually work when run. It reads, it does not execute.
- Anything in prose, images or video.
- Code in languages other than Python (the README and `package.json` checks still work).
- Whether a required key is valid, or a service is reachable.

A clean report means these checks found nothing, not that the quick start works.
