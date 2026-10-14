# Agent Skills

Two original agent skills in the open [SKILL.md](https://agentskills.io) format, for Claude Code, Codex, Cursor and other agents that read it.

Each skill is a folder with a `SKILL.md`, a script that does the deterministic work, and references that load on demand. Each has an executable test.

| Skill | What it does |
|---|---|
| [🧭 quickstart-checker](quickstart-checker/) | Checks whether a README's quick start can work, by reading its commands against the files: missing paths and scripts, stale clone steps after a copy, a Python version the code does not meet, unlisted imports, undocumented variables |
| [🔍 claim-auditor](claim-auditor/) | Checks a repository's README claims against the code behind them: typed-in numbers, demos that never import the library they advertise, token counts estimated as `len // 4`, mislabeled figures, unsourced claims |

## Install

Copy a skill folder into your agent's skills directory:

| Agent | Skills dir |
|---|---|
| Claude Code | `~/.claude/skills/` |
| Codex | `~/.codex/skills/` |
| Cursor | `~/.cursor/skills/` |
| Project-level (shared) | `.agents/skills/` in your repo |

Skills run with your agent's permissions. Read the `SKILL.md` and every script before installing, including these.

## Test

```bash
python3 evals/claim-auditor/test_claim_audit.py
python3 evals/quickstart-checker/test_quickstart_check.py
```

## Credit

The folder layout (skill, scripts, references, evals) and the idea of testing skills as code follow the conventions of the [agent_skills](https://github.com/Shubhamsaboo/awesome-llm-apps/tree/main/agent_skills) collection in awesome-llm-apps (Apache-2.0). No code was copied from it. Its structural linter and security scanner were used only to check this skill, and are not included here.

Licensed under the Apache License 2.0. See [LICENSE](LICENSE).
