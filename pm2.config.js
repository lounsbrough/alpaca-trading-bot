module.exports = {
  apps : [{
    name: 'alpaca-trading-bot',
    cmd: 'main.py',
    args: '--lot=2000 TSLA FB AAPL',
    autorestart: false,
    cron_restart: '0 3 * * *',
    watch: false,
    interpreter: 'python3'
  }]
};
