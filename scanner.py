import requests
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, render_template

app = Flask(__name__)

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────

SUBREDDITS = [
    "stocks", "investing", "stockmarket",
    "wallstreetbets", "WallStreetBetsELITE", "shortsqueeze",
    "TheRaceTo100K"
]

HOURS_BACK        = 24
POSTS_PER_SUB     = 50
COMMENTS_PER_POST = 10
TOP_N             = 10

ARCTIC  = "https://arctic-shift.photon-reddit.com/api"
HEADERS = {"User-Agent": "StockScanner/2.0 (personal research tool)"}

BULLISH_KEYWORDS = {
    "breakout":       3,
    "all time high":  3,
    "ath":            3,
    "short squeeze":  3,
    "catalyst":       3,
    "upgraded":       3,
    "beat earnings":  3,
    "earnings beat":  3,
    "bullish":        2,
    "going up":       2,
    "undervalued":    2,
    "buy the dip":    2,
    "strong buy":     2,
    "price target":   2,
    "moon":           2,
    "rally":          1,
    "gains":          1,
    "green":          1,
    "pumping":        1,
    "rip":            1,
    "upside":         1,
    "outperform":     1,
}

FALSE_POSITIVE_WORDS = {
    "I", "A", "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL",
    "CAN", "HER", "WAS", "ONE", "OUR", "OUT", "DAY", "GET", "HAS",
    "HIM", "HIS", "HOW", "ITS", "MAY", "NEW", "NOW", "OLD", "SEE",
    "TWO", "WAY", "WHO", "BOY", "DID", "LET", "PUT", "SAY", "SHE",
    "TOO", "USE", "IMO", "TBH", "TIL", "EDIT", "TLDR", "TL", "DR",
    "EPS", "CEO", "CFO", "COO", "CTO", "IPO", "SEC", "ETF", "ATH",
    "DD", "WSB", "USA", "USD", "GDP", "CPI", "FED", "AI", "ML",
    "IT", "US", "UK", "EU", "YOY", "QOQ", "PE", "EV", "RSI",
    "MACD", "SMA", "EMA", "VWAP", "FOMO", "YOLO", "EOD", "EOW",
    "HODL", "LOL", "OMG", "WTF", "JUST", "BEEN", "FROM", "THEY",
    "THIS", "THAT", "WITH", "HAVE", "MORE", "WILL", "YOUR", "ALSO",
    "THAN", "INTO", "OVER", "SOME", "WHAT", "WHEN", "THEN", "THEM",
    "WELL", "ONLY", "LIKE", "EVEN", "BACK", "GOOD", "HERE", "MUCH",
    "VERY", "MOST", "KNOW", "CALL", "PUTS", "PART", "NEXT", "LONG",
    "HIGH", "LAST", "BOTH", "DOES", "HOLD", "SELL", "BEAR", "BULL",
    "DOWN", "PUMP", "DUMP", "RISK", "LOSS", "GAIN", "OPEN", "CASH",
    "FUND", "RATE", "DEBT", "COST", "BEST", "MAKE", "YEAR", "WEEK",
    "SAME", "EACH", "REAL", "NEWS", "SAID", "WENT", "GIVE", "KEEP",
    "TAKE", "COME", "LOOK", "NEED", "FEEL", "WORK", "PLAY", "READ",
    "FIND", "SHOW", "MOVE", "TALK", "MEAN", "MANY", "SURE", "HELP",
    "IDEA", "HUGE", "SEND", "DEAL", "TIME", "GROW", "PLAN", "STOCK",
    "AFAIK", "LMAO", "IIRC", "FWIW", "IMHO", "NFA", "DYOR",
    "UTC", "EST", "PST", "CST", "GMT", "AM", "PM", "OR", "IF", "DO",
    "SO", "GO", "NO", "ON", "AT", "BE", "BY", "IN", "OF", "TO", "UP",
    "AN", "AS", "IS", "MY", "WE", "HE", "ME", "VS", "ET", "RE", "OK",
    "CTB", "SI", "SS", "SHO", "FTD", "HTB", "OTC", "AH", "PH",
    "TTM", "FCF", "DCF", "LBO", "IRR", "NPV", "PNL", "PL", "TA",
    "FA", "RR", "PT", "BUY", "DCA", "ROI", "ROE", "ROA",
    "DIV", "NAV", "AUM", "HFT", "MFI", "OBV", "ATR", "BB", "KC",
    "MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN",
    "JAN", "FEB", "MAR", "APR", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
}

TICKER_PATTERN = re.compile(r'\$([A-Z]{1,5})\b|\b([A-Z]{2,5})\b')


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def cutoff_timestamp():
    dt = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
    return str(int(dt.timestamp()))

def extract_tickers(text):
    tickers = set()
    for match in TICKER_PATTERN.finditer(text):
        candidate = match.group(1) or match.group(2)
        if candidate and candidate not in FALSE_POSITIVE_WORDS:
            tickers.add(candidate)
    return tickers

def score_text(text):
    lower = text.lower()
    return sum(w for kw, w in BULLISH_KEYWORDS.items() if kw in lower)

def extract_snippet(text, ticker, max_len=140):
    for sentence in text.split("."):
        if ticker in sentence and len(sentence.strip()) > 15:
            s = sentence.strip().replace("\n", " ")
            return s[:max_len] + ("…" if len(s) > max_len else "")
    return ""

def fetch_posts(subreddit, after):
    try:
        r = requests.get(
            f"{ARCTIC}/posts/search",
            params={
                "subreddit": subreddit,
                "after":     after,
                "limit":     POSTS_PER_SUB,
                "sort":      "desc",
                "fields":    "id,title,selftext,subreddit",
            },
            headers=HEADERS,
            timeout=10
        )
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        print(f"[!] fetch_posts failed for r/{subreddit}: {e}")
        return []

def fetch_comments(post_id):
    try:
        r = requests.get(
            f"{ARCTIC}/comments/search",
            params={
                "link_id": f"t3_{post_id}",
                "limit":   COMMENTS_PER_POST,
                "sort":    "desc",
                "fields":  "body",
            },
            headers=HEADERS,
            timeout=10
        )
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception:
        return []


# ─────────────────────────────────────────────
#  MAIN SCAN
# ─────────────────────────────────────────────

def run_scan():
    after          = cutoff_timestamp()
    ticker_score   = Counter()
    ticker_mention = Counter()
    ticker_sources = defaultdict(set)
    ticker_snippet = {}
    ticker_link    = {}
    total_posts    = 0
    total_comments = 0

    for sub in SUBREDDITS:
        posts = fetch_posts(sub, after)
        total_posts += len(posts)

        for post in posts:
            post_id    = post.get("id", "")
            title      = post.get("title", "")
            body       = post.get("selftext", "")
            post_sub   = post.get("subreddit", sub)
            thread_url = f"https://reddit.com/r/{post_sub}/comments/{post_id}" if post_id else ""

            full_text     = f"{title} {body}"
            post_score    = score_text(full_text)
            comments      = fetch_comments(post_id)
            total_comments += len(comments)
            comment_text  = " ".join(c.get("body", "") for c in comments)
            comment_score = score_text(comment_text)
            combined_score = post_score + comment_score

            if combined_score == 0:
                continue

            combined_text = f"{full_text} {comment_text}"
            for ticker in extract_tickers(combined_text):
                ticker_score[ticker]   += combined_score
                ticker_mention[ticker] += 1
                ticker_sources[ticker].add(sub)
                if thread_url and ticker not in ticker_link:
                    ticker_link[ticker] = thread_url
                if ticker not in ticker_snippet:
                    ticker_snippet[ticker] = extract_snippet(combined_text, ticker)


    results = []
    for rank, (ticker, score) in enumerate(ticker_score.most_common(TOP_N), 1):
        results.append({
            "rank":     rank,
            "ticker":   ticker,
            "score":    score,
            "mentions": ticker_mention[ticker],
            "sources":  sorted(ticker_sources[ticker]),
            "snippet":  ticker_snippet.get(ticker, ""),
            "link":     ticker_link.get(ticker, ""),
        })

    return {
        "results":        results,
        "total_posts":    total_posts,
        "total_comments": total_comments,
        "hours_back":     HOURS_BACK,
        "scanned_at":     datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        "debug":          f"scored tickers: {len(ticker_score)}, top5: {ticker_score.most_common(5)}",
    }


# ─────────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/scan")
def api_scan():
    try:
        data = run_scan()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
