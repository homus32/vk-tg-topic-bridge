/**
 * PM2 ecosystem for vk-topic-bridge (docs/05 §22 contract).
 * One fork process; PM2 writes only to logs/pm2.log (Loguru owns logs/app.log).
 */
module.exports = {
  apps: [
    {
      name: "vk-topic-bridge",
      cwd: __dirname,
      script: "./scripts/start.sh",
      interpreter: "none",

      instances: 1,
      exec_mode: "fork",

      autorestart: true,
      watch: false,

      min_uptime: "10s",
      max_restarts: 10,
      restart_delay: 5000,
      kill_timeout: 15000,

      log_file: "./logs/pm2.log",
      time: false,

      env: {
        PYTHONUNBUFFERED: "1",
      },
    },
  ],
};