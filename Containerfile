# Imagen del servidor MCP de memoria por HTTP (memoria-mcp-http).
# Build:  docker build -t memoria-mcp -f Containerfile .
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY memoria ./memoria
RUN pip install --no-cache-dir .
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["memoria-mcp-http"]
