FROM python:3.12-alpine
WORKDIR /app
# build from gacdi parent directory
COPY . .
RUN pip install --no-cache-dir .
CMD ["gacdi-manifest"]