---
name: quickstart-checker
description: >-
  Checks whether a repository's README quick start can work, without running
  anything. Verifies that the files and folders named in setup commands exist,
  that npm run scripts exist, that the README does not send readers to a
  different repository, that the Python version it promises matches the syntax
  the code uses, that imported packages are listed in requirements, and that
  environment variables the code reads are documented. Use when the user asks
  whether the setup or install instructions in a repo are broken or stale, will
  break for a new user, whether a quick start still works after a project was
  copied or moved, or before publishing or sharing a repo. Operates locally and
  offline. Reports leads to check, not verdicts.
license: Apache-2.0
metadata:
  version: "1.0.0"
---

# Quickstart Checker

A README quick start rots quietly. A project gets copied into a new repo and its
`cd` paths point at folders that no longer exist. A setup line promises "Python
3.8+" while the code needs 3.9. A required key is never mentioned. A new user hits
these first, and they are cheap to find by reading the commands against the files.

A script does the deterministic part. You judge each lead: a real break, a stale
instruction left over from a move, or a false positive.

The script reads files only. It never runs the commands in the README, makes no
network calls, and changes nothing.

## When to use

- Before publishing or sharing a repo, to catch setup steps that would fail
- After copying, moving or renaming a project, when its README may be stale
- When a new user reports that the install steps did not work
- When adopting an open-source project and you want to know if its README is trustworthy

## When not to use

- Actually running the setup to see if it works. This only reads, and a real run needs the user's agreement
- Checking whether the README's numbers or claims are true (use the claim-auditor skill for that)
- Languages other than Python for the code checks. README and `package.json` checks work for any repo

## Run the check

```bash
python3 scripts/quickstart_check.py --repo /path/to/repo --json
```

Use `--fail-on review` to make the exit code 1 when any REVIEW finding exists. Without
it the exit code is 0 unless the path is invalid (2).

## Read the output

Every finding is a lead.

- **REVIEW**: the step fails as written. `missing-path`, `missing-script`, `python-version`.
- **NOTE**: worth a look. `clones-other-repo`, `missing-requirement`, `undocumented-env`.

[references/checks.md](references/checks.md) explains each check, what a false positive
looks like, and the usual fix. Read the entry before judging a lead.

## Judge each lead

Open the file at the reported line and read the surrounding steps. Then sort it:

1. **Real break**: the path, script or version is wrong for this repository.
2. **Stale after a move**: the instruction was right for the original layout. This is the most common cause of `missing-path` and `clones-other-repo` in copied projects.
3. **False positive**: say why in one line. For example, a package that another listed package installs, or a variable that is optional.

Settle a lead by reading. Do not run the README's commands to find out, because that runs
unfamiliar code on the user's machine with their keys.

## Report

Give the user:

- A one-line verdict on whether a new reader could follow the quick start
- **Real breaks** and **stale instructions** with `file:line` and the one-line fix
- **Dismissed** leads with the reason, so they can disagree
- What was not checked: running the steps, non-Python code, and instructions that are not in code blocks

Do not edit the README unless asked. If asked, fix stale paths and clone steps to point at
this repository, and keep the README's other wording.

## Files

```
quickstart-checker/
├── SKILL.md
├── README.md
├── scripts/
│   └── quickstart_check.py    # the checks; standard library only
└── references/
    └── checks.md              # each check, false positives, how to resolve
```
