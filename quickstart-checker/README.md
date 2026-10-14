# 🧭 quickstart-checker

**Would a new reader be able to follow this README?** Checks whether a quick start can work, by reading the commands against the files. It never runs anything.

An agent skill (a `SKILL.md` plus a script) for Claude Code, Codex, Cursor and other agents that read the [agentskills.io](https://agentskills.io) format. The deterministic checks run as a script and the agent does the judging.

This is an original skill, not adapted from another project.

## Why it exists

Projects copied out of a larger repo keep their old setup steps. Run on a collection of copied agent demos, it found:

- A `cd advanced_ai_agents/multi_agent_apps/devpulse_ai` step for a folder that does not exist in the new repo.
- Nine READMEs that still told readers to clone the original collection, so a reader would get the original project instead of the copy.
- A README promising "Python 3.8+" for code that uses `tuple[bool, str]` in a function signature, which needs Python 3.9. On 3.8 the file fails to import.

A person finds these by following the steps. This finds the candidates in a second.

Run on the original awesome-llm-apps collection it also found these, each checked by hand against the repository: a `cd` into a folder that exists nowhere in the repo, a `cd` missing a path segment, a README that says to `cp .env.example .env` when no such file exists, and the same Python 3.9 syntax against a 3.8 promise (confirmed by reading the code, not by running 3.8).

## What it checks

| Check | Level | Finds |
|---|---|---|
| `missing-path` | REVIEW | A file or folder named in a README command that does not exist |
| `missing-script` | REVIEW | `npm run X` where `package.json` has no script `X` |
| `python-version` | REVIEW | A promised Python version older than the syntax needs |
| `clones-other-repo` | NOTE | A README that tells you to clone a different repository |
| `missing-requirement` | NOTE | A third-party import that requirements does not list |
| `undocumented-env` | NOTE | An environment variable the code reads that no README or `.env` mentions |

Details, false positives and fixes: [references/checks.md](references/checks.md).

## Use it

```bash
python3 scripts/quickstart_check.py --repo /path/to/repo           # readable report
python3 scripts/quickstart_check.py --repo /path/to/repo --json    # for tools
python3 scripts/quickstart_check.py --repo . --fail-on review      # exit 1 in CI if a step would fail
```

Python 3.8 or newer, standard library only. It reads files and nothing else: it does not run the README's commands, make network calls or modify anything.

To use it as a skill, copy this folder into your agent's skills directory (`~/.claude/skills/`, `~/.codex/skills/`, `~/.cursor/skills/`, or `.agents/skills/` in a repo). Read `SKILL.md` and the script first, as you should with any skill.

## Example

```
[REVIEW] missing-path  agents/devpulse-signal-intelligence/README.md:97
  evidence: cd: advanced_ai_agents/multi_agent_apps/devpulse_ai
[REVIEW] python-version  agents/multi-agent-trust-layer/multi_agent_trust_layer.py:396
  evidence: needs Python 3.9+ ('tuple[...]' in a type annotation), but agents/multi-agent-trust-layer/README.md:35 says "Python 3.8+"
[NOTE] clones-other-repo  agents/agent-chess-arena/README.md:33
  evidence: git clone https://github.com/Shubhamsaboo/awesome-llm-apps.git
```

## Limits, stated plainly

- It reads the steps; it does not run them. A clean report does not mean the quick start works.
- The code checks cover Python only. The README and `package.json` checks work for any repo.
- The checks are heuristics. A package installed by another listed package, or a variable documented somewhere the script does not look, will show up as a false positive. The package-to-import alias table is small.
- Written for Python 3.8 or newer, but only run on 3.13.

## Tests

```bash
python3 evals/quickstart-checker/test_quickstart_check.py     # from the repo root; 49 tests, about a second
```

The tests cover what each check flags and, just as important, what it must not flag. They were also run against deliberately broken copies of the script to confirm they fail when a check stops working.
