# Build context is apps/web itself (see docker-compose.yml) -- self-contained, no access to
# the Python workspace at the repo root.
FROM node:20-slim

WORKDIR /app

# Copy dependency manifests first so this layer is cached until deps actually change.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173
# The bind mount + anonymous node_modules volume in docker-compose.yml make this a dev
# server (hot reload), not a production build. Must bind 0.0.0.0, not Vite's default
# 127.0.0.1, or the host port mapping (5173:5173) can't reach it.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
