---
name: claim-auditor
description: >-
  Audits whether a repo backs up the claims in its README. Checks the savings,
  speedup, accuracy and cost figures against the code that is supposed to
  produce them. Finds percentages typed into code instead of computed, demos
  that advertise a library but never import it, token counts estimated as
  characters divided by four, one number labeled both a token saving and a size
  saving, README figures with no stated source, and strong wording such as
  "verified" in a repo with no tests. Use when the user asks whether a demo's
  numbers are real, whether a repo actually backs up its savings claims, to
  check a README for overclaiming, or to vet an open-source LLM or agent project
  before adopting or republishing it. Operates locally and offline. Reports
  leads to check, not verdicts.
license: Apache-2.0
metadata:
  version: "1.0.0"
---

# Claim Auditor

Demos love a big number. "93.7% fewer tokens", "47-92% savings, verified". This
skill checks whether the repository can actually back the claim. A script does
the deterministic part (parsing and pattern checks) and you do the judgment: for
each lead, decide whether it is a real problem, a quoted figure that only needs a
label, or a false positive.

The script reads files only. It never runs the repository's code, makes no
network calls, and changes nothing.

## When to use

- The user wants to know whether an open-source demo's numbers are real
- Before adopting, forking or republishing an LLM, agent or benchmark project
- Before writing your own README, to catch figures you cannot yet source
- When a README quotes savings, speedups, accuracy or cost and the user is unsure

## When not to use

- Judging whether a model's answers are correct or good (this does not evaluate quality)
- Languages other than Python (the code checks) and Markdown or text (the README checks)
- Verifying a number by re-running a benchmark. That is a separate step and needs the user's say-so

## Run the audit

```bash
python3 scripts/claim_audit.py --repo /path/to/repo --json
```

Use `--fail-on review` to make the exit code 1 when any REVIEW finding exists
(handy in CI). Without it the exit code is 0 unless the path is invalid (2).

## Read the output

Findings come in two levels, and every one is a lead:

- **REVIEW**: likely to mislead if real. `typed-literal`, `library-not-imported`, `mixed-labels`.
- **NOTE**: worth a look. `token-estimate`, `unsourced-figure`, `strong-wording`, `unparsed-file`.

[references/checks.md](references/checks.md) explains each check, what a false
positive looks like, and how to resolve it. Read the entry before judging a lead.

## Judge each lead

For every REVIEW finding, open the file at the reported line and read the
surrounding code or README. Then sort it:

1. **Confirmed**: the figure is typed in, the library is never used, or the label is wrong.
2. **Quoted, needs a label**: the number comes from somewhere real (the vendor, a paper) but the README states it as if measured here. Suggest wording that credits the source, or `# claim-audit: quoted` on a typed-in figure in code.
3. **False positive**: say why in one line (for example, the package imports under a different module name).

Work from the code. Do not run the repository's demo to settle a lead unless the
user agrees, because running unfamiliar code uses their machine and keys.

## Report

Give the user:

- A one-line verdict on how well the repo backs its claims, in plain words
- **Confirmed** problems with `file:line` and the one-sentence reason
- **Quoted figures** that need a source label, with a suggested wording
- **Dismissed** leads with the reason, so they can disagree
- What was not checked: other languages, and anything that needs running the code

Do not rewrite the README or the code unless asked. If asked, prefer the honest
fix: compute the number from a real run, or label it as quoted.

## Files

```
claim-auditor/
├── SKILL.md
├── README.md
├── scripts/
│   └── claim_audit.py        # the checks; standard library only
└── references/
    └── checks.md             # each check, false positives, how to resolve
```
