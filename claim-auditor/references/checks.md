# The checks

Every check produces a lead, not a verdict. Severity is how likely the lead is to
mislead if it turns out to be real.

## typed-literal (REVIEW)

A percentage typed into a string that is displayed (`print`, `st.metric`,
`st.markdown`, `st.write` and similar), a dict value under a metric-like key, or a
variable whose name suggests a measurement (`savings`, `reduction`, `accuracy`,
`benchmark`, `result`, and so on).

- **Why it matters:** a number that is typed cannot change when the code runs. A
  "live" dashboard that shows `"63.9%"` is showing a constant.
- **Real example:** an app that calls `st.metric("Avg Size Reduction", "63.9%")`.
- **False positives:** a static results table that is clearly labeled as such; a
  threshold in a prompt ("flag anything above 90%").
- **Not flagged:** docstrings, `100%` and `0%`, CSS such as `width: 80%`, f-strings
  where the number is a placeholder (`f"{pct:.1f}%"`), a line carrying the comment
  `# claim-audit: quoted`, and a string whose own text credits someone else
  (*reports*, *according to*, *claims*, *quoted*, *vendor*). The word *measured* does
  not silence it, because a typed-in number that says "measured" is the problem.
- **Resolve:** compute the figure from a measurement the code performs. If it is
  genuinely quoted from elsewhere, say so in the text, or add `# claim-audit: quoted`
  to the line so the next audit knows it was a deliberate choice.

## library-not-imported (REVIEW)

A package listed in a `requirements*.txt` that no Python file imports, while a
string literal contains an import or use of it (`from lib import X`, `lib.func`).

- **Why it matters:** a demo that only *prints* code about a library is not
  exercising it. Any numbers it shows were produced by something else.
- **Real example:** a "with Headroom" demo whose requirements list `headroom-ai`
  but which never imports it. The printed text includes `from headroom.integrations
  import HeadroomChatModel`, and the "compressed" list was built by hand.
- **False positives:** a package that is imported under a different name than its
  package name, when the skill does not know the alias. The alias table is small.
  A package used only through a CLI or plugin can also trigger it. The check
  needs two things to fire: no file imports the package, and a string contains an
  import or use of it. A bare mention like `pip install somelib` does not count.
- **Resolve:** call the library for real, or say the demo is illustrative.

## mixed-labels (REVIEW)

The same percentage is described as a token saving on one line and a size saving
(bytes, characters, payload) on another.

- **Why it matters:** cost follows tokens, not bytes. The two usually differ.
- **Real example:** "63.9% average token reduction" at the top of a README and
  "63.9% average size reduction" in its performance section, where the token figure
  was 54.1%.
- **False positives:** a line that mentions both words is skipped as ambiguous.
- **Resolve:** use each label for the figure it describes.

## token-estimate (NOTE)

`len(text) // 4` or `len(text) / 4` used as a token count.

- **Why it matters:** characters divided by four is a rule of thumb. It is fine for
  a back-of-envelope guess and wrong for a published saving.
- **Resolve:** use the model's tokenizer (`tiktoken` for OpenAI models, the
  provider's counter otherwise) before quoting a number.

## unsourced-figure (NOTE)

A percentage, or a dollar amount, in a README, next to savings or performance wording
(*saves*, *reduction*, *faster*, *cost*, *accuracy* and similar), with no hint of its
source on the same line, in the header of its table, or in the four non-empty lines
above it. Example dialogue and spec tables are not claims, so they are skipped. Hints include *reported*,
*according to*, *measured*, *benchmark*, *illustrative*, *estimate*, *sample*,
*reproduce*, *not re-run* and *project-reported*.

- **Why it matters:** readers cannot tell measured from quoted from guessed.
- **False positives:** a source stated further away, in a footnote, or in a
  different file.
- **Resolve:** add the source in plain words. "Measured with `python demo.py` on
  <date>" and "reported by the vendor, not re-run" are both fine. Hiding the source
  is what this check exists to catch.
- **Not flagged:** `100%` and `0%`.

## strong-wording (NOTE)

Words like *verified*, *proven*, *proof*, *guarantee*, *real API calls*, *not
estimates*, *production-ready* or *battle-tested* in a README, in a repository with
no test, eval or benchmark file or directory (any path part starting with `test`,
`eval` or `bench`, or ending in `_test.py`).

- **Why it matters:** the wording promises evidence the repo does not contain.
- **False positives:** evidence that lives elsewhere (a separate repo, CI config).
- **Resolve:** add the test or benchmark, or soften the wording.

## unparsed-file (NOTE)

A `.py` file with a syntax error. It was skipped, so its claims were not checked.
Python 2 files and templates that contain Python are common causes.

## What the skill cannot tell you

- Whether a computed number is *right*. It only sees where numbers come from.
- Anything in JavaScript, notebooks or other languages.
- Whether the model's answers are good. It does not evaluate quality.
- Claims made only in images, videos or a website.

A clean report means these checks found nothing, not that the claims are true.
