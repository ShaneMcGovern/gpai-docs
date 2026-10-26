# syntax=docker/dockerfile:1

# Named build stage so the uv version is a literal FROM tag, which Dependabot's
# docker ecosystem tracks; an inline `COPY --from=` is not reliably detected.
FROM ghcr.io/astral-sh/uv:0.12.24 AS uv

FROM python:3.13.17-slim-bookworm

# libatomic1: required by the Node runtime pre-commit's nodeenv installs for the
# prettier hook; without it the hook fails with "libatomic.so.1: cannot open
# shared object file".
# gh: bookworm's 2.23.0 never moves; no Dependabot ecosystem sees apt packages.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gh \
        git \
        libatomic1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /bin/

# UV_LINK_MODE=copy: hard links fail across the bind-mount/volume boundary.
# VIRTUAL_ENV/PATH: so a plain shell finds the project tools without `uv run`.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH

# A login shell rebuilds PATH from /etc/profile and drops the venv; this file
# covers `bash -l`. Single-quoted so ${PATH} expands when sourced, not at build.
RUN printf 'export VIRTUAL_ENV=%s\nexport PATH="%s/bin:${PATH}"\n' \
    "${VIRTUAL_ENV}" "${VIRTUAL_ENV}" \
    > /etc/profile.d/10-venv.sh

# The user name is a literal because compose.yaml hardcodes /home/developer for
# its volumes. The uid/gid are build args for Linux hosts not at 1000, where the
# bind mount leaves /app read-only (first failure: pytest writing coverage.xml).
ARG USER_UID=1000
ARG USER_GID=1000
RUN groupadd --gid "${USER_GID}" developer \
    && useradd --uid "${USER_UID}" --gid "${USER_GID}" --create-home --shell /bin/bash developer

WORKDIR /app

# root-owned: nothing should rewrite the entrypoint.
COPY --chown=root:root --chmod=755 .devcontainer/entrypoint.sh /entrypoint.sh

# Mount targets must exist and be owned by developer: Docker creates a missing
# named-volume target as root, and the tools then fail with permission errors.
RUN mkdir -p /app/.venv \
        "/home/developer/.cache/uv" \
        "/home/developer/.cache/pre-commit" \
        "/home/developer/.config/gh" \
    && chown -R developer:developer \
        /app \
        "/home/developer/.cache" \
        "/home/developer/.config"

USER developer

ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]
