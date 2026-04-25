"""
MstreamTrader - Notifications toast pour Kivy.

Remplace le pattern "status_text en bas du formulaire" qui était :
  - Invisible si l'utilisateur a scrollé
  - Pas évident qu'une action a réussi/échoué
  - Mal placé (en bas, alors que le bouton cliqué est souvent en haut)

Cette approche :
  - Affiche un Popup centré, sans bordure, semi-transparent
  - Auto-dismiss après N secondes (3s par défaut)
  - 4 niveaux : info (bleu), success (vert), warning (orange), error (rouge)
  - Couleur de fond bien contrastée → on voit toujours le message
  - Re-stylable via les paramètres
"""

from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.clock import Clock
from kivy.metrics import dp


# 4 thèmes de couleur pour différencier visuellement
_THEMES = {
    "info":    {"bg": (0.10, 0.30, 0.55, 0.95), "text": (1, 1, 1, 1)},
    "success": {"bg": (0.05, 0.45, 0.20, 0.95), "text": (1, 1, 1, 1)},
    "warning": {"bg": (0.55, 0.35, 0.05, 0.95), "text": (1, 1, 1, 1)},
    "error":   {"bg": (0.55, 0.10, 0.10, 0.95), "text": (1, 1, 1, 1)},
}


def show_toast(message: str, level: str = "info", duration: float = 3.0):
    """
    Affiche un toast au centre de l'écran qui se ferme automatiquement.

    Args:
        message  : texte à afficher (peut contenir des sauts de ligne).
        level    : "info" | "success" | "warning" | "error".
        duration : secondes avant auto-dismiss (default 3.0).

    Thread-safe : peut être appelé depuis n'importe quel thread (le
    schedule_once garantit que le Popup est créé dans le main thread).
    """
    theme = _THEMES.get(level, _THEMES["info"])

    def _open(_dt):
        content = Label(
            text=message,
            color=theme["text"],
            font_size=dp(14),
            bold=True,
            halign="center",
            valign="middle",
            text_size=(dp(280), None),
        )
        # Calculer une hauteur raisonnable selon la longueur du texte
        nb_lines = max(1, message.count("\n") + 1 + len(message) // 40)
        height_px = min(dp(60 + nb_lines * 28), dp(240))

        popup = Popup(
            title="",
            separator_height=0,
            content=content,
            size_hint=(None, None),
            size=(dp(320), height_px),
            background_color=theme["bg"],
            background="",   # désactive le fond par défaut
            auto_dismiss=True,
        )
        popup.open()
        # Auto-dismiss après duration
        Clock.schedule_once(lambda dt: popup.dismiss(), duration)

    Clock.schedule_once(_open, 0)


def show_info(message: str, duration: float = 3.0):
    show_toast(message, "info", duration)


def show_success(message: str, duration: float = 3.0):
    show_toast(message, "success", duration)


def show_warning(message: str, duration: float = 4.0):
    show_toast(message, "warning", duration)


def show_error(message: str, duration: float = 5.0):
    show_toast(message, "error", duration)
