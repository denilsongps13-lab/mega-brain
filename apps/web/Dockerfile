FROM node:22-alpine AS build
WORKDIR /web
COPY apps/web/package*.json ./
RUN npm ci
COPY apps/web ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build
FROM nginxinc/nginx-unprivileged:stable-alpine
COPY apps/deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/out /usr/share/nginx/html
EXPOSE 8080
