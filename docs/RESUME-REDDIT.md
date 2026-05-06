# ⏸️ RESUME POINT — Reddit Sentiment Monitor

**Stan:** Wszystkie pliki gotowe, czeka TYLKO na zatwierdzenie Reddit API.

## Pliki już gotowe (nie ruszaj)
- `reddit-monitor/monitor.py` ✅
- `reddit-monitor/requirements.txt` ✅
- `reddit-monitor/reddit-monitor.yml` ✅
- `strategies/reddit-sentiment.md` ✅

## Co zrobić gdy przyjdzie mail od Reddit

**1. Utwórz Reddit app**
- https://www.reddit.com/prefs/apps → "create another app"
- Typ: **script**, Nazwa: `trading-monitor`, Redirect: `http://localhost:8080`
- Zapisz: `client_id` (pod nazwą aplikacji) + `client_secret`

**2. Utwórz Cloudflare Worker `reddit-proxy`**
- Wejdź na dash.cloudflare.com → Workers → Create
- Nazwa: `reddit-proxy`
- Kod: identyczny jak `geopolitical-proxy` (już masz ten kod)
- Dodaj sekrety: `ROUTINE_ENDPOINT` (URL nowej routiny) + `ANTHROPIC_TOKEN`

**3. Dodaj GitHub Secrets**
- Repo → Settings → Secrets → Actions:
  - `REDDIT_CLIENT_ID`
  - `REDDIT_CLIENT_SECRET`
  - `CLOUDFLARE_REDDIT_WORKER_URL`

**4. Skopiuj workflow do repo i push**
```bash
cd /Users/bartlomiejmikos/Documents/Git/trading-system
cp /Users/bartlomiejmikos/Downloads/investing/reddit-monitor/reddit-monitor.yml .github/workflows/
git add -A && git commit -m "Add Reddit sentiment monitor" && git push
```

**5. Utwórz Claude Routine "Reddit Sentiment Handler"**
- claude.ai → Code → Routines → New Routine
- Trigger: API
- Connector: Alpaca MCP
- Prompt: analogiczny do Geopolitical Alert Handler, ale czyta `strategies/reddit-sentiment.md`

**6. Test manualny**
- GitHub → Actions → Reddit Sentiment Monitor → Run workflow
- Sprawdź logi — powinno pojawić się skanowanie 3 subredditów

---
*Stworzono 05.05.2026 — wróć tutaj gdy Reddit zatwierdzi API*
