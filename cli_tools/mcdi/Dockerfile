# syntax=docker/dockerfile:1

FROM python:3.12-slim

# Keep one trust store for command-line tools, Python's ssl module, and
# requests. A private/corporate CA can be supplied at build time with:
#   docker build --secret id=mcdi_ca_cert,src=/path/to/root-ca.crt \
#     --build-arg MCDI_CA_CERT_SHA256=<certificate-sha256> ...
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The secret is optional so normal and CI builds need no private CA. When it is
# supplied, copy it into the image and regenerate Debian's combined CA bundle.
# The secret mount keeps an extra copy out of the build context and /app.
# Secret contents do not invalidate Docker's cache, so the caller also supplies
# their SHA-256 as a safe cache key.
ARG MCDI_CA_CERT_SHA256=none
RUN --mount=type=secret,id=mcdi_ca_cert,required=false \
    set -eu; \
    if [ -f /run/secrets/mcdi_ca_cert ]; then \
        if [ "$MCDI_CA_CERT_SHA256" = "none" ]; then \
            echo "MCDI_CA_CERT_SHA256 is required when mcdi_ca_cert is supplied" >&2; \
            exit 2; \
        fi; \
        actual_sha256="$(sha256sum /run/secrets/mcdi_ca_cert | cut -d ' ' -f 1)"; \
        if [ "$actual_sha256" != "$MCDI_CA_CERT_SHA256" ]; then \
            echo "mcdi_ca_cert does not match MCDI_CA_CERT_SHA256" >&2; \
            exit 2; \
        fi; \
        install -m 0644 /run/secrets/mcdi_ca_cert \
            /usr/local/share/ca-certificates/mcdi-custom-ca.crt; \
        update-ca-certificates; \
    elif [ "$MCDI_CA_CERT_SHA256" != "none" ]; then \
        echo "mcdi_ca_cert is required when MCDI_CA_CERT_SHA256 is supplied" >&2; \
        exit 2; \
    fi

WORKDIR /app
# build from the mcdi parent directory
COPY . .
RUN pip install --no-cache-dir .
# Build identifier (e.g. git SHA) so a run can report exactly which code it used.
ARG MCDI_BUILD=local
ENV MCDI_BUILD=${MCDI_BUILD}
CMD ["mcdi", "--help"]
