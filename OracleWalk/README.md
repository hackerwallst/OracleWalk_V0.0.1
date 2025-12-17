# OracleWalk

Framework de trading automatizado para Binance com estratégias ICT/FVG e MA+RSI, modos backtest e live, dashboard em Flask, alertas no Telegram e builds executáveis para Windows/Linux. English version below.

---
## Português

### O que resolve
- Roda estratégia ICT (Fair Value Gap) pronta, com controles de risco e preço de execução.
- Dashboard web (Flask + Lightweight Charts) com candles, indicadores, trades, orderbook e equity.
- Suporta trading ao vivo (ou `dry_run`) e backtests rápidos com dados Binance.
- Scripts de build geram executável standalone via PyInstaller.

### Arquitetura (resumo)
- **core**: orquestra engine (`run_backtest`, `run_live`).
- **config**: carrega `.env` ou `config.txt`.
- **data**: histórico/WS de klines e orderbook, indicadores.
- **strategy**: estratégias ICT (FVG) e MA+RSI.
- **execution**: gestão de risco, modelo de preço (slippage/fees), executor/logger.
- **notifications**: wrapper do Telegram.
- **dashboard**: servidor Flask + assets estáticos.
- **optimization**: backtester simples + grid search walk-forward.
- **storage**: persistência SQLite para trades/equity.

Detalhes completos em `docs/architecture.md`.

### Estrutura do repositório
```
/src/oraclewalk
  core/            # engine principal
  config/          # carregamento de config (.env / config.txt)
  data/            # histórico/live, indicadores, orderbook
  execution/       # risco, executor, modelo de preço
  strategy/        # estratégias ICT + MA/RSI
  dashboard/       # Flask + estáticos
  notifications/   # Telegram
  optimization/    # backtester + walk-forward
  storage/         # SQLite
docs/              # arquitetura, setup/uso
tests/             # unit tests (unittest)
requirements.txt
config.example.txt
.env.example
build_executable*.{bat,ps1,sh}
install_all_dependencies.bat
pyproject.toml
```

### Requisitos
- Python 3.10+ (testado 3.8–3.13; prefira >=3.10)
- pip/venv
- Chaves da Binance e credenciais do bot do Telegram para live/alertas

### Instalação (manual)
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```
No Windows, você pode usar `install_all_dependencies.bat` na raiz (cria `.venv` e instala dependências).

### Configuração
Escolha:
- `.env` (recomendado): copie `.env.example` → `.env` e preencha.
- `config.txt`: copie `config.example.txt` → `config.txt` e preencha.
- Opcional: `ORACLEWALK_CONFIG=/caminho/para/config.txt` para apontar fora da raiz.

Chaves importantes:
- `BINANCE_API_KEY`, `BINANCE_API_SECRET`
- `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` (opcional, mas recomendado)
- `MODE` (`backtest`|`live`), `SYMBOLS`, `TIMEFRAME`, `RISK_PER_TRADE`, `DRY_RUN`

`AppConfig.from_sources` lê `.env` e `config.txt` (raiz por padrão).

### Execução
Ative a venv e, na raiz:
```bash
python -m oraclewalk.main
```
Depende de `mode`:
- **backtest**: busca dados recentes, roda estratégia ICT no backtester e envia resumo no Telegram.
- **live**: inicia WebSocket (kline/book), dashboard (http://127.0.0.1:8000), loop da estratégia, risco/execução e alertas. `dry_run=true` simula ordens.

### Dashboard
- Sobe automaticamente no live em `http://127.0.0.1:8000`.
- Exibe candles + MA/RSI, trades, profundidade do book, equity e retângulos FVG.

### Builds de executáveis
- Linux/macOS: `./build_executable.sh`
- Windows: `build_executable_windows.bat` ou `.ps1`
Binários ficam em `dist/`. Coloque `config.txt` e `trades.csv` ao lado do executável.

### Testes
```bash
python -m unittest discover -s tests -p "test_*.py"
```

### Riscos e segurança
- Trading ao vivo é arriscado; use `dry_run=true` até estar seguro.
- Não versionar chaves ( `.env`, `config.txt` estão no `.gitignore`).
- Revise slippage/fees e sizing antes de ir para produção.

---
## English

### What it does
- Runs a ready-to-use ICT (Fair Value Gap) strategy with risk controls and execution pricing.
- Web dashboard (Flask + Lightweight Charts) for candles, indicators, trades, orderbook, and equity.
- Supports live trading (or `dry_run`) plus fast backtests on Binance data.
- Build scripts generate standalone executables via PyInstaller.

### Architecture (overview)
- **core**: engine orchestration (`run_backtest`, `run_live`).
- **config**: loads `.env` or `config.txt`.
- **data**: historical fetcher, WebSocket kline/book, indicators, orderbook handler.
- **strategy**: ICT (FVG) and MA+RSI.
- **execution**: risk manager, price model (slippage/fees), trade executor/logger.
- **notifications**: Telegram wrapper.
- **dashboard**: Flask server + static assets.
- **optimization**: simple backtester + walk-forward grid search.
- **storage**: SQLite persistence for trades/equity.

Full flow details in `docs/architecture.md`.

### Repository layout
```
/src/oraclewalk
  core/            # main engine
  config/          # config loader (.env / config.txt)
  data/            # historical/live handlers, indicators, orderbook
  execution/       # risk, executor, price model, trade logging
  strategy/        # ICT + MA/RSI strategies
  dashboard/       # Flask server + static assets
  notifications/   # Telegram notifier
  optimization/    # backtester + walk-forward optimizer
  storage/         # SQLite manager
docs/              # architecture, setup/usage, references
tests/             # unit tests (unittest)
requirements.txt
config.example.txt
.env.example
build_executable*.{bat,ps1,sh}
install_all_dependencies.bat
pyproject.toml
```

### Requirements
- Python 3.10+ (tested 3.8–3.13; prefer >=3.10)
- pip/venv
- Binance API keys and Telegram bot credentials for live/alerts

### Installation (manual)
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```
Windows convenience: run `install_all_dependencies.bat` from repo root (creates `.venv` and installs dependencies).

### Configuration
Pick one:
- `.env` (recommended): copy `.env.example` → `.env` and fill values.
- `config.txt`: copy `config.example.txt` → `config.txt` and fill values.
- Optional: set `ORACLEWALK_CONFIG=/path/to/config.txt` to point outside the repo root.

Important keys:
- `BINANCE_API_KEY`, `BINANCE_API_SECRET`
- `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` (optional but recommended)
- `MODE` (`backtest`|`live`), `SYMBOLS`, `TIMEFRAME`, `RISK_PER_TRADE`, `DRY_RUN`

`AppConfig.from_sources` loads `.env` + the provided `config.txt` path (default: project root).

### Running
Activate your venv, then from the project root:
```bash
python -m oraclewalk.main
```
Behavior depends on `mode`:
- **backtest**: fetches recent data, runs the ICT strategy through the backtester, and sends a Telegram summary.
- **live**: spins up WebSocket (kline/book), dashboard (http://127.0.0.1:8000), strategy loop, risk/execution, Telegram alerts. `dry_run=true` keeps orders simulated.

### Dashboard
- Auto-starts in live mode at `http://127.0.0.1:8000`.
- Shows candles + MA/RSI, trades, orderbook depth, equity, and FVG rectangles.

### Building executables
- Linux/macOS: `./build_executable.sh`
- Windows: `build_executable_windows.bat` or `build_executable_windows.ps1`
Executables land in `dist/`. Place `config.txt` and `trades.csv` beside the binary to run.

### Testing
```bash
python -m unittest discover -s tests -p "test_*.py"
```

### Risk & safety
- Live trading is risky. Use `dry_run=true` until fully confident.
- Keep API keys out of source control (`.env`, `config.txt` are gitignored).
- Review slippage/fee settings and position sizing before going live.

## License
MIT - see `LICENSE`.

## Contributing
Pull requests welcome. Please:
- Keep logic parity; document any behavior changes.
- Add/adjust tests where feasible.
- Update docs when changing flows or configs.
