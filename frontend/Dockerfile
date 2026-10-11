# ==============================================================================
# Lenny Growth Assistant - Frontend Multi-Stage Dockerfile
#
# Stage 1: Build production React bundle using Vite
# Stage 2: Serve static bundle via lightweight Nginx Alpine container
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build React Production Bundle
# ------------------------------------------------------------------------------
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies using clean lockfile
COPY package.json package-lock.json ./
RUN npm ci

# Copy source code and build bundle
COPY . .
RUN npm run build

# ------------------------------------------------------------------------------
# Stage 2: Production Nginx Server
# ------------------------------------------------------------------------------
FROM nginx:alpine-slim

# Copy built artifacts from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy custom Nginx configuration with SPA fallback and API proxying
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --retries=3 --start-period=5s \
    CMD wget -qO- http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
