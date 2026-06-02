# StockScan — Reddit Bullish Sentiment Scanner

A mobile-friendly web app that scans Reddit for bullish stock mentions over the last 24h.

## Files

```
stockscanner/
├── app.py            ← backend (Flask + scanner logic)
├── templates/
│   └── index.html    ← frontend (mobile-friendly UI)
├── requirements.txt  ← Python dependencies
├── Procfile          ← tells Railway how to start the app
└── README.md
```

## Deploy to Railway (free, ~5 minutes)

1. Go to https://github.com and create a free account if you don't have one
2. Create a **New repository** — name it `stockscanner`, set it to Public
3. Upload all these files (drag & drop works on GitHub)
4. Go to https://railway.app — sign up with your GitHub account
5. Click **New Project → Deploy from GitHub repo**
6. Select your `stockscanner` repo
7. Railway auto-detects Python and deploys — takes ~2 minutes
8. Click **Settings → Networking → Generate Domain**
9. You get a public URL like `stockscanner-production.up.railway.app`
10. Bookmark it on your Android — done!

## Usage

- Open the URL on any device
- Press **RUN SCAN** — takes ~60 seconds
- Results show top 10 bullish stocks ranked by weighted sentiment score

## Notes

- Free Railway plan gives 500 hours/month — plenty for personal use
- The scan timeout is set to 120s — if Reddit is slow it may occasionally time out
- NFA — for research purposes only
