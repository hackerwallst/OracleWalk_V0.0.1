# file: oraclewalk/main.py
import os
import sys
from pathlib import Path

from oraclewalk.config.config_loader import AppConfig
from oraclewalk.core.engine import run_backtest, run_live
from oraclewalk.utils.logger import setup_logger

logger = setup_logger(__name__)


def _default_config_path() -> Path:
    """
    Resolve o caminho do config.txt tanto no código-fonte quanto no binário PyInstaller.
    - Em modo congelado (sys.frozen): usa a pasta do executável.
    - Em modo normal: prioriza ORACLEWALK_CONFIG, depois config.txt no CWD,
      por fim tenta a raiz do repo (pai de src/).
    """
    env_path = os.getenv("ORACLEWALK_CONFIG")
    if env_path:
        return Path(env_path)

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "config.txt"

    cwd_candidate = Path.cwd() / "config.txt"
    if cwd_candidate.exists():
        return cwd_candidate

    return Path(__file__).resolve().parents[2] / "config.txt"


def main():
    cfg_path = _default_config_path()
    cfg = AppConfig.from_sources(str(cfg_path))

    logger.info(f"Iniciando OracleWalk em modo: {cfg.mode.upper()}")

    if cfg.mode == "backtest":
        run_backtest(cfg)

    elif cfg.mode == "live":
        run_live(cfg)

    else:
        logger.error(f"Modo inválido no config.txt: {cfg.mode}")
        raise ValueError(f"Modo inválido: {cfg.mode}")


if __name__ == "__main__":
    main()
