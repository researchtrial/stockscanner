import requests
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────

SUBREDDITS = [
    "stocks", "investing", "stockmarket",
    "wallstreetbets", "WallStreetBetsELITE", "shortsqueeze",
    "TheRaceTo100K"
]

HOURS_BACK      = 24    # only scan posts/comments from last 48 hours
POSTS_PER_SUB   = 50   # Arctic Shift max per request
COMMENTS_PER_POST = 10  # top N comments to scan per post
TOP_N           = 10    # leaderboard size

# Arctic Shift base URL
ARCTIC = "https://arctic-shift.photon-reddit.com/api"

HEADERS = {"User-Agent": "StockScanner/2.0 (personal research tool)"}

# ─────────────────────────────────────────────
#  BULLISH KEYWORDS  (weighted)
# ─────────────────────────────────────────────

BULLISH_KEYWORDS = {
    # Strong signals (weight 3)
    "breakout":       3,
    "all time high":  3,
    "ath":            3,
    "short squeeze":  3,
    "catalyst":       3,
    "upgraded":       3,
    "beat earnings":  3,
    "earnings beat":  3,
    # Medium signals (weight 2)
    "bullish":        2,
    "going up":       2,
    "undervalued":    2,
    "buy the dip":    2,
    "strong buy":     2,
    "price target":   2,
    "moon":           2,
    # Softer signals (weight 1)
    "rally":          1,
    "gains":          1,
    "green":          1,
    "pumping":        1,
    "rip":            1,
    "upside":         1,
    "outperform":     1,
}

# ─────────────────────────────────────────────
#  TICKER FILTERING
# ─────────────────────────────────────────────

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
    # Time / grammar / Reddit jargon
    "UTC", "EST", "PST", "CST", "GMT", "AM", "PM", "OR", "IF", "DO",
    "SO", "GO", "NO", "ON", "AT", "BE", "BY", "IN", "OF", "TO", "UP",
    "AN", "AS", "IS", "MY", "WE", "HE", "ME", "VS", "ET", "RE", "OK",
    # Short-selling / borrow jargon (not tickers)
    "CTB", "SI", "SS", "SHO", "FTD", "HTB", "OTC", "AH", "PH",
    # Finance abbreviations
    "TTM", "FCF", "DCF", "LBO", "IRR", "NPV", "PNL", "PL", "TA",
    "FA", "RR", "PT", "BUY", "DCA", "ROI", "ROE", "ROA", "EPS",
    "DIV", "NAV", "AUM", "HFT", "MFI", "OBV", "ATR", "BB", "KC",
    # Days / months
    "MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN",
    "JAN", "FEB", "MAR", "APR", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
}

TICKER_PATTERN = re.compile(r'\$([A-Z]{1,5})\b|\b([A-Z]{2,5})\b')


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def cutoff_timestamp() -> str:
    """Epoch seconds for HOURS_BACK hours ago — Arctic Shift accepts epoch timestamps."""
    dt = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
    return str(int(dt.timestamp()))


def extract_tickers(text: str) -> set:
    tickers = set()
    for match in TICKER_PATTERN.finditer(text):
        candidate = match.group(1) or match.group(2)
        if candidate and candidate not in FALSE_POSITIVE_WORDS:
            tickers.add(candidate)
    return tickers


def score_text(text: str) -> int:
    lower = text.lower()
    return sum(w for kw, w in BULLISH_KEYWORDS.items() if kw in lower)


def extract_snippet(text: str, ticker: str, max_len: int = 140) -> str:
    for sentence in text.split("."):
        if ticker in sentence and len(sentence.strip()) > 15:
            s = sentence.strip().replace("\n", " ")
            return s[:max_len] + ("…" if len(s) > max_len else "")
    return "—"


def fetch_posts(subreddit: str, after: str) -> list:
    """Fetch up to POSTS_PER_SUB posts from Arctic Shift after a given time."""
    url = f"{ARCTIC}/posts/search"
    params = {
        "subreddit": subreddit,
        "after":     after,
        "limit":     POSTS_PER_SUB,
        "sort":      "desc",          # newest first
        "fields":    "id,title,selftext,subreddit",  # permalink not a valid field
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        print(f"  [!] Posts fetch failed for r/{subreddit}: {e}")
        return []


def fetch_comments(post_id: str) -> list:
    """Fetch top comments for a post from Arctic Shift."""
    url = f"{ARCTIC}/comments/search"
    params = {
        "link_id": f"t3_{post_id}",
        "limit":   COMMENTS_PER_POST,
        "sort":    "desc",
        "fields":  "body",
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception:
        return []   # comments are best-effort, don't print noise


# ─────────────────────────────────────────────
#  MAIN SCANNER
# ─────────────────────────────────────────────

def scan_bullish_trends():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    after     = cutoff_timestamp()

    print(f"\n  📡  StockScanner v2  ·  {timestamp}")
    print(f"  Window : last {HOURS_BACK}h  |  Posts/sub: {POSTS_PER_SUB}  |  Comments/post: {COMMENTS_PER_POST}")
    print(f"  Subreddits: {', '.join('r/'+s for s in SUBREDDITS)}\n")

    ticker_score:   Counter               = Counter()
    ticker_mention: Counter               = Counter()
    ticker_sources: defaultdict           = defaultdict(set)
    ticker_snippet: dict                  = {}
    ticker_link:    dict                  = {}

    total_posts    = 0
    total_comments = 0

    for sub in SUBREDDITS:
        print(f"  ⏳  Scanning r/{sub}...", end=" ", flush=True)
        posts = fetch_posts(sub, after)
        print(f"{len(posts)} posts", end="")

        sub_comments = 0
        for post in posts:
            post_id   = post.get("id", "")
            title     = post.get("title", "")
            body      = post.get("selftext", "")
            sub       = post.get("subreddit", sub)
            # Build URL from id — Arctic Shift doesn't return permalink
            thread_url = f"https://reddit.com/r/{sub}/comments/{post_id}" if post_id else None

            # --- scan post text ---
            full_text  = f"{title} {body}"
            post_score = score_text(full_text)

            # --- scan comments (best-effort) ---
            comments = fetch_comments(post_id)
            sub_comments += len(comments)
            comment_text = " ".join(c.get("body", "") for c in comments)
            comment_score = score_text(comment_text)

            combined_score = post_score + comment_score
            if combined_score == 0:
                continue

            combined_text = f"{full_text} {comment_text}"
            tickers = extract_tickers(combined_text)

            for ticker in tickers:
                ticker_score[ticker]   += combined_score
                ticker_mention[ticker] += 1
                ticker_sources[ticker].add(f"r/{sub}")
                if thread_url and ticker not in ticker_link:
                    ticker_link[ticker] = thread_url
                if ticker not in ticker_snippet:
                    ticker_snippet[ticker] = extract_snippet(combined_text, ticker)

            time.sleep(0.05)   # gentle rate limiting

        total_posts    += len(posts)
        total_comments += sub_comments
        print(f"  ·  {sub_comments} comments")

    # ── OUTPUT ──────────────────────────────────────────────────────────────

    divider = "═" * 68
    print(f"\n{divider}")
    print(f"  📈  BULLISH MOMENTUM LEADERBOARD  ·  Top {TOP_N}  ·  Last {HOURS_BACK}h")
    print(f"  Scanned {total_posts} posts  ·  {total_comments} comments")
    print(f"{divider}\n")

    if not ticker_score:
        print("  No bullish sentiment detected. Try widening HOURS_BACK or adding subreddits.\n")
        return

    for rank, (ticker, score) in enumerate(ticker_score.most_common(TOP_N), 1):
        mentions  = ticker_mention[ticker]
        sources   = " · ".join(sorted(ticker_sources[ticker]))
        link      = ticker_link.get(ticker, "N/A")
        snippet   = ticker_snippet.get(ticker, "—")

        bar_fill  = min(score // 3, 20)
        momentum  = "█" * bar_fill + "░" * (20 - bar_fill)

        print(f"  #{rank:>2}  ${ticker:<6}  Score: {score:>4}  Mentions: {mentions:>3}")
        print(f"       Momentum : [{momentum}]")
        print(f"       Sources  : {sources}")
        print(f"       Snippet  : {snippet}")
        print(f"       Link     : {link}")
        print()

    print(divider)
    print("  NFA — for research purposes only.\n")


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # Quick connectivity check before full scan
    print("  Checking Arctic Shift connection...")
    try:
        test = requests.get(
            f"{ARCTIC}/posts/search",
            params={"subreddit": "stocks", "limit": 1},
            headers=HEADERS,
            timeout=6
        )
        if test.status_code == 200:
            print("  ✅  Arctic Shift reachable — starting scan\n")
            scan_bullish_trends()
        else:
            print(f"  ❌  Arctic Shift returned HTTP {test.status_code}")
            print("  Try again later or check https://arctic-shift.photon-reddit.com")
    except requests.exceptions.ConnectionError:
        print("  ❌  Cannot reach Arctic Shift — check your internet connection.")
    except requests.exceptions.Timeout:
        print("  ❌  Arctic Shift timed out.")