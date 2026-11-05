# Public site. Built when the container starts, not when the image is built:
# Next.js prerenders every page from the Soivi API, which has to be up.
FROM node:24.11.1-bookworm-slim

ENV NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
# The single source of the methodology page (copied into content/ at build time).
COPY docs/methodology.md ./docs/methodology.md

CMD ["sh", "scripts/start.sh"]
