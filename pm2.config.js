module.exports = {
  apps : [{
    name: 'alpaca-trading-bot',
    cmd: 'main.py',
    cron_restart: '0 3 * * *',
    watch: false,
    interpreter: 'python3'
  }]
};
