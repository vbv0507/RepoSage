FROM node:22-alpine

# Install git for Git Archaeology features
RUN apk add --no-cache git

WORKDIR /app

COPY package.json ./
RUN npm install --production --legacy-peer-deps

COPY . .

EXPOSE 5000

ENV PORT=5000
ENV REDIS_URL=redis://redis:6379
ENV CHROMA_URL=http://chromadb:8000

CMD ["node", "server.js"]
