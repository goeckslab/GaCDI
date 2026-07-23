FROM python:3.12-alpine
WORKDIR /app
# build from the mcdi parent directory
COPY . .
RUN pip install --no-cache-dir .
# Build identifier (e.g. git SHA) so a run can report exactly which code it used.
ARG MCDI_BUILD=local
ENV MCDI_BUILD=${MCDI_BUILD}
CMD ["mcdi", "--help"]
