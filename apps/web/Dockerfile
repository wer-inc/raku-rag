# syntax=docker/dockerfile:1
# Next.js web client. Build with context = repo ROOT (npm workspaces):
#   docker build -f apps/web/Dockerfile -t raku-rag-web .
FROM node:22-slim AS build
WORKDIR /repo
# NEXT_PUBLIC_* is inlined into the client bundle at BUILD time. Default "/v1" = same-origin relative
# (web + API behind one ALB); override with --build-arg NEXT_PUBLIC_API_BASE=https://api.example.com/v1
# for a split-origin (e.g. Vercel) deploy.
ARG NEXT_PUBLIC_API_BASE=/v1
ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}
COPY . .
# Build with full deps, then do a CLEAN prod-only install so dev tooling (jest/@nestjs/cli/
# @angular-devkit and their transitive globs — glob/tmp/picomatch) is ABSENT from the runtime image,
# not merely pruned (npm prune leaves hoisted dev deps in an npm-workspaces monorepo). Build artifacts
# (.next, packages/shared/dist) live outside node_modules and survive the wipe.
RUN npm ci \
 && npm run build:shared \
 && npm run build --workspace @raku-rag/web \
 && rm -rf node_modules \
 && npm ci --omit=dev

FROM node:22-slim AS runtime
WORKDIR /repo
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=build /repo/node_modules ./node_modules
COPY --from=build /repo/package.json ./package.json
COPY --from=build /repo/packages/shared ./packages/shared
COPY --from=build /repo/apps/web ./apps/web
WORKDIR /repo/apps/web
EXPOSE 3002
CMD ["npm", "run", "start"]
