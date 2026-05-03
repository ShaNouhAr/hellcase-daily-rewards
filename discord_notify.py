"""Notifications Discord via webhook pour Hellcase Daily Rewards.

Envoie un embed riche récapitulatif après chaque run, et une alerte en cas de
session Steam expirée (cookies invalides).

Configuration : URL de webhook lue dans l'ordre :
  1. Variable d'environnement DISCORD_WEBHOOK_URL
  2. Fichier config.json → clé "discord_webhook_url"

Pas de dépendance externe : utilise uniquement urllib de la stdlib.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

CONFIG_FILE = "config.json"


def _load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _load_webhook_url() -> Optional[str]:
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if url:
        return url.strip()
    cfg = _load_config()
    return (cfg.get("discord_webhook_url") or "").strip() or None


def _currency_symbol(override=None) -> str:
    """Retourne le symbole à utiliser.

    Priorité : argument `override` (devise détectée depuis la page) > variable
    d'env `HELLCASE_CURRENCY` > `config.json` > "$".
    """
    if override:
        return str(override).strip()
    sym = os.environ.get("HELLCASE_CURRENCY")
    if sym:
        return sym.strip()
    cfg = _load_config()
    return (cfg.get("currency_symbol") or "$").strip() or "$"


def _to_float(value):
    """Convertit une valeur (str/float/int) en float, ou None si impossible."""
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _fmt_price(value, currency=None):
    """Formate une valeur numérique avec le symbole de devise."""
    if value is None or value == "":
        return None
    sym = _currency_symbol(currency)
    try:
        n = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return f"{value} {sym}"
    text = f"{n:.2f}" if abs(n) < 10000 and n != int(n) else f"{n:g}"
    return f"{text} {sym}"


def _post(webhook_url: str, payload: dict) -> bool:
    data = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "hellcase-bot/1.0"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except (HTTPError, URLError, TimeoutError) as e:
        print(f"⚠ Webhook Discord : échec d'envoi ({e})")
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def notify_run_summary(
    cases_results: list[dict],
    inventory: Optional[dict] = None,
    webhook_url: Optional[str] = None,
) -> bool:
    """Envoie un rapport de run à Discord.

    :param cases_results: liste de dicts
        {"name": str, "status": "opened"|"skipped"|"error",
         "item": Optional[str], "price": Optional[str], "reason": Optional[str]}
    :param inventory: dict optionnel
        {"balance": str, "credits": str, "items_count": int,
         "items_value": str, "recent_items": list[dict]}
    :param webhook_url: URL du webhook (sinon lue depuis la config)
    """
    url = webhook_url or _load_webhook_url()
    if not url:
        return False

    opened = sum(1 for r in cases_results if r.get("status") == "opened")
    total = len(cases_results)

    if total == 0:
        color = 0x9B59B6  # violet
        title = "🎮 Hellcase — Aucune caisse détectée"
    elif opened == total:
        color = 0x2ECC71  # vert
        title = f"🎮 Hellcase — {opened}/{total} caisses ouvertes ✓"
    elif opened > 0:
        color = 0xF1C40F  # jaune
        title = f"🎮 Hellcase — {opened}/{total} caisses ouvertes (partiel)"
    else:
        color = 0xE74C3C  # rouge
        title = f"🎮 Hellcase — Aucune caisse ouverte ({total} détectées)"

    fields = []

    # Détecter la devise (passée via inventory) pour formater les prix
    curr = (inventory or {}).get("currency")

    # Détail par caisse
    lines = []
    for r in cases_results:
        name = r.get("name", "?")
        status = r.get("status")
        if status == "opened":
            item = r.get("item") or "?"
            price = _fmt_price(r.get("price"), currency=curr)
            suffix = f" — **{item}**" + (f" ({price})" if price else "")
            lines.append(f"🎁 `{name}`{suffix}")
        elif status == "skipped":
            reason = r.get("reason") or "indisponible"
            lines.append(f"⏸ `{name}` — _{reason}_")
        else:
            err = r.get("reason") or "erreur"
            lines.append(f"✗ `{name}` — _{err}_")

    if lines:
        # Discord limite chaque field à 1024 chars
        chunk = ""
        idx = 1
        for line in lines:
            if len(chunk) + len(line) + 1 > 1000:
                fields.append({"name": f"Caisses ({idx})", "value": chunk, "inline": False})
                chunk = ""
                idx += 1
            chunk += line + "\n"
        if chunk:
            fields.append({"name": "Caisses" if idx == 1 else f"Caisses ({idx})", "value": chunk, "inline": False})

    # Inventaire
    if inventory:
        inv_lines = []
        raw_balance = _to_float(inventory.get("balance"))
        raw_items_value = _to_float(inventory.get("items_value"))

        balance = _fmt_price(raw_balance, currency=curr)
        if balance:
            inv_lines.append(f"💵 Solde : **{balance}**")
        if inventory.get("items_count") is not None:
            items_val = _fmt_price(raw_items_value or 0, currency=curr)
            inv_lines.append(
                f"📦 Items : **{inventory['items_count']}** ({items_val})"
            )
        # Valeur totale = solde + valeur des items
        total = (raw_balance or 0) + (raw_items_value or 0)
        if total > 0 or raw_balance is not None or raw_items_value is not None:
            inv_lines.append(
                f"💎 Valeur totale : **{_fmt_price(total, currency=curr)}**"
            )
        if inv_lines:
            fields.append({
                "name": "Inventaire",
                "value": "\n".join(inv_lines),
                "inline": False,
            })

    payload = {
        "username": "Hellcase Bot",
        "embeds": [{
            "title": title,
            "color": color,
            "fields": fields,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "footer": {"text": "hellcase-daily-rewards"},
        }],
    }
    return _post(url, payload)


def notify_session_expired(webhook_url: Optional[str] = None) -> bool:
    """Alerte Discord quand la session Steam est expirée et qu'un scan manuel
    est requis (cron ne peut pas afficher le QR)."""
    url = webhook_url or _load_webhook_url()
    if not url:
        return False

    payload = {
        "username": "Hellcase Bot",
        "embeds": [{
            "title": "🔒 Session Hellcase expirée",
            "description": (
                "Les cookies ne sont plus valides. Une nouvelle authentification "
                "Steam via QR Code est nécessaire.\n\n"
                "**Action requise :** connecte-toi en SSH au serveur et lance :\n"
                "```bash\ncd /home/shanouhar/hellcase-daily-rewards\n"
                "python3 hellcase_auto.py\n```\n"
                "Puis scanne le QR affiché avec l'app Steam Mobile."
            ),
            "color": 0xE74C3C,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "footer": {"text": "hellcase-daily-rewards"},
        }],
    }
    return _post(url, payload)


def notify_error(message: str, webhook_url: Optional[str] = None) -> bool:
    """Alerte Discord pour une erreur générique."""
    url = webhook_url or _load_webhook_url()
    if not url:
        return False
    payload = {
        "username": "Hellcase Bot",
        "embeds": [{
            "title": "⚠ Hellcase — Erreur",
            "description": f"```\n{message[:1800]}\n```",
            "color": 0xE67E22,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "footer": {"text": "hellcase-daily-rewards"},
        }],
    }
    return _post(url, payload)
