"""
Compat para Python 3.13+: módulo imghdr foi removido da stdlib.
Aqui implementamos um stub mínimo apenas para satisfazer imports de libs que ainda dependem dele.
Retorna sempre None (detecção de imagem não é necessária para mensagens de texto do bot).
"""

def what(file=None, h=None):
    return None
