# NestJS API facade. Build with context = repo ROOT (npm workspaces + the @raku-rag/shared package):
#   docker build -f apps/api/Dockerfile -t raku-rag-api .
ARG NODE_BASE_IMAGE=public.ecr.aws/docker/library/node:22-slim
FROM ${NODE_BASE_IMAGE} AS build
WORKDIR /repo
ENV NEXT_TELEMETRY_DISABLED=1
# .dockerignore keeps node_modules/dist/.next out of the context; copy sources then install+build.
COPY . .
# Build with full deps, then do a CLEAN prod-only install so dev tooling (jest/@nestjs/cli/
# @angular-devkit and their transitive globs — glob/tmp/picomatch) is ABSENT from the runtime image,
# not merely pruned (npm prune leaves hoisted dev deps in an npm-workspaces monorepo). Build artifacts
# (dist, packages/shared/dist) live outside node_modules and survive the wipe.
RUN npm ci \
 && npm run build:shared \
 && npm run build --workspace @raku-rag/api \
 && rm -rf node_modules \
 && npm ci --omit=dev

FROM ${NODE_BASE_IMAGE} AS runtime
WORKDIR /repo
ENV NODE_ENV=production
COPY --from=build /repo/node_modules ./node_modules
COPY --from=build /repo/package.json ./package.json
COPY --from=build /repo/packages/shared ./packages/shared
COPY --from=build /repo/apps/api ./apps/api
WORKDIR /repo/apps/api
EXPOSE 3000
# The API imports @raku-rag/shared from source, so tsc computes the project rootDir as the repo root
# and mirrors it under outDir → the entrypoint is the NESTED dist/apps/api/src/main.js (not dist/src).
CMD ["node", "dist/apps/api/src/main.js"]
