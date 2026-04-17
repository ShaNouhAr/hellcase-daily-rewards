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


def _load_webhook_url() -> Optional[str]:
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if url:
        return url.strip()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return (cfg.get("discord_webhook_url") or "").strip() or None
    except (FileNotFoundError, json.JSONDecodeError):
        return None


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

    # Détail par caisse
    lines = []
    for r in cases_results:
        name = r.get("name", "?")
        status = r.get("status")
        if status == "opened":
            item = r.get("item") or "?"
            price = r.get("price")
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
        if inventory.get("balance"):
            inv_lines.append(f"💵 Solde : **{inventory['balance']}**")
        if inventory.get("credits"):
            inv_lines.append(f"🪙 Crédits : **{inventory['credits']}**")
        if inventory.get("items_count") is not None:
            inv_lines.append(f"📦 Items : **{inventory['items_count']}**")
        if inventory.get("items_value"):
            inv_lines.append(f"💎 Valeur totale : **{inventory['items_value']}**")
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
