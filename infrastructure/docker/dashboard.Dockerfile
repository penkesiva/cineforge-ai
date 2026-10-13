# syntax=docker/dockerfile:1.7
# CineForge dashboard image (Next.js, npm workspace @cineforge/dashboard).
# Build context = repo root.
#
# Targets:
#   dev     - `npm run dev` with hot reload (compose default; sources bind-mounted)
#   runner  - `npm run build` at image build time, then `npm run start` (prod-like)
#
# Next.js rewrites (/api/v1/*, /health -> API_INTERNAL_URL) are resolved at build
# time for `runner`, so pass --build-arg API_INTERNAL_URL if the API is not `api:8000`.

ARG NODE_VERSION=22

FROM node:${NODE_VERSION}-alpine AS base
RUN apk add --no-cache libc6-compat
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
RUN chown node:node /app

# ---------------------------------------------------------------------------
# Dependencies only (cached until package*.json change).
# ---------------------------------------------------------------------------
FROM base AS deps
USER node
COPY --chown=node:node package.json package-lock.json ./
COPY --chown=node:node apps/dashboard/package.json apps/dashboard/package.json
COPY --chown=node:node packages/schemas/package.json packages/schemas/package.json
RUN --mount=type=cache,target=/home/node/.npm,uid=1000,gid=1000 \
    npm ci --no-audit --no-fund

# ---------------------------------------------------------------------------
# dev: sources baked in (works without bind mounts); compose mounts them for reload.
# ---------------------------------------------------------------------------
FROM deps AS dev
COPY --chown=node:node packages/schemas packages/schemas
COPY --chown=node:node apps/dashboard apps/dashboard
# Pre-create volume mount points so anonymous volumes inherit `node` ownership.
RUN mkdir -p apps/dashboard/.next apps/dashboard/node_modules packages/schemas/node_modules
ENV PORT=3000 \
    HOSTNAME=0.0.0.0 \
    WATCHPACK_POLLING=true
EXPOSE 3000
CMD ["npm", "run", "dev", "--workspace", "@cineforge/dashboard"]

# ---------------------------------------------------------------------------
# runner: production build.
# ---------------------------------------------------------------------------
FROM dev AS runner
ARG API_INTERNAL_URL=http://api:8000
ENV API_INTERNAL_URL=${API_INTERNAL_URL} \
    NODE_ENV=production
RUN npm run build --workspace @cineforge/dashboard
CMD ["npm", "run", "start", "--workspace", "@cineforge/dashboard"]
