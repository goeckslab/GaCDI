FROM python:3.12-alpine
WORKDIR /app
# build from gacdi parent directory
COPY . .
RUN pip install --no-cache-dir .
# Build identifier (e.g. git SHA) so a run can report exactly which code it used.
ARG GACDI_BUILD=local
ENV GACDI_BUILD=${GACDI_BUILD}
CMD ["gacdi-manifest"]