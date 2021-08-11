module.exports = {
  apps : [{
    name: 'alpaca-trading-bot',
    cmd: 'main.py',
    restart_delay: 10000,
    cron_restart: '0 3 * * *',
    watch: false,
    interpreter: 'python3'
  }]
};
