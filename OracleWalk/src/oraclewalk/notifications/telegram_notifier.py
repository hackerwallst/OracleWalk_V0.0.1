# file: oraclewalk/notifications/telegram_notifier.py

from typing import Optional
import sys
import types
from oraclewalk.utils.logger import setup_logger

logger = setup_logger(__name__)

# python-telegram-bot (13.x) pode falhar no Python 3.13 por dependências removidas (ex.: imghdr, urllib3.contrib.appengine).
# Tentamos importar; se faltar urllib3.contrib.appengine, injetamos um stub mínimo e reimportamos.
Bot = None  # type: ignore
try:
    from telegram import Bot as _Bot  # type: ignore
    Bot = _Bot
except Exception as e:
    if "urllib3.contrib.appengine" in str(e):
        try:
            stub = types.ModuleType("appengine")
            stub.is_appengine_sandbox = lambda: False
            stub.is_local_appengine = lambda: False
            # garante pacote urllib3.contrib presente
            contrib_pkg = types.ModuleType("urllib3.contrib")
            contrib_pkg.appengine = stub
            sys.modules["urllib3.contrib"] = contrib_pkg
            sys.modules["urllib3.contrib.appengine"] = stub
            from telegram import Bot as _Bot  # type: ignore
            Bot = _Bot
            logger.warning("Telegram: aplicado stub para urllib3.contrib.appengine (Python 3.13).")
        except Exception as e2:
            logger.warning(f"Telegram Bot indisponível (stub falhou): {e2}. Notificações serão apenas logadas.")
    else:
        logger.warning(f"Telegram Bot indisponível: {e}. Notificações serão apenas logadas.")


class TelegramNotifier:
    """
    Wrapper simples para envio de mensagens Telegram.
    Se a lib não estiver disponível ou der erro (caso do Python 3.13),
    apenas registra a mensagem no log e segue o jogo.
    """

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.bot: Optional["Bot"] = None  # type: ignore

        if Bot is not None and token and chat_id:
            try:
                self.bot = Bot(token=self.token)
            except Exception as e:
                logger.warning(f"Falha ao inicializar Bot Telegram: {e}")
                self.bot = None
        else:
            if Bot is None:
                logger.info("Telegram Bot não disponível. Notificações apenas em log.")
            else:
                logger.info("Token ou chat_id vazios. Notificações apenas em log.")

    def send(self, text: str) -> None:
        if self.bot is None:
            # fallback: só loga
            logger.info(f"[TELEGRAM MOCK] {text}")
            return

        try:
            self.bot.send_message(chat_id=self.chat_id, text=text)
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem Telegram: {e}")
