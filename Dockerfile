FROM python:3.12-slim

LABEL org.opencontainers.image.title="CiteGuard MCP" \
      org.opencontainers.image.description="Zero-dependency MCP server & CLI to verify scientific citations, detect chimera hallucinations & retractions." \
      org.opencontainers.image.source="https://github.com/Lukecele/citeguard-mcp" \
      org.opencontainers.image.licenses="MIT" \
      io.modelcontextprotocol.server.name="io.github.Lukecele/citeguard-mcp"

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir .

CMD ["citeguard-mcp", "serve"]
