# syntax=docker/dockerfile:1
# Next.js web client. Build with context = repo ROOT (npm workspaces):
#   docker build -f apps/web/Dockerfile -t raku-rag-web .
FROM node:22-slim AS build
WORKDIR /repo
ENV NEXT_TELEMETRY_DISABLED=1
COPY . .
RUN npm ci \
 && npm run build:shared \
 && npm run build --workspace @raku-rag/web \
 && npm prune --omit=dev

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
