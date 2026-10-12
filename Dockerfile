# The digest-pinning intent: when this image becomes a release artifact, pin
# the base below to a digest (and let an update bot move the digest, never the
# tag). Until then the tag is deliberately floating; no `latest` tag appears
# anywhere in this file.
FROM python:3.13-slim

# The wheel build reads exactly four inputs (pyproject.toml, whose readme and
# license fields name two of the others; README.md, LICENSE, src/), so the
# metadata files land first, where they change least, and the code after them.
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

# PEP 517: pip builds the wheel with the backend pyproject.toml names and
# installs the distribution, which puts the `gpai-docs` console script on PATH
# and the registry data in site-packages. pip runs once, at build time; there
# is no uv in the image and the CLI never needs the network.
RUN pip install --no-cache-dir .

# A non-root user for the run side: the CLI reads what it is given and writes
# nothing outside its output paths. /work is pre-created and owned here so the
# workload directory exists even without a mount.
RUN useradd --create-home --user-group gpai-docs \
    && mkdir -p /work \
    && chown gpai-docs:gpai-docs /work

USER gpai-docs

# So `-v "$PWD:/work"` lines up with `lint /work/model-docs.yaml`.
WORKDIR /work

ENTRYPOINT ["gpai-docs"]
