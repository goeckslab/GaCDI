FROM ubuntu:20.04 AS gdc-client-builder

# gdc.cancer.gov currently serves a certificate chain that minimal containers do
# not trust. TLS verification is bypassed only for this pinned artifact, whose
# exact SHA-256 is verified before extraction.
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl unzip && \
    curl -kfsSL https://gdc.cancer.gov/system/files/public/file/gdc-client_2.3_Ubuntu_x64-py3.8-ubuntu-20.04.zip \
      -o gdc-client_2.3_Ubuntu_x64-py3.8-ubuntu-20.04.zip && \
    echo "5805635e5551962280589f5a59d047bde93b380c653de2b9b62460e7336c8189  gdc-client_2.3_Ubuntu_x64-py3.8-ubuntu-20.04.zip" | sha256sum -c - && \
    unzip -q gdc-client_2.3_Ubuntu_x64-py3.8-ubuntu-20.04.zip && \
    unzip -q gdc-client_2.3_Ubuntu_x64.zip && \
    chmod 755 gdc-client

# The existing gacdi-manifest image is Alpine/musl, which cannot safely run the
# Ubuntu/glibc gdc-client binary. Use a glibc Python runtime and install the same
# package source directly so the two images still share one Python codebase.
FROM python:3.12-slim-bookworm

COPY --from=gdc-client-builder /gdc-client /usr/local/bin/gdc-client
COPY cli_tools/gacdi_manifest /tmp/gacdi-manifest
RUN pip install --no-cache-dir /tmp/gacdi-manifest && \
    rm -rf /tmp/gacdi-manifest && \
    gdc-client --version && \
    gacdi-download --version

ARG GACDI_BUILD=local
ENV GACDI_BUILD=${GACDI_BUILD}
CMD ["gacdi-download", "--help"]
