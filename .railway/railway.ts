import { defineRailway, github, postgres, project, redis, service, volume } from "railway/iac";

export default defineRailway(() => {
  const medtimeline = github("Purvee25/medtimeline");

  const Redis = redis("Redis", { region: "iad" });
  Redis.deploy = { startCommand: "/bin/sh -c \"rm -rf $RAILWAY_VOLUME_MOUNT_PATH/lost+found/ && exec docker-entrypoint.sh redis-server --requirepass $REDIS_PASSWORD --save 60 1 --dir $RAILWAY_VOLUME_MOUNT_PATH\"" };
  Redis.networking = { privateNetworkEndpoint: "redis" };
  const Postgres = postgres("Postgres", { region: "iad" });
  Postgres.networking = { privateNetworkEndpoint: "postgres" };
  const postgresVolume = volume("postgres-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "iad", sizeMB: 500 });
  const redisVolume = volume("redis-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "iad", sizeMB: 500 });
  const web = service("web", {
    source: medtimeline,
    build: { buildEnvironment: "V3", builder: "DOCKERFILE" },
    healthcheck: "/healthz",
    healthcheckTimeout: 30,
    replicas: { "iad": 1 },
  });
  const worker = service("worker", {
    source: medtimeline,
    build: { buildEnvironment: "V3", builder: "DOCKERFILE", dockerfilePath: "Dockerfile.worker" },
    replicas: { "iad": 1 },
  });

  return project("reliable-laughter", {
    variables: { managed: false },
    resources: [web, Redis, Postgres, worker, postgresVolume, redisVolume],
  });
});
