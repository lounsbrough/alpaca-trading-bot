import os
import alpaca_trade_api as alpaca
import asyncio
import pandas as pd
import pytz
import sys
import logging
import json
from datetime import datetime
from enum import Enum

from alpaca_trade_api import Stream
from alpaca_trade_api.common import URL
from alpaca_trade_api.rest import TimeFrame

logger = logging.getLogger()

APCA_API_KEY_ID = os.getenv('APCA_API_KEY_ID')
APCA_API_SECRET_KEY = os.getenv('APCA_API_SECRET_KEY')

STOCK_MARKET_TIMEZONE = 'America/New_York'

class StockState(Enum):
    TO_BUY = 1
    BUY_SUBMITTED = 2
    TO_SELL = 3
    SELL_SUBMITTED = 4

class ScalpAlgo:
    def __init__(self, api, symbol, lot):
        self._api = api
        self._symbol = symbol
        self._lot = lot
        self._bars = []
        self._l = logger.getChild(self._symbol)

        now = pd.Timestamp.now(tz=STOCK_MARKET_TIMEZONE).floor('1min')
        market_open = now.replace(hour=9, minute=30)
        today = now.strftime('%Y-%m-%d')
        tomorrow = (now + pd.Timedelta('1day')).strftime('%Y-%m-%d')
        data = api.get_bars(symbol, TimeFrame.Minute, today, tomorrow, adjustment='raw').df
        bars = data[market_open:]
        self._bars = bars

        self._init_state()

    def _init_state(self):
        self._next_close = self._api.get_clock().next_close
        symbol = self._symbol
        order = [o for o in self._api.list_orders() if o.symbol == symbol]
        position = [p for p in self._api.list_positions()
                    if p.symbol == symbol]
        self._order = order[0] if len(order) > 0 else None
        self._position = position[0] if len(position) > 0 else None
        if self._position is not None:
            if self._order is None:
                self._state = StockState.TO_SELL
            else:
                self._state = StockState.SELL_SUBMITTED
                if self._order.side != 'sell':
                    self._l.warn(
                        f'state {self._state} mismatch order {self._order}')
        else:
            if self._order is None:
                self._state = StockState.TO_BUY
            else:
                self._state = StockState.BUY_SUBMITTED
                if self._order.side != 'buy':
                    self._l.warn(
                        f'state {self._state} mismatch order {self._order}')

    def _now(self):
        return pd.Timestamp.now(tz=STOCK_MARKET_TIMEZONE)

    def _update_next_close(self, next_close):
        self._next_close = next_close

    def _too_early_to_trade(self):
        return self._now().time() < pd.Timestamp('10:05').time()

    def _market_closing_soon(self):
        return self._now() >= self._next_close - pd.Timedelta('5 min')

    def checkup(self, position):
        now = self._now()
        order = self._order
        if (order is not None and
            order.side == 'buy' and now - order.submitted_at.tz_convert(tz=STOCK_MARKET_TIMEZONE) > pd.Timedelta('2 min')):
            last_price = self._api.get_last_trade(self._symbol).price
            self._l.info(
                f'canceling missed buy order {order.id} at {order.limit_price} '
                f'(current price = {last_price})')
            self._cancel_order()

        if self._position is not None and self._market_closing_soon():
            self._submit_sell(bailout=True)

    def _cancel_order(self):
        if self._order is not None:
            self._api.cancel_order(self._order.id)

    def _calculate_buy_signal(self):
        mavg = self._bars.rolling(20).mean().close.values
        closes = self._bars.close.values
        if closes[-2] < mavg[-2] and closes[-1] > mavg[-1]:
            self._l.info(
                f'buy signal: closes[-2] {closes[-2]} < mavg[-2] {mavg[-2]} '
                f'closes[-1] {closes[-1]} > mavg[-1] {mavg[-1]}')
            return True
        else:
            self._l.info(
                f'closes[-2:] = {closes[-2:]}, mavg[-2:] = {mavg[-2:]}')
            return False

    def on_bar(self, bar):
        self._bars = self._bars.append(pd.DataFrame({
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close,
            'volume': bar.volume,
        }, index=[pd.Timestamp(bar.timestamp, tz=pytz.UTC)]))

        self._l.info(
            f'received bar start: {pd.Timestamp(bar.timestamp)}, close: {bar.close}, len(bars): {len(self._bars)}')

        if self._too_early_to_trade() or self._market_closing_soon():
            return

        if self._state == StockState.TO_BUY:
            signal = self._calculate_buy_signal()
            if signal:
                self._submit_buy()

    def on_order_update(self, event, order):
        self._l.info(f'order update: {event} = {order}')
        if event == 'fill':
            self._order = None
            if self._state == StockState.BUY_SUBMITTED:
                self._position = self._api.get_position(self._symbol)
                self._transition(StockState.TO_SELL)
                self._submit_sell()
                return
            elif self._state == StockState.SELL_SUBMITTED:
                self._position = None
                self._transition(StockState.TO_BUY)
                return
        elif event == 'partial_fill':
            self._position = self._api.get_position(self._symbol)
            self._order = self._api.get_order(order['id'])
            return
        elif event in ('canceled', 'rejected'):
            if event == 'rejected':
                self._l.warn(f'order rejected: current order = {self._order}')
            self._order = None
            if self._state == StockState.BUY_SUBMITTED:
                if self._position is not None:
                    self._transition(StockState.TO_SELL)
                    self._submit_sell()
                else:
                    self._transition(StockState.TO_BUY)
            elif self._state == StockState.SELL_SUBMITTED:
                self._transition(StockState.TO_SELL)
                self._submit_sell(bailout=True)
            else:
                self._l.warn(f'unexpected state for {event}: {self._state}')

    def _submit_buy(self):
        trade = self._api.get_last_trade(self._symbol)
        amount = int(self._lot / trade.price)
        try:
            order = self._api.submit_order(
                symbol=self._symbol,
                side='buy',
                type='limit',
                qty=amount,
                time_in_force='day',
                limit_price=trade.price,
            )
        except Exception as e:
            self._l.info(e)
            self._transition(StockState.TO_BUY)
            return

        self._order = order
        self._l.info(f'submitted buy {order}')
        self._transition(StockState.BUY_SUBMITTED)

    def _submit_sell(self, bailout=False):
        params = dict(
            symbol=self._symbol,
            side='sell',
            qty=self._position.qty,
            time_in_force='day',
        )
        if bailout:
            params['type'] = 'market'
        else:
            current_price = float(
                self._api.get_last_trade(
                    self._symbol).price)
            cost_basis = float(self._position.avg_entry_price)
            limit_price = max(cost_basis + 0.01, current_price)
            params.update(dict(
                type='limit',
                limit_price=limit_price,
            ))
        try:
            order = self._api.submit_order(**params)
        except Exception as e:
            self._l.error(e)
            self._transition(StockState.TO_SELL)
            return

        self._order = order
        self._l.info(f'submitted sell {order}')
        self._transition(StockState.SELL_SUBMITTED)

    def _transition(self, new_state):
        self._l.info(f'transition from {self._state} to {new_state}')
        self._state = new_state


def main():
    stream = Stream(APCA_API_KEY_ID,
                    APCA_API_SECRET_KEY,
                    base_url=URL('https://paper-api.alpaca.markets'),
                    data_feed='sip')
    api = alpaca.REST(key_id=APCA_API_KEY_ID,
                    secret_key=APCA_API_SECRET_KEY,
                    base_url="https://paper-api.alpaca.markets")

    with open('stock-selections.json') as f:
        stock_selections = json.load(f)

    fleet = {}
    next_close = api.get_clock().next_close

    for stock_selection in stock_selections:
        logger.info(f'selected stock {stock_selection}')

        algo = ScalpAlgo(api, stock_selection['symbol'], stock_selection['lot'])
        fleet[stock_selection['symbol']] = algo

    async def on_bars(data):
        if data.symbol in fleet:
            fleet[data.symbol].on_bar(data)

    for stock_selection in stock_selections:
        stream.subscribe_bars(on_bars, stock_selection['symbol'])

    async def on_trade_updates(data):
        logger.info(f'trade_updates {data}')
        symbol = data.order['symbol']
        if symbol in fleet:
            fleet[symbol].on_order_update(data.event, data.order)

    stream.subscribe_trade_updates(on_trade_updates)

    def refresh_next_close():
        next_close = api.get_clock().next_close

    async def periodic():
        while True:
            if api.get_clock().is_open:
                refresh_next_close()
                positions = api.list_positions()
                for symbol, algo in fleet.items():
                    algo._update_next_close(next_close)
                    pos = [p for p in positions if p.symbol == symbol]
                    algo.checkup(pos[0] if len(pos) > 0 else None)

            await asyncio.sleep(30)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.gather(
        stream._run_forever(),
        periodic(),
    ))
    loop.close()

if __name__ == '__main__':
    fmt = '%(asctime)s:%(filename)s:%(lineno)d:%(levelname)s:%(name)s:%(message)s'
    logging.basicConfig(level=logging.INFO, format=fmt)

    main()
