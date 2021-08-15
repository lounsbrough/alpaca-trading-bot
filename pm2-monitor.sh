#!/bin/bash

SCRIPTDIR=$(dirname "$0")

lastOfflineAlertFile="$SCRIPTDIR/last-offline-alert.txt"

touch $lastOfflineAlertFile
currentTimestamp=$(date +'%s')
lastOfflineAlert=$(cat $lastOfflineAlertFile)

if [[ -z "$lastOfflineAlert" ]]; then
  lastOfflineAlert=0
fi

elapsedSeconds=$(($currentTimestamp-$lastOfflineAlert))

if [[ "$elapsedSeconds" -lt "3600" ]]; then
  echo "Last alert was $elapsedSeconds seconds ago, waiting to send another notification"
  exit 0
fi

status=$(pm2 jlist | jq -r '.[] | select(.name == "alpaca-trading-bot") | .pm2_env.status')

if [[ $status =~ "offline" ]]; then
  echo "Trading bot does not appear to be online, sending notification!"

  if [[ -z $HTTPS_AUTHENTICATION_SECRET ]]; then
    echo "Unable to find authentication secret for sending notification!"
    exit 1
  fi

  curl -X POST -H 'Content-type: application/json' --data '{"text":"Trading bot does not appear to be online!"}' $STOCK_TRADING_BOT_SLACK_WEBHOOK

  date +'%s' > $lastOfflineAlertFile
fi
