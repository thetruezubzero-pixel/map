FROM node:22-slim AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
ARG VITE_GATEWAY_URL=/api
ARG VITE_PY_API_URL=/py-api
ENV VITE_GATEWAY_URL=$VITE_GATEWAY_URL
ENV VITE_PY_API_URL=$VITE_PY_API_URL
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
