module.exports = {
  apps : [{
    name: 'alpaca-trading-bot',
    cmd: 'main.py',
    args: '--lot=2000 TSLA FB AAPL',
    autorestart: false,
    watch: false,
    interpreter: 'python3'
  }]
};
