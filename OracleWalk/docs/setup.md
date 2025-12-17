# Setup & Uso

## 1) Pré-requisitos
- Python 3.10+ (pip/venv)
- Chaves Binance e credenciais do bot Telegram para modo live/alertas

## 2) Instalação rápida
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

Windows: `install_all_dependencies.bat` automatiza venv + pip.

## 3) Configuração
1. Copie `.env.example` → `.env` **ou** `config.example.txt` → `config.txt`.
2. Preencha:
   - `BINANCE_API_KEY` / `BINANCE_API_SECRET`
   - `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID` (opcional, mas recomendado)
   - `MODE` (`backtest` | `live`)
   - `DRY_RUN` (`true` para simular)
   - `SYMBOLS`, `TIMEFRAME`, `RISK_PER_TRADE`, `SLIPPAGE`, `COMMISSION_*`
3. Arquivos sensíveis já estão no `.gitignore`.

`AppConfig.from_sources` lê `.env` e, se existir, `config.txt` na raiz (ou caminho passado).\
Opcional: defina `ORACLEWALK_CONFIG=/caminho/para/config.txt` para customizar o local do arquivo.

## 4) Executando
Ative a venv e rode a partir da raiz:
```bash
python -m oraclewalk.main
```

- **backtest**: baixa dados recentes, roda estratégia ICT, gera resumo via Telegram.
- **live**:
  - Conecta WebSocket (kline + bookTicker + aggTrade)
  - Sobe dashboard em http://127.0.0.1:8000
  - Executa estratégia ICT em loop, checa SL/TP, envia alertas Telegram
  - `dry_run=true` mantém execução simulada.

## 5) Dashboard
- Autoabre no navegador em modo live.
- Endpoints:
  - `/api/candles`, `/api/trades`, `/api/orderbook`, `/api/fvg`, `/api/equity`, `/api/debug`
- Buffers internos separados para histórico (candles fechados) e live (candle em formação).

## 6) Builds
- Linux/macOS: `./build_executable.sh`
- Windows: `build_executable_windows.bat` ou `build_executable_windows.ps1`
Coloque `config.txt` e `trades.csv` ao lado do binário para rodar.

## 7) Testes
```bash
python -m unittest discover -s tests -p "test_*.py"
```

## 8) Logs & dados
- Logs: `oraclewalk.log` (stdout + arquivo) + `logs/trades_*.csv`
- Trades: `trades.csv`
- DB: `oraclewalk.db` (SQLite)
- Posição aberta persistida em `open_position.json`
Todos ignorados pelo `.gitignore` por padrão.

## 9) Boas práticas
- Valide em `backtest` ou `live` com `dry_run=true` antes de usar chave real.
- Revise `slippage`/`commission` conforme a conta Binance (spot/futures).
- Atualize `risk_per_trade` de acordo com a alavancagem e tolerância de perda.
