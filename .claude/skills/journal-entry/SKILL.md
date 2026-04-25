---
name: journal-entry
description: Zapisuje trade do dziennika. Wywołuj po każdym wykonanym lub odrzuconym tradzie.
allowed-tools: Read, Write
---

# Journal Entry

Dopisuje wpis do pliku journal/trades-YYYY-MM-DD.md (tworzy plik jeśli nie istnieje).

## Format wpisu

## HH:MM | SYMBOL | BUY/SELL | strategia | EXECUTED/REJECTED

- Entry: $X.XX | SL: $X.XX | TP: $X.XX
- Size: $XXXX (X.X% equity)
- R:R ratio: X.X
- Risk officer: APPROVE/REJECT — powód
- Order ID: XXX (jeśli executed)
- Powód odrzucenia: XXX (jeśli rejected)

---

Po dopisaniu wróć z: { "logged": true, "file": "journal/trades-YYYY-MM-DD.md" }
