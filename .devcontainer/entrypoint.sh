#!/bin/bash
set -euo pipefail

cd /app

# /app/.git separately on purpose: git checks the exact path, so a mount
# that exempts only /app still fails with "dubious ownership". The guard
# stops --add duplicating entries on every restart.
for d in /app /app/.git; do
  if ! git config --global --get-all safe.directory 2>/dev/null | grep -qx "${d}"; then
    git config --global --add safe.directory "${d}"
  fi
done

if [ -n "${GIT_AUTHOR_NAME:-}" ] && [ -n "${GIT_AUTHOR_EMAIL:-}" ]; then
  git config --global user.name "${GIT_AUTHOR_NAME}"
  git config --global user.email "${GIT_AUTHOR_EMAIL}"
else
  echo "GIT_AUTHOR_NAME and GIT_AUTHOR_EMAIL not set; skipping git identity config"
  echo "Set them in .devcontainer/.env, or run git config --global user.name/user.email"
fi

# Points git at gh as its HTTPS credential helper, so pushes authenticate
# without a prompt. Re-run every start because ~/.gitconfig is not persisted:
# without the helper, git fails with "could not read Username". Skipped while
# gh has nothing authenticated yet.
if gh auth status >/dev/null 2>&1; then
  if ! gh auth setup-git; then
    echo "WARNING: gh auth setup-git failed; git push over HTTPS will not use gh."
  fi
fi

if [ -f pyproject.toml ]; then
  # `[ -w uv.lock ]` is false when the file is missing too, so the `! -f` arm
  # keeps a fresh clone off the --frozen path. A read-only lock (Windows bind
  # mount) syncs --frozen rather than being deleted to dodge the permissions.
  if [ ! -f uv.lock ] || [ -w uv.lock ]; then
    sync_cmd=(uv sync --all-groups)
  else
    echo "uv.lock is read-only; syncing with --frozen (the lock will not be updated)"
    sync_cmd=(uv sync --frozen --all-groups)
  fi

  # Deliberately non-fatal: under `set -e` a transient failure (no network on
  # first start) would kill the container and leave no way to diagnose it.
  if ! "${sync_cmd[@]}"; then
    echo "WARNING: uv sync failed. The container is still running so you can"
    echo "         attach and re-run 'uv sync --all-groups' once the cause is fixed."
  fi
else
  echo "pyproject.toml not found; skipping uv sync"
fi

# Installed here rather than in a devcontainer postCreateCommand so that
# `docker compose up` alone yields a complete environment; failure is non-fatal.
if [ -d .git ] && [ -f .pre-commit-config.yaml ]; then
  if ! uv run --frozen pre-commit install --install-hooks; then
    echo "WARNING: pre-commit install failed; git hooks are NOT active."
    echo "         Re-run 'uv run pre-commit install --install-hooks' once fixed."
  fi
else
  echo "No .git or no .pre-commit-config.yaml; skipping pre-commit install"
fi

exec sleep infinity
