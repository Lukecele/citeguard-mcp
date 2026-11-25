FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && git clone https://github.com/Lukecele/citeguard-mcp.git /tmp/citeguard \
    && pip install --no-cache-dir /tmp/citeguard \
    && rm -rf /tmp/citeguard

CMD ["citeguard-mcp", "serve"]
