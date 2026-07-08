FROM ubuntu:20.04 AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends wget unzip ca-certificates && \
    wget https://gdc.cancer.gov/system/files/public/file/gdc-client_2.3_Ubuntu_x64-py3.8-ubuntu-20.04.zip && \
    unzip gdc-client_2.3_Ubuntu_x64-py3.8-ubuntu-20.04.zip && \
    unzip gdc-client_2.3_Ubuntu_x64.zip && \
    chmod 755 gdc-client

FROM ubuntu:20.04

COPY --from=builder /gdc-client /usr/local/bin/gdc-client