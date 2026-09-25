# XAU/USD Zone + News Combo Bot — Setup Guide (Hinglish)

Ye bot 2 kaam karta hai:
1. Har 5 min mein free ForexFactory calendar check karta hai — jab bhi koi **High Impact USD news** (Fed, NFP, CPI etc.) 30 min door ho, Telegram pe reminder bhejta hai.
2. TradingView se aapka Pine Script indicator jab "Strong Buyer/Seller Zone" bana ta hai, alert webhook ke through is bot ko bhejta hai — bot us alert ko Telegram pe forward karta hai, aur agar news paas hai to warning bhi jod deta hai.

---

## Step 1: Telegram Bot Banao (5 min)

1. Telegram open karo, search karo **@BotFather**
2. `/newbot` command bhejo, naam do (jaise `XAUUSD Alert Bot`)
3. BotFather aapko ek **token** dega — jaise `123456789:ABCdefGhIJKlmNoPQRstuVwxyZ` — ise save kar lo
4. Ab apne bot ko Telegram pe search karke ek message bhejo (jaise "hi") — ye zaroori hai warna bot aapko message nahi bhej payega
5. Apna **Chat ID** nikalne ke liye browser mein ye URL kholo (token apna daal do):
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
   Response mein `"chat":{"id": 123456789...}` milega — ye aapka `TELEGRAM_CHAT_ID` hai

---

## Step 2: Render.com pe Free Deploy (10 min)

1. [render.com](https://render.com) pe free account banao (GitHub se sign up kar sakte ho)
2. Ye poora `xauusd-news-bot` folder GitHub pe ek naye repo mein upload karo
3. Render dashboard mein → **New +** → **Web Service** → apna GitHub repo select karo
4. Settings:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
5. **Environment Variables** add karo:
   - `TELEGRAM_BOT_TOKEN` = aapka bot token
   - `TELEGRAM_CHAT_ID` = aapka chat id
6. Deploy karo — kuch minute mein aapko ek URL milega jaisa:
   ```
   https://xauusd-news-bot.onrender.com
   ```

> **Free tier note**: Render free service 15 min inactivity ke baad sleep ho jati hai. **Ab ye automatic handle hota hai** — bot khud har 10 min mein apne aap ko ping karta hai (`self_ping_job` in `app.py`), isliye alag se UptimeRobot account banane ki zarurat nahi hai. Render aapko `RENDER_EXTERNAL_URL` environment variable automatically deta hai, bot usi ko use karta hai.

---

## Step 3: TradingView Pe SIRF EK Alert Banao

1. Apna updated Pine Script (`XAUUSD_Zones_Delta_News.pine`) chart pe laga do
2. Chart pe **Alert** icon (ghanti) click karo → **Create Alert**
3. **Condition** mein apna indicator select karo, dropdown mein **"Any alert() function call"** choose karo (specific condition select karne ki zarurat nahi — script khud decide karega kaunsa signal bhejna hai)
4. **Alert actions** mein "Webhook URL" enable karo, daalo:
   ```
   https://xauusd-news-bot.onrender.com/webhook
   ```
5. **Message box khaali chhod do** — script khud JSON message bhejta hai, TradingView ka default message overwrite ho jayega
6. **Alert frequency**: "Once Per Bar" rakho (speed ke liye)
7. Save karo — bas ab **ek hi alert** se teeno signal (zone, delta, news reaction) automatically Telegram pe aayenge

---

## Delta Level Kaise Set Karo (Buyer vs Seller)

Pine Script mein 2 input hain:
- `Strong BUY Delta Level` — jab **rolling delta isse zyada** ho jaaye, matlab buyers dominant hain
- `Strong SELL Delta Level` — jab **rolling delta isse kam (negative)** ho jaaye, matlab sellers dominant hain

**Sahi number kaise pata karein (aapko khud calibrate karna hai, koi universal number nahi hota):**
1. Indicator chart pe lagao, top-right table mein "Current Delta" dekho — normal market mein ye kis range mein ghoomta hai (jaise -200 se +200)
2. Jab bhi price strongly ek direction mein move kare (bina news ke bhi), us waqt delta value note karo — wahi aapka **threshold** hai
3. XAU/USD active session (London/NY overlap, roughly 6:30 PM – 11:30 PM IST) mein delta zyada volatile hota hai — Asian session mein kam. Isliye ek hi fixed number sab session pe kaam nahi karega; agar zyada precision chahiye to session ke hisaab se alag threshold rakhna padega (abhi ye manual hai)
4. Start karne ke liye: normal range ka **2-3x** value ko threshold banao, phir kuch din dekh kar fine-tune karo

---

## Kya Milega Telegram Pe (3 Types)

**1. Zone Signal:**
```
🟢 STRONG BUYER ZONE — XAU/USD
Price: 2651.0
Zone Level: 2650.2
```

**2. Delta Threshold Signal:**
```
🟢 STRONG BUY (Delta Confirmed) — XAU/USD
Price: 2651.0
Delta: 620
→ Delta is in the buyer-favorable zone
```

**3. Instant News Reaction (fires the moment price actually moves past your set threshold — usually within 1.5-4 sec of that move happening, not from the exact news second):**
```
⚡🟢 NEWS REACTION: BUY — XAU/USD
Impact: 📈 POSITIVE (Bullish)
Price moved: 4.2
Current Price: 2655.0
Delta: 340
⚠️ This reflects the ACTUAL move already happened — not a prediction of what news will do.
```

---

## Speed Optimization — 2-5 Sec Latency Ke Liye

Bot ab **cache-based** hai — news calendar background mein har 5 min refresh hoti hai, webhook ke andar koi live HTTP call nahi hota. Isse bot ka apna processing time **~50-200 milliseconds** ho gaya hai. Baaki delay in cheezon se aata hai (inko fix karna zaroori hai):

1. **TradingView Alert Frequency** (ye ek-baar ka setup hai, roz nahi karna): Alert banate waqt "Alert actions" mein frequency **"Once Per Bar"** rakho, "Once Per Bar Close" mat rakho — warna alert candle band hone tak wait karega (1 min chart pe 60 sec tak ka delay ho sakta hai). Ek baar set karne ke baad ye hamesha usi tarah chalta rahega jab tak alert delete na karo — koi baar-baar ka manual kaam nahi hai. TradingView koi public API nahi deta jisse alerts ko code se create/edit kiya ja sake, isliye ye ek click hamesha manual hi rahega.

2. **Chart Timeframe**: Jitna chhota timeframe utni jaldi signal fire hoga. 1-min chart pe realtime tick pe bhi alert fire ho sakta hai (agar frequency "Once Per Bar" hai), lekin agar aapko seconds-level precision chahiye to TradingView ke **paid plan** mein **1-second chart** try karo

3. **Render Server Hamesha Warm (ab fully automatic)**: Bot khud har 10 min mein apne aap ko ping karta hai — koi UptimeRobot ya manual monitor setup ki zarurat nahi. Deploy karte hi ye khud-ba-khud shuru ho jata hai

4. **Check Actual Speed**: Render dashboard ke **Logs** tab mein jaake dekho — har webhook ke saath `[INFO] Webhook processed in XXXms` print hoga. Ye batayega ki bot khud kitna fast hai (network delay ke alawa)

**Realistic total time breakdown:**
| Step | Time |
|---|---|
| TradingView condition detect + alert fire | ~0.5-2 sec (frequency setting pe depend) |
| Webhook network travel to Render | ~0.2-0.5 sec |
| Bot processing (cache-based) | ~0.05-0.2 sec |
| Telegram deliver to your phone | ~0.5-1 sec |
| **Total** | **~1.5-4 sec (warm server ke saath)** |

Isse fast (sach mein sub-second) sirf tab possible hai jab TradingView ki jagah **direct broker API (MT5/MT4 Expert Advisor)** use karo, jo tick-by-tick data pe seedha chalta hai — lekin wo alag setup hai, TradingView-based nahi.

---

## Important Limitations (sach mein samajhna zaroori)

- ForexFactory ka ye feed **unofficial/free** hai — kabhi kabhi format change ho sakta hai ya down ho sakta hai. Agar reliability chahiye to paid API (TradingEconomics, Finnhub) use karo — bas `FF_CALENDAR_URL` wala function replace karna hoga.
- Ye bot **news ka result predict nahi karta** — sirf reminder deta hai ki news aane wali hai, taaki aap savdhaan rahein. Actual result (bullish/bearish) sirf news release ke baad hi pata chalta hai.
- Render free tier thoda slow start le sakta hai (cold start ~30-50 sec) agar bahut der se sola raha ho — UptimeRobot lagane se ye issue nahi hoga.
