# Contributing

This document covers the developer side of the repository: getting the
container running, the quality gate, commit and pull request rules,
dependencies, tests, types, and what CI does with a change.
[README.md](README.md) covers the tool itself.

## Setup

**Prerequisites**: [Docker](https://docs.docker.com/get-docker/),
[VS Code](https://code.visualstudio.com/), and the
[Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers).
No Python and no uv on the host.

### Git identity and the GitHub token

`.devcontainer/.env` holds the author details commits in this checkout
carry:

```bash
GIT_AUTHOR_NAME="Your Name"
GIT_AUTHOR_EMAIL="you@example.com"
```

Edit it to your own identity. The file is gitignored, so it stays local
to your checkout; `.devcontainer/.env.example` is the committed copy and
carries placeholders, and anyone who clones this repository copies it and
fills in their own.

The container receives these values, and `entrypoint.sh` applies them, so
commits made inside the container carry the right author. They must not be
empty: git reads them directly and they outrank `user.name`, so a blank
value fails every commit with `fatal: empty ident name`.

A `GH_TOKEN` in the same file authenticates `gh` inside the container, and
`entrypoint.sh` points git at `gh`'s credential helper on start-up so
pushes work without a second sign-in. Without it, `git push` fails with
`could not read Username for 'https://github.com'`.

### Option 1: VS Code Dev Container (Recommended)

Open the folder in VS Code, then click **"Reopen in Container"** or use
the Command Palette (`Cmd/Ctrl+Shift+P`) and run
**"Dev Containers: Reopen in Container"**.

On first start the container syncs the environment (`uv sync`) and
installs the pre-commit hooks. Both are automatic.

### Option 2: Docker Compose

Run the container directly with Docker Compose:

```bash
# Build and start the container
docker compose -f .devcontainer/compose.yaml up -d --build

# Open a shell inside it
docker compose -f .devcontainer/compose.yaml exec app bash

# Stop the container
docker compose -f .devcontainer/compose.yaml down
```

`entrypoint.sh` applies your git identity, runs `uv sync`, and installs
the pre-commit hooks on every start. `devcontainer.json` is a thin wrapper
over this same compose file. It adds editor settings and nothing else, so
the two entry points can't drift apart.

### First start

**Start the container before your first change.** `uv.lock` is committed,
so the first `uv sync` inside the container installs exactly the pinned
set. Both workflows install with `uv sync --frozen`, so the lock has to
stay in step: run `uv lock` when you change a dependency, and commit the
result with the change that caused it.

Either way, **commit from inside the container**. The git hooks call
`uv run`, so they need the container's toolchain. A `git commit` from the
host will try to use a host Python and fail. The VS Code terminal already
is a container shell.

### Why everything runs in the container

The container is the only environment whose Python and uv versions are
pinned and reproducible. Running tools against a host Python will
eventually disagree with CI. Every command in this document assumes you
are inside the container.

## Making a change

```text
edit -> git commit -> hooks run -> push -> CI -> merge to main -> release
```

1. Branch from `main`:

   ```bash
   git checkout -b feature/short-description
   ```

2. Make the change, with tests.

3. Run the gate:

   ```bash
   uv run pre-commit run --all-files
   uv run pytest
   ```

4. Commit. The hooks run automatically, and the commit-msg hook rejects
   any message that is not a Conventional Commit.

5. Push and open a PR against `main`.

Everyday commands:

```bash
# Tests, with coverage
uv run pytest

# Lint, fixing what can be fixed
uv run ruff check --fix .

# Format
uv run ruff format .

# Type check
uv run mypy

# Every hook, exactly as CI runs them
uv run pre-commit run --all-files
```

`pre-commit run --all-files` covers CI's `pre-commit` job but not its
`test` job, because pytest is not a hook. Run both before pushing.
`uv run` syncs the environment before running, so there's no virtualenv
to activate.

## Quality gate

`.pre-commit-config.yaml` is the single definition of "correct", used by
your local hooks and by CI.

One stage needs more than `--all-files`. That run covers the `pre-commit`
stage; the `commit-msg` stage needs a commit message, and there is no such
thing in a `--all-files` run. So `validate.yml` writes each pull request
commit's message, and the pull request title, to a file and runs the hooks
against them directly. A message written with `--no-verify` still fails
the pull request; a commit pushed straight to `main` is caught by
`release.yml`'s gate instead.

| Hook | Stage | What it does |
| --- | --- | --- |
| Hygiene hooks | pre-commit | Whitespace, EOF, merge markers, large files, private keys, LF endings |
| `check-yaml`, `check-json`, `check-toml` | pre-commit | Parse validity |
| `prettier` | pre-commit | Formats YAML and JSON |
| `markdownlint-fix` | pre-commit | Formats and lints Markdown |
| `shellcheck` | pre-commit | Lints shell scripts |
| `ruff-check`, `ruff-format` | pre-commit | Lints and formats Python |
| `mypy` | pre-commit | Type checks `src/` and `tests/` |
| `uv-lock` | pre-commit | Fails if `uv.lock` has drifted |
| `conventional-pre-commit` | commit-msg | Rejects non-Conventional commit messages |

Several of these are deliberately configured against the obvious default:

- **`ruff` and `mypy` run as local hooks** (`uv run ruff`, `uv run mypy`)
  rather than through mirror repositories. For mypy this is necessary: a
  mirrored hook runs in an isolated environment that cannot see project
  dependencies, so it reports false import errors as soon as there are
  any. For ruff it means there is one version, declared in
  `pyproject.toml` and locked in `uv.lock`, so `uv run ruff` and the CI
  hook cannot drift apart and enforce different rules.
- **`prettier` is not given TOML.** It can't parse TOML without a plugin.
- **`check-json` and `prettier` both skip `devcontainer.json`.** It's
  JSONC: the comments in it are valid there and are a parse error to both
  tools.
- **`markdownlint` skips `CHANGELOG.md`.** python-semantic-release
  generates it and emits two blank lines between releases, which trips
  MD012. Since the release commit carries `[skip ci]`, that would land
  unchecked and fail the *next* push, leaving CI red after every release.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/), enforced by
the `conventional-pre-commit` hook. The format feeds the release pipeline:
python-semantic-release derives the next version from it, and a message it
can't parse silently produces no release.

```text
<type>: <description>
```

| Type | Meaning | Releases? |
| --- | --- | --- |
| `feat` | New functionality | Minor |
| `fix` | Bug fix | Patch |
| `perf` | Performance improvement | **Patch** |
| `docs` | Documentation only | No |
| `refactor` | Restructuring without behaviour change | No |
| `test` | Tests only | No |
| `build` | Build system, dependencies, container | No |
| `ci` | CI configuration | No |
| `chore` | Everything else | No |
| `style` | Formatting only | No |

Breaking changes take a `!` after the type (`feat!: ...`) or a
`BREAKING CHANGE:` footer, and produce a major bump.

`perf` is the one to watch: it reads like housekeeping but ships a patch
release, because PSR's conventional parser sets `patch_tags = ("fix", "perf")`.
The commit-msg hook accepts `revert`, but it is not one of PSR's allowed
tags, so it produces no release.

Examples:

```text
feat: add --json output flag
fix: handle empty input without raising
docs: document the release pipeline
```

## Pull requests

PRs are squash-merged, so **the PR title becomes the commit message on
`main`**. That title must be a valid Conventional Commit. The commit-msg
hook can't check a PR title, so this one is on you.

`validate.yml` runs on pull requests to `main` only: nothing runs on a
plain branch push, and nothing runs on the squashed commit after the
merge. That gap is what `release.yml` covers, by checking that a commit
on `main` arrived through a pull request whose Validate run was green.

## Dependencies

```bash
uv add httpx                      # runtime
uv add --group dev pytest-mock    # development only
uv remove httpx
```

Always commit `uv.lock`. CI installs with `--frozen` and fails if the lock
has drifted; the `uv-lock` hook catches it locally first.

### Updating pinned tools

Separate mechanisms, because no single one covers everything:

| What | How |
| --- | --- |
| Python dependencies | Dependabot, weekly (`uv` ecosystem) |
| GitHub Actions | Dependabot, weekly (`github-actions` ecosystem) |
| Base and uv images | Dependabot, weekly (`docker` ecosystem, `/.devcontainer` and `/` - the root Dockerfile included) |
| pre-commit hooks | Manual: `uv run pre-commit autoupdate` |
| python-semantic-release | Manual: the version in `.github/workflows/release.yml` |

Dependabot has no pre-commit ecosystem, which is why the pre-commit row is
manual. Run it periodically and follow with
`uv run pre-commit run --all-files`, since a new hook revision often
surfaces new findings.

The last row is manual for a different reason. `release.yml` invokes PSR
through `uvx` with an explicit version rather than using its GitHub
Action, so no Dependabot ecosystem can see it.

ruff and mypy are **not** pinned by hand. They're declared in
`pyproject.toml`, locked in `uv.lock`, and called by local hooks, so
Dependabot's `uv` ecosystem updates them and there is only ever one
version of each.

## Tests

pytest, with coverage measured against the installed `gpai_docs` package
and a floor of 95%.

```bash
uv run pytest                       # everything, with coverage
uv run pytest tests/test_cli.py -v  # one file
uv run pytest -k schema             # by name
```

The suite follows the tool: the registry data and its verification
(`test_registry_*`, `test_verify.py`), the document reader
(`test_documents.py`), the lint passes (`test_lint_completeness.py`,
`test_lint_typed.py`, `test_consistency.py`), diff and extract
(`test_diff.py`, `test_extract*.py`), the reports (`test_reports.py`), the
DOCX round trip (`test_docx_import.py`, `test_docx_export.py`), the
exporters (`test_export.py`), the CLI and its exit contracts
(`test_cli.py`), the errata log's shape (`test_errata.py`), the paper and
its LaTeX render (`test_paper.py`), the documents' plain style
(`test_docs_style.py`), and the packaging metadata (`test_packaging.py`).

Coverage has no `omit` rules and no exclusions: an
`if __name__ == "__main__":` guard counts like any other branch. Mark
genuinely unreachable code `# pragma: no cover` rather than lowering the
floor or excluding the file.

### The coverage badge

`badges/coverage.svg` is committed, and the `badge` job in `release.yml`
regenerates it on `main` by re-running the suite and feeding the resulting
`coverage.xml` to genbadge.

## Types

mypy runs in `strict` mode over `src/` and `tests/`, including test
functions. New code needs annotations:

```python
def render(rows: list[str], *, indent: int = 0) -> str: ...
```

```bash
uv run mypy
```

## Comments

A comment earns its place by explaining a why the code cannot: an external
constraint (a legal text, another tool's quirk, a wire format), an invariant
nothing enforces, a workaround, or a pointer to where the truth lives. If the
code says it, the comment does not. One line is the default; a short
paragraph only when the why genuinely needs one.

Docstrings: a module gets one to four lines, a class one or two, a function
one line or only the contract its signature cannot carry (raises, side
effects, non-obvious semantics). Tests follow the same rule: keep why the
case exists, drop the narration of what it does.

Rationale that is really documentation - a methodology note, an artifact
record - belongs in `docs/`, with the code carrying a pointer. Comments are
not a second copy of the documents, and the documents are not a second copy
of the comments.

## CI and releases

The workflows live in `.github/workflows/`. `registry-verify.yml` runs
weekly on a schedule and on demand; the rest run on changes and are
described below.

**`validate.yml`** runs on PRs to `main` only, and is the quality gate:

1. `pre-commit` - every hook, across all files, then the `commit-msg`
   hooks over every commit in the pull request and the conventional check
   over the pull request title (a squash merge turns that title into the
   subject on `main`).
2. `test` - pytest.
3. `docker` - the "Docker image (build and smoke)" job: builds the image
   from the root Dockerfile, runs the console script's `--help`, lints a
   minimal document with exit 1 and the findings closure asserted, and
   verifies the packaged registry offline.

**`release.yml`** runs on pushes to `main`. Its `release` job first
verifies that the pushed commit arrived through a pull request whose
Validate run was green, and then hands off
to python-semantic-release, which reads its configuration from
`pyproject.toml`. Releases come from commit messages: the type prefix
decides what happens (the table above says which prefixes ship).

On a release, python-semantic-release bumps the version in
`pyproject.toml`, the only place it appears. It inserts the new entry into
`CHANGELOG.md` below its `<!-- version list -->` marker and re-locks
`uv.lock` so its recorded version follows. Then it tags and publishes a
GitHub Release.

The release job publishes nothing: `build_command` runs `uv lock` instead
of a build, which keeps `uv.lock`'s recorded project version in step with
the bump PSR just wrote into `pyproject.toml`, and `assets` carries the
regenerated lock into the release commit. Without it, a release would
leave the lock stale and fail the `uv-lock` hook on the next push.

The second job, `badge`, regenerates `badges/coverage.svg` from a fresh
run of the suite and commits it if it changed. Both jobs share a
`concurrency` group, so they can't race each other pushing to `main`.

There is nothing to do to release: merging a `feat:`, `fix:` or `perf:`
commit to `main` triggers it. Never edit `CHANGELOG.md` by hand or bump a
version manually. python-semantic-release owns both, and a manual edit
will either be overwritten or leave the two version locations out of
step.
