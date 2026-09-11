# ============================================================================
# RazorGrowth AI — frontend image
#
# Two-stage build: node builds the production bundle, nginx serves it and
# proxies /api/* to the backend service. Same-origin API calls mean the
# existing frontend needs zero configuration changes (VITE_API_BASE_URL
# stays empty).
# ============================================================================
FROM node:20-slim AS build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ------------------------------------------------------------------ #
# Runtime — nginx reverse proxy + static server
# ------------------------------------------------------------------ #
FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
