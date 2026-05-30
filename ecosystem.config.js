// pm2 ecosystem dosyası — ana dizinden `pm2 start ecosystem.config.js` ile başlatın
module.exports = {
  apps: [
    {
      name: 'trade-scanner',
      script: 'scanner.py',
      interpreter: 'python3',
      cwd: '/Users/tunahan/trade/trade',
      watch: false,
      autorestart: true,
      restart_delay: 5000,
      log_file: '/Users/tunahan/trade/trade/scanner.log',
      out_file: '/Users/tunahan/trade/trade/scanner.log',
      error_file: '/Users/tunahan/trade/trade/scanner_err.log',
    },
    {
      name: 'jarvis-backend-api',
      script: 'server.js',
      cwd: '/Users/tunahan/trade/trade/dashboard_backend',
      watch: false,
      autorestart: true,
      restart_delay: 3000,
      env: { PORT: 5001, NODE_ENV: 'production' },
    },
  ],
};
