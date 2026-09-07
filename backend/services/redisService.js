import Redis from 'ioredis';
import dotenv from 'dotenv';
dotenv.config();

const REDIS_URL = process.env.REDIS_URL || 'redis://localhost:6379';

class CacheService {
  constructor() {
    this.memoryStore = new Map();
    this.memoryTimeouts = new Map();
    this.isRedisConnected = false;
    this.redisClient = null;

    this.init();
  }

  init() {
    try {
      this.redisClient = new Redis(REDIS_URL, {
        maxRetriesPerRequest: 1,
        retryStrategy: () => null, // Don't crash or loop endlessly if Redis is offline
        connectTimeout: 2000,
        lazyConnect: true
      });

      this.redisClient.connect()
        .then(() => {
          this.isRedisConnected = true;
          console.log(`[Redis] 🟢 Connected to Redis at ${REDIS_URL}`);
        })
        .catch((err) => {
          this.isRedisConnected = false;
          console.log(`[Redis] ⚠️ Redis server not reachable at ${REDIS_URL}. Using high-speed in-memory cache fallback.`);
        });

      this.redisClient.on('error', (err) => {
        if (this.isRedisConnected) {
          console.warn('[Redis] Connection lost, switching to in-memory fallback.');
        }
        this.isRedisConnected = false;
      });
    } catch (e) {
      this.isRedisConnected = false;
      console.log('[Redis] Falling back to in-memory cache store.');
    }
  }

  async get(key) {
    if (this.isRedisConnected && this.redisClient) {
      try {
        const data = await this.redisClient.get(key);
        return data ? JSON.parse(data) : null;
      } catch (err) {
        this.isRedisConnected = false;
      }
    }
    const val = this.memoryStore.get(key);
    return val !== undefined ? JSON.parse(val) : null;
  }

  async set(key, value, ttlSeconds = 3600) {
    const serialized = JSON.stringify(value);

    if (this.isRedisConnected && this.redisClient) {
      try {
        if (ttlSeconds) {
          await this.redisClient.set(key, serialized, 'EX', ttlSeconds);
        } else {
          await this.redisClient.set(key, serialized);
        }
        return true;
      } catch (err) {
        this.isRedisConnected = false;
      }
    }

    // In-memory fallback
    this.memoryStore.set(key, serialized);
    if (this.memoryTimeouts.has(key)) {
      clearTimeout(this.memoryTimeouts.get(key));
    }
    if (ttlSeconds) {
      const timeout = setTimeout(() => {
        this.memoryStore.delete(key);
        this.memoryTimeouts.delete(key);
      }, ttlSeconds * 1000);
      this.memoryTimeouts.set(key, timeout);
    }
    return true;
  }

  async del(key) {
    if (this.isRedisConnected && this.redisClient) {
      try {
        await this.redisClient.del(key);
      } catch (e) {}
    }
    this.memoryStore.delete(key);
    if (this.memoryTimeouts.has(key)) {
      clearTimeout(this.memoryTimeouts.get(key));
      this.memoryTimeouts.delete(key);
    }
  }

  async clearQueries() {
    for (const key of this.memoryStore.keys()) {
      if (key.startsWith('query:')) {
        this.memoryStore.delete(key);
      }
    }
  }

  getStatus() {
    return {
      connected: this.isRedisConnected,
      mode: this.isRedisConnected ? 'redis' : 'in-memory-fallback',
      entriesCached: this.memoryStore.size
    };
  }
}

export const cacheService = new CacheService();
