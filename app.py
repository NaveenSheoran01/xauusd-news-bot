"""
XAU/USD Zone + News Combo Alert Bot
------------------------------------
- Receives TradingView webhook alerts (Buyer/Seller zone signals)
- Fetches free economic calendar (ForexFactory) for USD high-impact news
- Sends combined alerts to Telegram:
    - Standalone news reminders (30 min before high-impact USD news)
    - Zone alerts from TradingView, with a warning if news is near
"""

import os
import time
import threading
import requests
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# ============================ CONFIG (set as environment variables) ============================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

# Free, unofficial ForexFactory JSON calendar feed (weekly)
FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Keywords that matter most for XAU/USD (gold reacts hardest to USD macro + Fed events)
GOLD_RELEVANT_KEYWORDS = [
    "fomc", "fed", "interest rate", "rate decision", "non-farm", "nfp",
    "cpi", "core cpi", "ppi", "unemployment", "jobless claims",
    "gdp", "retail sales", "powell", "pce"
]

ALERT_MINUTES_BEFORE = 30     # alert this many minutes before high-impact news
NEWS_WARNING_WINDOW  = 30     # if a zone signal comes within this window of news, add a warning

# Keeps track of which news events we've already alerted about (avoid duplicate spam)
alerted_news_ids = set()

# ---- SPEED OPTIMIZATION ----
# Calendar is fetched in the background every 5 min and cached here.
# The webhook handler reads this cache directly (0 network calls) so it can
# reply to TradingView in milliseconds instead of waiting on a live HTTP fetch.
calendar_cache = []
calendar_cache_lock = threading.Lock()

# ============================ TELEGRAM HELPER ============================
def send_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] Telegram not configured, message not sent:", message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=4)
        if r.status_code != 200:
            print("[ERROR] Telegram send failed:", r.text)
    except Exception as e:
        print("[ERROR] Telegram exception:", e)


# ============================ NEWS FETCH ============================
def fetch_calendar():
    """Fetch this week's economic calendar. Returns list of events (dicts)."""
    try:
        r = requests.get(FF_CALENDAR_URL, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("[ERROR] Failed to fetch calendar:", e)
        return []


def is_gold_relevant(event: dict) -> bool:
    if event.get("country") != "USD":
        return False
    if event.get("impact", "").lower() != "high":
        return False
    title = event.get("title", "").lower()
    return any(k in title for k in GOLD_RELEVANT_KEYWORDS)


def parse_event_time(event: dict):
    """ForexFactory feed gives a date string; parse to timezone-aware datetime (UTC)."""
    try:
        # Example format: "2025-01-10T13:30:00-05:00"
        raw = event.get("date")
        if not raw:
            return None
        dt = datetime.fromisoformat(raw)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


# ============================ SELF-PING (keeps Render awake automatically) ============================
# Render provides this env var automatically on deployed services.
SELF_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

def self_ping_job():
    """Pings our own /health endpoint every 10 min so Render's free tier
    never sees 15 min of inactivity and never puts the service to sleep.
    This replaces the need to manually set up an external UptimeRobot monitor."""
    if not SELF_URL:
        print("[WARN] RENDER_EXTERNAL_URL not set, skipping self-ping (set it manually if needed)")
        return
    try:
        r = requests.get(f"{SELF_URL}/health", timeout=10)
        print(f"[INFO] Self-ping OK: {r.status_code}")
    except Exception as e:
        print("[WARN] Self-ping failed:", e)
    """Runs in the background every 5 min. Updates calendar_cache in place."""
    global calendar_cache
    events = fetch_calendar()
    with calendar_cache_lock:
        calendar_cache = events
    print(f"[INFO] Calendar cache refreshed: {len(events)} events")


def get_upcoming_gold_news(within_minutes: int):
    """
    Return list of (event, minutes_until, event_time) for relevant news happening soon.
    Reads from the in-memory cache only — NO live HTTP call here, so this is
    near-instant and safe to call inside the webhook handler.
    """
    with calendar_cache_lock:
        events = list(calendar_cache)
    now = datetime.now(timezone.utc)
    upcoming = []
    for ev in events:
        if not is_gold_relevant(ev):
            continue
        ev_time = parse_event_time(ev)
        if not ev_time:
            continue
        delta_min = (ev_time - now).total_seconds() / 60
        if 0 <= delta_min <= within_minutes:
            upcoming.append((ev, delta_min, ev_time))
    return upcoming


# ============================ SCHEDULED NEWS REMINDER JOB ============================
def check_news_job():
    upcoming = get_upcoming_gold_news(ALERT_MINUTES_BEFORE)
    for ev, mins_left, ev_time in upcoming:
        ev_id = f"{ev.get('title')}_{ev.get('date')}"
        if ev_id in alerted_news_ids:
            continue
        alerted_news_ids.add(ev_id)
        ist_time = ev_time.astimezone(timezone(timedelta(hours=5, minutes=30)))
        msg = (
            f"🔔 <b>Upcoming High-Impact News (XAU/USD)</b>\n"
            f"Event: {ev.get('title')}\n"
            f"Time: {ist_time.strftime('%d-%b %H:%M')} IST (~{int(mins_left)} min away)\n"
            f"Forecast: {ev.get('forecast', 'N/A')} | Previous: {ev.get('previous', 'N/A')}\n"
            f"⚠️ Expect high volatility on Gold around this time."
        )
        send_telegram(msg)


scheduler = BackgroundScheduler()
scheduler.add_job(refresh_calendar_cache, "interval", minutes=5)
scheduler.add_job(check_news_job, "interval", minutes=5)
scheduler.add_job(self_ping_job, "interval", minutes=10)
scheduler.start()

# Pre-load cache and do first self-ping immediately at startup (threaded so app boots instantly)
threading.Thread(target=refresh_calendar_cache, daemon=True).start()
threading.Thread(target=self_ping_job, daemon=True).start()


# ============================ WEBHOOK FROM TRADINGVIEW ============================
@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Single unified webhook for all signals from the Pine Script's alert() calls:

    Zone signal:
        {"type":"buyer_zone","signal":"zone","level":"2650.2","price":"2651.0"}
        {"type":"seller_zone","signal":"zone","level":"2670.0","price":"2669.5"}

    Delta threshold signal:
        {"type":"buyer_zone","signal":"delta_buy","delta":"620","price":"2651.0"}
        {"type":"seller_zone","signal":"delta_sell","delta":"-610","price":"2669.5"}

    Instant news reaction signal (fires the moment price moves past your threshold after news):
        {"type":"news_reaction","signal":"news_buy","bias":"positive","move":"4.2","price":"2655.0","delta":"340"}
        {"type":"news_reaction","signal":"news_sell","bias":"negative","move":"-5.1","price":"2645.0","delta":"-410"}

    Configure this in TradingView Alert -> Webhook URL:
        https://YOUR-RENDER-URL/webhook
    """
    t0 = time.time()
    data = request.get_json(force=True, silent=True) or {}
    signal = data.get("signal", "unknown")
    price = data.get("price", "N/A")

    if signal == "zone":
        side = "buyer_zone" in data.get("type", "")
        emoji = "🟢 STRONG BUYER ZONE" if side else "🔴 STRONG SELLER ZONE"
        msg = f"{emoji} — XAU/USD\nPrice: {price}\nZone Level: {data.get('level','N/A')}"

    elif signal in ("delta_buy", "delta_sell"):
        is_buy = signal == "delta_buy"
        emoji = "🟢 STRONG BUY (Delta Confirmed)" if is_buy else "🔴 STRONG SELL (Delta Confirmed)"
        msg = f"{emoji} — XAU/USD\nPrice: {price}\nDelta: {data.get('delta','N/A')}\n"
        msg += "→ Delta is in the buyer-favorable zone" if is_buy else "→ Delta is in the seller-favorable zone"

    elif signal in ("news_buy", "news_sell"):
        is_buy = signal == "news_buy"
        bias = data.get("bias", "").upper()
        emoji = "⚡🟢 NEWS REACTION: BUY" if is_buy else "⚡🔴 NEWS REACTION: SELL"
        impact = "📈 POSITIVE (Bullish)" if bias == "POSITIVE" else "📉 NEGATIVE (Bearish)"
        msg = (
            f"{emoji} — XAU/USD\n"
            f"Impact: {impact}\n"
            f"Price moved: {data.get('move','N/A')}\n"
            f"Current Price: {price}\n"
            f"Delta: {data.get('delta','N/A')}\n"
            f"⚠️ This reflects the ACTUAL move already happened — not a prediction of what news will do."
        )
    else:
        msg = f"Signal received — XAU/USD\nRaw data: {data}"

    # Reads from in-memory cache only — no network call here, so this stays fast
    near_news = get_upcoming_gold_news(NEWS_WARNING_WINDOW)
    if near_news:
        ev, mins_left, _ = near_news[0]
        msg += f"\n\n🔔 <b>{ev.get('title')}</b> news in ~{int(mins_left)} min — volatility likely."

    # Send to Telegram in a background thread so the webhook returns to
    # TradingView immediately without waiting for Telegram's response
    threading.Thread(target=send_telegram, args=(msg,), daemon=True).start()

    elapsed_ms = int((time.time() - t0) * 1000)
    print(f"[INFO] Webhook processed in {elapsed_ms}ms")
    return jsonify({"status": "ok", "sent": msg, "processing_ms": elapsed_ms}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "alive", "time": datetime.utcnow().isoformat()}), 200


@app.route("/", methods=["GET"])
def home():
    return "XAU/USD News + Zone Bot is running."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
