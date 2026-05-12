# Whitelist dozwolonych instrumentów

**Wersja: 2.0 (2026-05-06) — risk-on overhaul**
Źródło prawdy: `docs/STRATEGY.md` §10.

## Akcje US (mega-cap)
AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA

## Financials
JPM, V, MA, JNJ, BRK.B

## ETF (szeroki rynek)
SPY, QQQ, VOO, VTI, IWM, VXUS, VWO

## ETF (sektory)
XLK, XLF, XLE, XLV, XLY

## Surowce ETF
GLD, SLV

## Krypto (Alpaca) — v2.4 (2026-05-12) predator expansion

### Tier 1 — proven majors (full size, standard TP/SL)
BTC/USD, ETH/USD

### Tier 2 — mid-cap alts (quick-win mode: $2.5k, TP +10%, SL -8%)
SOL/USD, AVAX/USD, LINK/USD, DOT/USD, MATIC/USD, LTC/USD, BCH/USD,
UNI/USD, AAVE/USD

Per-tier params: see `crypto-monitor/monitor.py::COIN_TIERS`.
Predator filters: 24h move 3-15% bracket, BTC dominance guard
(-3% in 1h blocks alt longs), max 3 simultaneous alt positions.
Combined cap $25k. LLM Curator validates each scan.

## Spółki obronne — Big-5
RTX, LMT, NOC, GD, BA

## Spółki obronne — Mid-cap
KTOS, PLTR, AXON, LDOS, SAIC, CACI

## Defense ETF
ITA, XAR, DFEN

## European defense ADR
BAESY, EADSY

## Energia
XOM, CVX

## Lewarowane ETF (3×) — RISK-ON, dodane 2026-05-06
TQQQ, SQQQ, SPXL, SPXS, UPRO, SPXU
SOXL, SOXS, FAS, FAZ, TNA, TZA

## High-beta single names — dodane 2026-05-06
COIN  (Coinbase — proxy crypto)
MSTR  (MicroStrategy — proxy BTC z lewarem)
ARM   (Arm Holdings — momentum AI/chip)
SMCI  (Super Micro — high-beta AI)

---

## Czego TU NIE MA i dlaczego

- **Penny stocks** — brak płynności, manipulacja
- **Volatility ETP** (VXX, UVXY) — decay zjada pozycję
- **Małe biotechs** — earnings/binarne ryzyko niemierzalne
- **Single-stock leveraged ETFs** (TSLZ, NVDS, NVDL, etc.) — wąska płynność, gap risk
- **OTC / dark pool only** — execution issues
- **SPACs** — pre-merger niemiarodajne fundamenty

## Dodawanie nowego tickera

1. Dodać tu (sekcja odpowiedniej klasy)
2. Zaktualizować `docs/STRATEGY.md` §10
3. Zaktualizować właściwy `strategies/*.md` jeśli wymaga sizing-u
4. Zaktualizować odpowiedni monitor (`TICKERS_*` array)
5. Commit + push
