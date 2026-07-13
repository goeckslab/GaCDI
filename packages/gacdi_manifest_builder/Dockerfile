FROM python:3.12-alpine

# Build from the repository root. The builder imports the shared `gacdi`
# contract package, so both local distributions must be installed into the
# image; installing only this subdirectory makes clean-checkout builds fail.
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY gacdi ./gacdi
RUN pip install --no-cache-dir .

WORKDIR /src/cli_tools/gacdi_manifest
COPY cli_tools/gacdi_manifest/pyproject.toml cli_tools/gacdi_manifest/README.md cli_tools/gacdi_manifest/LICENSE ./
COPY cli_tools/gacdi_manifest/gacdi_manifest ./gacdi_manifest
RUN pip install --no-cache-dir . \
    && gacdi-manifest --version

# Build identifier (e.g. git SHA) so a run can report exactly which code it used.
ARG GACDI_BUILD=local
ENV GACDI_BUILD=${GACDI_BUILD}
CMD ["gacdi-manifest"]
