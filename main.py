import threading
import time
from datetime import datetime

import requests
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.clock import Clock

try:
    from plyer import notification
    NOTIFICATIONS_AVAILABLE = True
except Exception:
    NOTIFICATIONS_AVAILABLE = False

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
CHECK_INTERVAL_SECONDS = 5 * 60


def fetch_gold_data(interval="5m", range_="5d"):
    params = {"interval": interval, "range": range_}
    resp = requests.get(YAHOO_URL, params=params, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    result = data["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]

    candles = []
    for i in range(len(timestamps)):
        h, l, c, o = quote["high"][i], quote["low"][i], quote["close"][i], quote["open"][i]
        if None in (h, l, c, o):
            continue
        candles.append({"time": datetime.fromtimestamp(timestamps[i]), "open": o, "high": h, "low": l, "close": c})
    return candles


def find_swings(candles, lookback=3):
    n = len(candles)
    for c in candles:
        c["swing_high"] = False
        c["swing_low"] = False
    for i in range(lookback, n - lookback):
        window = candles[i - lookback: i + lookback + 1]
        highs = [w["high"] for w in window]
        lows = [w["low"] for w in window]
        if candles[i]["high"] == max(highs):
            candles[i]["swing_high"] = True
        if candles[i]["low"] == min(lows):
            candles[i]["swing_low"] = True
    return candles


def detect_structure(candles):
    swings = [c for c in candles if c["swing_high"] or c["swing_low"]]
    events = []
    trend = None
    last_high = None
    last_low = None
    last_high_point = None
    last_low_point = None

    for row in swings:
        price = row["close"]
        time_ = row["time"]

        if row["swing_high"]:
            if last_high is not None:
                if price > last_high and trend == "down":
                    events.append((time_, "CHoCH (bullish)", price))
                    trend = "up"
                elif price > last_high and trend == "up":
                    events.append((time_, "BOS (bullish continuation)", price))
            last_high = price
            last_high_point = row

        if row["swing_low"]:
            if last_low is not None:
                if price < last_low and trend == "up":
                    events.append((time_, "CHoCH (bearish)", price))
                    trend = "down"
                elif price < last_low and trend == "down":
                    events.append((time_, "BOS (bearish continuation)", price))
            last_low = price
            last_low_point = row

        if trend is None:
            trend = "up" if row["swing_high"] else "down"

    return events, trend, last_high_point, last_low_point


def calc_buffer(candles, lookback=20):
    recent = candles[-lookback:] if len(candles) >= lookback else candles
    ranges = [c["high"] - c["low"] for c in recent]
    avg_range = sum(ranges) / len(ranges) if ranges else 0
    return avg_range * 0.3


def build_trade_idea(current_price, trend, last_high_point, last_low_point, candles):
    buffer = calc_buffer(candles)

    if trend == "up" and last_low_point is not None:
        sl = last_low_point["low"] - buffer
        risk = current_price - sl
        if risk <= 0:
            return None
        tps = [current_price + risk * r for r in (1, 2, 3, 4, 5)]
        return "BUY", current_price, sl, tps, risk, buffer

    elif trend == "down" and last_high_point is not None:
        sl = last_high_point["high"] + buffer
        risk = sl - current_price
        if risk <= 0:
            return None
        tps = [current_price - risk * r for r in (1, 2, 3, 4, 5)]
        return "SELL", current_price, sl, tps, risk, buffer

    return None


def format_report(candles, events, trend, last_high_point, last_low_point, is_new_event):
    last = candles[-1]
    price = last["close"]
    now_str = datetime.now().strftime("%H:%M:%S")

    lines = []
    lines.append(f"[b]GOLD (XAUUSD)[/b]  -  {now_str}")
    lines.append(f"Current Price: {price:.2f}")
    bias = "UP" if trend == "up" else "DOWN" if trend == "down" else "UNCLEAR"
    lines.append(f"Structure Bias: {bias}")
    lines.append("")

    idea = build_trade_idea(price, trend, last_high_point, last_low_point, candles)
    if idea:
        direction, entry, sl, tps, risk, buffer = idea
        lines.append(f"[b]{direction} ZONE[/b]")
        lines.append(f"Entry / Zone: {entry:.2f}")
        for i, tp in enumerate(tps, start=1):
            lines.append(f"TP{i}: {tp:.2f}")
        lines.append(f"SL: {sl:.2f}  (wick + {buffer:.2f} trap buffer)")
        lines.append(f"Risk (1R): {risk:.2f} pts | Reward at TP5: {risk*5:.2f} pts")
    else:
        lines.append("Not enough swing data yet to build a zone.")

    lines.append("")
    if events:
        _, ev_name, ev_price = events[-1]
        if is_new_event:
            lines.append(f"[color=ff5555]NEW EVENT: {ev_name} @ {ev_price:.2f}[/color]")
        else:
            lines.append(f"Last event: {ev_name} @ {ev_price:.2f}")
    else:
        lines.append("No BOS/CHoCH detected yet.")

    lines.append("")
    lines.append("[i]Structure-based idea, not a confirmed signal.[/i]")

    return "\n".join(lines), idea


def send_notification(title, message):
    if not NOTIFICATIONS_AVAILABLE:
        return
    try:
        notification.notify(title=title, message=message[:250], app_name="Gold SMC Monitor", timeout=15)
    except Exception:
        pass


class GoldMonitorLayout(BoxLayout):
    pass


class GoldMonitorApp(App):
    def build(self):
        self.title = "Gold SMC Monitor"
        self.last_seen_event_time = None

        root = BoxLayout(orientation="vertical", padding=10, spacing=10)

        scroll = ScrollView()
        self.status_label = Label(
            text="Starting up... fetching first price check.",
            markup=True,
            size_hint_y=None,
            valign="top",
            halign="left",
        )
        self.status_label.bind(texture_size=self._update_label_height)
        self.status_label.bind(width=lambda inst, val: setattr(
            self.status_label, "text_size", (val, None)
        ))
        scroll.add_widget(self.status_label)
        root.add_widget(scroll)

        self.worker_thread = threading.Thread(target=self.background_loop, daemon=True)
        self.worker_thread.start()

        return root

    def _update_label_height(self, instance, size):
        self.status_label.height = size[1]

    def background_loop(self):
        while True:
            try:
                candles = fetch_gold_data(interval="5m", range_="5d")
                if len(candles) >= 10:
                    candles = find_swings(candles, lookback=3)
                    events, trend, last_high_point, last_low_point = detect_structure(candles)

                    is_new_event = False
                    if events:
                        latest_time = events[-1][0]
                        is_new_event = latest_time != self.last_seen_event_time
                        self.last_seen_event_time = latest_time

                    report_text, idea = format_report(
                        candles, events, trend, last_high_point, last_low_point, is_new_event
                    )

                    Clock.schedule_once(lambda dt, t=report_text: self.update_ui(t))

                    if is_new_event:
                        if idea:
                            direction, entry, sl, tps, risk, buffer = idea
                            msg = f"{direction} ZONE @ {entry:.2f} | TP1: {tps[0]:.2f} | SL: {sl:.2f}"
                        else:
                            msg = f"New structure event. Price: {candles[-1]['close']:.2f}"
                        send_notification("Gold Structure Update", msg)
                else:
                    Clock.schedule_once(lambda dt: self.update_ui("Not enough data yet, retrying..."))
            except Exception as e:
                Clock.schedule_once(lambda dt, err=str(e): self.update_ui(f"Error fetching data: {err}"))

            time.sleep(CHECK_INTERVAL_SECONDS)

    def update_ui(self, text):
        self.status_label.text = text


if __name__ == "__main__":
    GoldMonitorApp().run()
