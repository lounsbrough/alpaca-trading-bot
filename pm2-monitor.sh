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

if [[ ! $status =~ "online" ]]; then
  echo "Trading bot does not appear to be online, sending notification!"

  if [[ -z $HTTPS_AUTHENTICATION_SECRET ]]; then
    echo "Unable to find authentication secret for sending notification!"
    exit 1
  fi

  curl -X POST \
    http://127.0.0.1:7239 \
    -H 'Content-Type: application/json' \
    -d '{
        "authCode": "'$HTTPS_AUTHENTICATION_SECRET'",
        "deviceName": "David - Phone",
        "action": "pushNote",
        "noteTitle": "Alpaca Trading Bot",
        "noteBody": "Trading bot does not appear to be online!"
    }'

    date +'%s' > $lastOfflineAlertFile
fi
