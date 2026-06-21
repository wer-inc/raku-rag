# syntax=docker/dockerfile:1
# NestJS API facade. Build with context = repo ROOT (npm workspaces + the @raku-rag/shared package):
#   docker build -f apps/api/Dockerfile -t raku-rag-api .
FROM node:22-slim AS build
WORKDIR /repo
ENV NEXT_TELEMETRY_DISABLED=1
# .dockerignore keeps node_modules/dist/.next out of the context; copy sources then install+build.
COPY . .
RUN npm ci \
 && npm run build:shared \
 && npm run build --workspace @raku-rag/api \
 && npm prune --omit=dev

FROM node:22-slim AS runtime
WORKDIR /repo
ENV NODE_ENV=production
COPY --from=build /repo/node_modules ./node_modules
COPY --from=build /repo/package.json ./package.json
COPY --from=build /repo/packages/shared ./packages/shared
COPY --from=build /repo/apps/api ./apps/api
WORKDIR /repo/apps/api
EXPOSE 3000
# nest-cli sourceRoot=src, outDir=dist → entrypoint is dist/src/main.js
CMD ["node", "dist/src/main.js"]
