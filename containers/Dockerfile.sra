# GaCDI SRA runtime: base image + sra-tools.
#   docker build -f containers/Dockerfile.sra \
#     --build-arg BASE_IMAGE=gacdi-base:dev -t gacdi-sra:dev .
ARG BASE_IMAGE=quay.io/goeckslab/gacdi-base:0.1.1
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="gacdi-sra" \
      org.opencontainers.image.description="GaCDI SRA importer runtime (gacdi + sra-tools)"

USER root
COPY containers/env/sra.yml /tmp/sra.yml
RUN micromamba install -y -n base -f /tmp/sra.yml && micromamba clean -a -y
USER $MAMBA_USER
