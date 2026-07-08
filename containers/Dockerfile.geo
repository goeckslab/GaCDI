# GaCDI GEO runtime: base image + entrez-direct.
#   docker build -f containers/Dockerfile.geo \
#     --build-arg BASE_IMAGE=gacdi-base:dev -t gacdi-geo:dev .
ARG BASE_IMAGE=quay.io/paulocilasjr/gacdi-base:0.1.0
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="gacdi-geo" \
      org.opencontainers.image.description="GaCDI GEO importer runtime (gacdi + entrez-direct)"

USER root
COPY containers/env/geo.yml /tmp/geo.yml
RUN micromamba install -y -n base -f /tmp/geo.yml && micromamba clean -a -y
USER $MAMBA_USER
