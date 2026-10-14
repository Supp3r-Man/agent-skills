# 🔍 claim-auditor

**Does this demo's number come from anywhere?** Checks a repository's README claims against the code that is supposed to produce them.

An agent skill (a `SKILL.md` plus a script) for Claude Code, Codex, Cursor and other agents that read the [agentskills.io](https://agentskills.io) format. The deterministic checks run as a script and the agent does the judging, so the findings are repeatable and do not depend on a model's mood.

This is an original skill, not adapted from another project.

## Why it exists

While vetting open-source LLM demos, the same problems kept appearing:

- A "with library" demo whose compressed output was a hand-picked slice of a list, and which never called the library. It printed a claimed 93.7% saving that was just arithmetic on a rigged list.
- A README that called 63.9% a *token* saving and, further down, called the same 63.9% a *size* saving. The token figure was 54.1%.
- An app showing benchmark numbers as typed-in strings.
- Token counts estimated as `len(text) // 4`.

A person finds these by reading carefully. This finds the candidates quickly.

## What it checks

| Check | Level | Finds |
|---|---|---|
| `typed-literal` | REVIEW | A percentage typed into a displayed string or a metric-named variable |
| `library-not-imported` | REVIEW | A listed package that no file imports, but whose import is printed in a string |
| `mixed-labels` | REVIEW | One number called both a token saving and a size saving |
| `token-estimate` | NOTE | A token count computed as `len(x) // 4` |
| `unsourced-figure` | NOTE | A README percentage, cost or multiplier ("20x cheaper") with no hint of its source |
| `strong-wording` | NOTE | "verified", "proven", "real API calls" with no tests in the repo |
| `unparsed-file` | NOTE | A Python file that could not be parsed |

Details, false positives and fixes: [references/checks.md](references/checks.md).

## Use it

```bash
python3 scripts/claim_audit.py --repo /path/to/repo           # readable report
python3 scripts/claim_audit.py --repo /path/to/repo --json    # for tools
python3 scripts/claim_audit.py --repo . --fail-on review      # exit 1 in CI if anything needs review
```

Python 3.8 or newer, standard library only. It reads files and nothing else: it does not run the repository's code, make network calls or modify anything.

A typed-in figure that is deliberately quoted from elsewhere can be acknowledged with a `# claim-audit: quoted` comment on its line, so it stops showing up.

To use it as a skill, copy this folder into your agent's skills directory (`~/.claude/skills/`, `~/.codex/skills/`, `~/.cursor/skills/`, or `.agents/skills/` in a repo). Read `SKILL.md` and the script first, as you should with any skill.

## Example

Run on the original, unmodified Headroom demo from awesome-llm-apps:

```
[REVIEW] library-not-imported  headroom_demo.py:147
  evidence: headroom-ai is in requirements.txt:1 but no file imports it; its import or use appears only inside a string
[REVIEW] typed-literal  headroom_demo.py:182
  evidence: 50-90% (shown by print())
[NOTE] token-estimate  headroom_demo.py:58
  evidence: len(...) // 4 used as a token count
```

## Limits, stated plainly

- It cannot tell whether a computed number is *right*, only where numbers come from.
- Python and Markdown only.
- The checks are heuristics. Expect some false positives, such as a package imported under a different name than its package name. The alias table is small.
- A clean report means these checks found nothing, not that the claims are true.

## Tests

```bash
python3 evals/claim-auditor/test_claim_audit.py     # from the repo root; 33 tests, about a second
```

The tests cover what each check flags and, just as important, what it must not flag. They were also run against deliberately broken copies of the script to confirm they fail when a check stops working.
