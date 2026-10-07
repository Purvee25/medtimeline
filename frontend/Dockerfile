# syntax=docker/dockerfile:1
FROM node:24.21-alpine AS build
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN npm ci
COPY . .
RUN npm run build

# Unprivileged image: runs as uid 101 and listens on 8080.
FROM nginxinc/nginx-unprivileged:1.29-alpine AS runtime
# Rendered by the image's entrypoint (envsubst) into /etc/nginx/conf.d/default.conf at start-up.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
ENV API_UPSTREAM=http://web:8000 S3_ORIGIN=https://s3.ap-south-1.amazonaws.com
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
