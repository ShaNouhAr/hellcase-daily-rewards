#!/usr/bin/env python3
"""
Hellcase - Ouverture automatique des caisses gratuites quotidiennes.
- Authentification Steam via QR Code (dans le terminal)
- Refresh automatique des cookies dès que la session expire
- Détection dynamique des caisses gratuites disponibles sur le compte
"""

import json
import os
import sys
import time
from datetime import datetime
from io import BytesIO
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import NoSuchElementException

import discord_notify


BASE_URL = "https://hellcase.com"
COOKIES_FILE = "cookies.json"

# Mapping des caractères "masqués" de la font Hellcase "Currencies" vers leur
# vrai symbole. Hellcase obfusque l'icône devise (un caractère ASCII différent
# pour chaque devise) pour empêcher le scraping ; ce mapping a été fourni par
# l'utilisateur après test visuel.
CURRENCY_MAP = {
    "1": "$",    # USD
    "2": "€",    # EUR
    "3": "£",    # GBP
    "9": "R$",   # BRL
    "50": "zł",  # PLN
    "80": "lei", # RON
}

# Fallback si la détection automatique échoue
FALLBACK_CASES = [
    {'name': 'NEWBIE', 'url': '/fr/open/newbie'},
    {'name': 'GAMER', 'url': '/fr/open/gamer'},
    {'name': 'SEMI-PRO', 'url': '/fr/open/semi-pro'},
    {'name': 'PRO', 'url': '/fr/open/pro'},
]


# =========================================================================
# Steam QR Authentication
# =========================================================================

def _click_first(driver, selectors, timeout=5):
    """Essaie plusieurs sélecteurs (By, valeur) et clique le premier trouvé."""
    wait = WebDriverWait(driver, timeout)
    for by, sel in selectors:
        try:
            el = wait.until(EC.element_to_be_clickable((by, sel)))
            el.click()
            return True
        except Exception:
            continue
    return False


def _steam_navigate(driver):
    """Navigue depuis hellcase jusqu'à la page de login Steam OpenID.

    Flux sur Hellcase 2026 :
    1) Home → click "CONNEXION" (ouvre un modal)
    2) Modal → click "CONNECTEZ-VOUS AVEC STEAM" → redirection Steam
    """
    for url in (f"{BASE_URL}/fr", BASE_URL, f"{BASE_URL}/en"):
        driver.get(url)
        time.sleep(4)

        # Étape 1 : ouvrir le modal de connexion (textes case-insensitive)
        opened = _click_first(driver, [
            (By.XPATH, "//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'connexion')]"),
            (By.XPATH, "//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'sign in')]"),
            (By.XPATH, "//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'log in')]"),
            (By.XPATH, "//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'login')]"),
        ], timeout=15)
        if not opened:
            continue
        time.sleep(2)

        # Étape 2 : cliquer sur le bouton Steam dans le modal
        _click_first(driver, [
            (By.XPATH, "//a[contains(@href,'/auth/steam') or contains(@href,'steampowered') or contains(@href,'steamcommunity')]"),
            (By.XPATH, "//button[contains(translate(.,'STEAM','steam'),'steam')]"),
            (By.XPATH, "//*[self::a or self::button][.//*[contains(translate(.,'STEAM','steam'),'steam')]]"),
            (By.XPATH, "//img[contains(@src,'steam')]/ancestor::*[self::a or self::button][1]"),
        ], timeout=6)

        # Attendre la redirection vers Steam (jusqu'à 15s)
        for _ in range(15):
            time.sleep(1)
            if 'steampowered.com' in driver.current_url or 'steamcommunity.com' in driver.current_url:
                return True

    return False


def _steam_enable_qr(driver):
    """Active le mode QR Code sur la page Steam (ancienne UI seulement).

    Sur la nouvelle page Sign In (2024+), le QR est déjà visible par défaut,
    donc on tente les sélecteurs rapidement et on ignore les échecs.
    """
    return _click_first(driver, [
        (By.CLASS_NAME, "login_qrcode_link"),
        (By.ID, "login_qrcode_link"),
        (By.XPATH, "//a[contains(@class,'qrcode')]"),
    ], timeout=1)


def _steam_find_qr_img(driver):
    """Trouve l'élément <img> du QR Code Steam (nouvelle page de login 2024+)."""
    wait = WebDriverWait(driver, 15)
    for by, sel in [
        # Nouveau Steam Sign In : le QR est un <img src="blob:...">
        (By.CSS_SELECTOR, "img[src^='blob:']"),
        # Anciennes versions
        (By.XPATH, "//div[contains(@class,'qr_code')]//img"),
        (By.XPATH, "//div[contains(@class,'responsive_login_qrcode')]//img"),
        (By.XPATH, "//div[contains(@class,'qrcode')]//img"),
        (By.CSS_SELECTOR, ".qr_code img"),
        (By.CSS_SELECTOR, ".responsive_login_qrcode img"),
        (By.XPATH, "//img[contains(@class,'qrcode') or contains(@class,'qr_code')]"),
    ]:
        try:
            return wait.until(EC.presence_of_element_located((by, sel)))
        except Exception:
            continue
    return None


def _decode_qr(img_element):
    """Screenshot de l'élément et décodage du QR Code."""
    try:
        from PIL import Image
        from pyzbar.pyzbar import decode
    except ImportError as e:
        pkg = "Pillow" if "PIL" in str(e) else "pyzbar"
        print(f"\n  ✗ Dépendance manquante : {pkg}")
        print("  Installez les dépendances requises :")
        print("    sudo apt install libzbar0")
        print("    pip install --break-system-packages Pillow pyzbar qrcode")
        sys.exit(1)
    img = Image.open(BytesIO(img_element.screenshot_as_png))
    results = decode(img)
    return results[0].data.decode() if results else None


def _print_qr(data):
    """Affiche un QR Code en ASCII dans le terminal."""
    try:
        import qrcode
    except ImportError:
        print("  ✗ qrcode manquant. Installez-le : pip install --break-system-packages qrcode")
        sys.exit(1)
    qr = qrcode.QRCode(border=2)
    qr.add_data(data)
    qr.make(fit=True)
    print()
    qr.print_ascii(invert=True)
    print()


def steam_qr_auth(driver, cookies_file):
    """Lance le flux d'authentification Steam via QR Code.

    Affiche le QR Code dans le terminal, attend le scan, sauvegarde les cookies.
    Retourne True en cas de succès.
    """
    print("\n" + "=" * 60)
    print("  AUTHENTIFICATION STEAM via QR Code")
    print("=" * 60)

    print("\n  → Navigation vers Steam...")
    if not _steam_navigate(driver):
        print(f"  ✗ Redirection Steam non détectée ({driver.current_url})")
        return False
    print("  ✓ Page Steam atteinte")

    print("  → Recherche du QR Code...")
    # Sur la nouvelle page Steam Sign In (2024+), le QR est affiché par défaut.
    # On tente l'ancien bouton d'activation pour compatibilité, avec un timeout court.
    _steam_enable_qr(driver)
    time.sleep(1)

    last_data = None

    def show_qr():
        nonlocal last_data
        el = _steam_find_qr_img(driver)
        if el is None:
            return False
        data = _decode_qr(el)
        if data and data != last_data:
            last_data = data
            print("\n  📱 Scannez ce QR Code avec l'application Steam Mobile :")
            _print_qr(data)
        return bool(data)

    if not show_qr():
        print("  ✗ QR Code introuvable sur la page Steam")
        return False

    print("  ⏳ En attente de la connexion (scan du QR sur Steam Mobile)...")
    deadline = time.time() + 180
    last_refresh = time.time()
    last_url = driver.current_url

    while time.time() < deadline:
        time.sleep(1)
        url = driver.current_url

        if url != last_url:
            print(f"     ↪ {url[:100]}")
            last_url = url

        # Étape intermédiaire : page de confirmation OpenID (après scan du QR)
        # → /openid/login affiche un bouton "Sign In" à cliquer pour autoriser.
        if 'steamcommunity.com' in url and '/openid/login' in url and '/loginform' not in url:
            clicked = _click_first(driver, [
                (By.ID, "imageLogin"),
                (By.XPATH, "//input[@type='submit' and contains(@value,'Sign In')]"),
                (By.XPATH, "//input[@type='submit']"),
                (By.XPATH, "//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'sign in')]"),
                (By.XPATH, "//a[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'sign in')]"),
            ], timeout=2)
            if clicked:
                print("     ✓ Confirmation OpenID validée")
                time.sleep(2)
                continue

        # Étape 1 : on est toujours sur la page de login Steam
        on_steam_loginform = (
            'steamcommunity.com' in url and '/openid/loginform' in url
        ) or 'steampowered.com/login' in url

        # Étape 2 : on a quitté la page login Steam → la redirection OpenID
        # passe par steam.loginhell.com puis revient sur hellcase.com.
        # Dans tous les cas, on considère qu'on est authentifié quand on
        # atterrit sur hellcase.com (peu importe le path).
        on_hellcase = 'hellcase.com' in urlparse(url).netloc

        if on_hellcase:
            # Laisser la page finir son chargement (cookies de session posés)
            time.sleep(4)
            try:
                driver.get(f"{BASE_URL}/fr")
                time.sleep(3)
            except Exception:
                pass
            cookies = driver.get_cookies()
            with open(cookies_file, 'w') as f:
                json.dump(cookies, f, indent=2)
            print(f"\n  ✓ Connexion réussie ! {len(cookies)} cookies sauvegardés dans '{cookies_file}'\n")
            return True

        # Rafraîchir le QR s'il a expiré (~25s) seulement si on est encore sur le loginform
        if time.time() - last_refresh > 25 and on_steam_loginform:
            show_qr()
            last_refresh = time.time()

    print("  ✗ Timeout (3 min) — Connexion non détectée")
    return False


# =========================================================================
# Hellcase Opener
# =========================================================================

class HellcaseAutoOpener:
    def __init__(self, cookies_file=COOKIES_FILE, headless=True):
        self.cookies_file = cookies_file
        print("🚀 Initialisation du navigateur...")
        self._setup_driver(headless)
        self._ensure_session()

    def _setup_driver(self, headless):
        chrome_options = Options()
        if headless:
            chrome_options.add_argument('--headless=new')
            chrome_options.add_argument('--window-size=1280,900')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument(
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

        for binary in ('/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome'):
            if os.path.exists(binary):
                chrome_options.binary_location = binary
                break

        driver_path = None
        for candidate in ('/usr/bin/chromedriver', '/usr/lib/chromium/chromedriver'):
            if os.path.exists(candidate):
                driver_path = candidate
                break

        try:
            if driver_path:
                self.driver = webdriver.Chrome(
                    service=Service(driver_path), options=chrome_options
                )
            else:
                self.driver = webdriver.Chrome(options=chrome_options)
        except Exception as e:
            print(f"✗ Chrome introuvable : {e}")
            print("   Installation : sudo apt install chromium chromium-driver")
            exit(1)

        self.wait = WebDriverWait(self.driver, 10)

    def _ensure_session(self):
        """Charge les cookies s'ils sont valides, sinon Steam QR auth."""
        if os.path.exists(self.cookies_file):
            print("  → Chargement des cookies existants...")
            self._load_cookies()
            if self._is_logged_in():
                print("  ✓ Session valide")
                return
            print("  ⚠ Session expirée — nouvelle authentification Steam requise")

        # Si le script est lancé sans TTY (cron, systemd, etc.), on ne peut pas
        # afficher de QR interactivement. On notifie Discord et on sort proprement.
        if not sys.stdin.isatty():
            print("  ✗ Pas de terminal interactif → impossible d'afficher le QR.")
            try:
                discord_notify.notify_session_expired()
                print("  📨 Alerte Discord envoyée (session expirée)")
            except Exception as e:
                print(f"  ⚠ Envoi Discord échoué : {e}")
            self.driver.quit()
            exit(2)

        if not steam_qr_auth(self.driver, self.cookies_file):
            try:
                discord_notify.notify_session_expired()
            except Exception:
                pass
            self.driver.quit()
            exit(1)

    def _load_cookies(self):
        with open(self.cookies_file, 'r') as f:
            cookies_data = json.load(f)
        self.driver.get(BASE_URL)
        time.sleep(2)

        if isinstance(cookies_data, dict):
            for name, value in cookies_data.items():
                try:
                    self.driver.add_cookie({
                        'name': name, 'value': value, 'domain': '.hellcase.com'
                    })
                except Exception:
                    pass
        elif isinstance(cookies_data, list):
            allowed = {'name', 'value', 'domain', 'path', 'secure', 'httpOnly', 'expiry', 'sameSite'}
            for cookie in cookies_data:
                try:
                    self.driver.add_cookie({k: v for k, v in cookie.items() if k in allowed})
                except Exception:
                    pass

        self.driver.refresh()
        time.sleep(2)

    def _is_logged_in(self):
        """Vérifie que la session actuelle est authentifiée sur hellcase."""
        self.driver.get(f"{BASE_URL}/fr")
        time.sleep(3)

        # Si un bouton de login visible → pas connecté
        login_prompts = [
            "//a[contains(@href,'/auth/steam')]",
            "//*[contains(text(),'Sign in through Steam')]",
            "//*[contains(text(),'Se connecter via Steam')]",
        ]
        for sel in login_prompts:
            try:
                if self.driver.find_element(By.XPATH, sel).is_displayed():
                    return False
            except NoSuchElementException:
                continue

        # Indicateurs de session active
        logged_in = [
            "//*[contains(@class,'user-balance')]",
            "//*[contains(@class,'user-avatar')]",
            "//*[contains(@class,'header-user')]",
            "//*[contains(@class,'avatar')]",
            "//*[contains(@class,'userpanel')]",
        ]
        for sel in logged_in:
            try:
                if self.driver.find_element(By.XPATH, sel).is_displayed():
                    return True
            except NoSuchElementException:
                continue

        # Heuristique finale : page chargée sans prompt de login
        return '/login' not in self.driver.current_url

    # ---- Détection dynamique des caisses gratuites ----

    def _detect_free_cases(self):
        """Scrape la page des caisses gratuites quotidiennes.

        URL principale : /fr/dailyfree (liste les vraies free cases quotidiennes :
        newbie, gamer, semi-pro, pro, etc., selon le niveau du compte).
        """
        for path in ('/fr/dailyfree', '/fr/free-cases', '/fr/free'):
            try:
                self.driver.get(BASE_URL + path)
                time.sleep(4)
                cases = self._scrape_case_links()
                if cases:
                    return cases
            except Exception:
                continue
        return FALLBACK_CASES

    def _scrape_case_links(self):
        """Extrait les liens /open/ de la page courante."""
        cases = []
        seen = set()
        try:
            links = self.driver.find_elements(By.XPATH, "//a[contains(@href,'/open/')]")
        except Exception:
            return []

        for link in links:
            try:
                href = link.get_attribute('href') or ''
            except Exception:
                continue
            path = urlparse(href).path
            if not path or '/open/' not in path or path in seen:
                continue
            seen.add(path)
            slug = path.rstrip('/').split('/open/')[-1]
            if not slug or '/' in slug:
                continue
            name = slug.replace('-', ' ').upper()
            cases.append({'name': name, 'url': path})

        return cases

    # ---- Ouverture d'une caisse ----

    def _cooldown_text(self):
        """Si la caisse est en cooldown, retourne le texte du timer (ex: '12H : 08MIN').

        Hellcase affiche un div `_timer_*` dans la zone `_open-button_*` quand
        la caisse a déjà été ouverte aujourd'hui et qu'il faut attendre.
        """
        for sel in (
            "[class*='_open-button_'] [class*='_timer_']",
            "[class*='_open_'] [class*='_timer_']",
            "[class*='_timer_']",
        ):
            try:
                el = self.driver.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    txt = (el.text or "").strip()
                    if txt:
                        # Format "0JOUR : 12H : 08MIN" → on le nettoie
                        return " ".join(txt.split())
            except NoSuchElementException:
                continue
        return None

    def _find_open_button(self):
        """Retourne le bouton d'ouverture **réel** de la caisse, ou None.

        Hellcase place le bouton d'ouverture dans un conteneur `_open-button_`.
        Quand la caisse est en cooldown, ce conteneur affiche un timer à la
        place du bouton — on doit donc vérifier qu'on a bien un bouton et pas
        un timer.
        """
        # Chercher un bouton d'action dans la zone d'ouverture (pas RECHARGER
        # ni TOUT ACCEPTER qui sont ailleurs sur la page).
        for sel in (
            "[class*='_open-button_'] button:not([disabled])",
            "[class*='_open-button_'] a",
            "[class*='_open_'] button:not([disabled])",
        ):
            try:
                el = self.driver.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed() and el.is_enabled():
                    txt = (el.text or "").strip().upper()
                    # Un vrai bouton d'ouverture contient "OUVRIR" / "OPEN"
                    # (évite par exemple "RECHARGER" qui apparaît si pas de bouton)
                    if any(kw in txt for kw in ("OUVRIR", "OPEN", "GRATUIT", "FREE")):
                        return el
            except NoSuchElementException:
                continue
        return None

    def _unavailable_reason(self):
        """Tente d'identifier pourquoi une caisse n'est pas ouvrable."""
        cd = self._cooldown_text()
        if cd:
            return f"cooldown ({cd})"

        # Abonnement / niveau requis
        for sel in (
            "//*[contains(text(),'abonnement')]",
            "//*[contains(text(),'subscription')]",
            "//*[contains(text(),'Premium')]",
            "//*[contains(text(),'niveau')]",
            "//*[contains(text(),'level')]",
            "//*[contains(text(),'NIVEAU')]",
        ):
            try:
                el = self.driver.find_element(By.XPATH, sel)
                if el.is_displayed():
                    return f"non éligible ({el.text.strip()[:60]})"
            except NoSuchElementException:
                continue

        return "indisponible (raison inconnue)"

    def _open_case(self, case):
        """Ouvre une caisse et retourne un dict de résultat.

        Format retourné :
          {"name": str, "status": "opened"|"skipped"|"error",
           "item": str|None, "price": str|None, "reason": str|None}
        """
        name = case['name']
        print(f"\n🎁 {name}")
        self.driver.get(BASE_URL + case['url'])
        time.sleep(4)

        # Vérifier d'abord le cooldown (caisse déjà ouverte aujourd'hui)
        cd = self._cooldown_text()
        if cd:
            reason = f"déjà ouverte — prochain run dans {cd}"
            print(f"  ⏸  {reason}")
            return {"name": name, "status": "skipped", "item": None,
                    "price": None, "reason": reason}

        button = self._find_open_button()
        if not button:
            reason = self._unavailable_reason()
            print(f"  ⏸  {reason}")
            return {"name": name, "status": "skipped", "item": None,
                    "price": None, "reason": reason}

        # Mémoriser les noms d'items déjà présents AVANT le clic (preview de la
        # caisse) pour pouvoir ensuite identifier le nouveau drop.
        pre_click_names = self._collect_item_names()

        try:
            button.click()
            print("  ✓ Caisse ouverte")
        except Exception as e:
            print(f"  ✗ Erreur au clic : {e}")
            return {"name": name, "status": "error", "item": None,
                    "price": None, "reason": str(e)[:120]}

        # Attendre la fin de l'animation de roulette (~8s)
        time.sleep(9)

        item_name, item_price = self._extract_obtained_item(pre_click_names)
        if item_name:
            suffix = f" ({item_price})" if item_price else ""
            print(f"  🎉 Item obtenu : {item_name}{suffix}")
        return {"name": name, "status": "opened", "item": item_name,
                "price": item_price, "reason": None}

    def _collect_item_names(self):
        """Retourne l'ensemble des noms d'items visibles sur la page."""
        names = set()
        try:
            for el in self.driver.find_elements(By.CSS_SELECTOR, "[class*='_name_']"):
                try:
                    t = (el.text or "").strip()
                    if t and 0 < len(t) < 80 and not t.isdigit():
                        names.add(t)
                except Exception:
                    continue
        except Exception:
            pass
        return names

    def _extract_obtained_item(self, pre_click_names=None):
        """Extrait le drop réel obtenu après ouverture.

        Stratégie :
        1. Cherche un conteneur de résultat (`_drop_`, `_result_`, `_prize_`, …)
           qui apparaît après l'animation et contient l'item gagné.
        2. Sinon, prend un `_name_` qui n'était PAS dans la preview de la caisse
           (diff avec `pre_click_names`).
        """
        pre_click_names = pre_click_names or set()
        name, price = None, None

        # 1) Conteneurs de résultat typiques d'Hellcase
        for container_sel in (
            "[class*='_drop-result_']",
            "[class*='_result_']",
            "[class*='_prize_']",
            "[class*='_drop_']",
            "[class*='_won_']",
            "[class*='_winning_']",
        ):
            try:
                containers = self.driver.find_elements(By.CSS_SELECTOR, container_sel)
            except Exception:
                continue
            for c in containers:
                try:
                    if not c.is_displayed():
                        continue
                    name_el = c.find_elements(By.CSS_SELECTOR, "[class*='_name_']")
                    price_el = c.find_elements(By.CSS_SELECTOR, "[class*='_price_']")
                    if name_el:
                        t = (name_el[0].text or "").strip()
                        if t and len(t) < 80:
                            name = t
                    if price_el:
                        name, price = self._extract_item_from_container(c)
                    if name:
                        break
                except Exception:
                    continue
            if name:
                break

        # 2) Fallback : un nouveau nom d'item apparu après le clic
        if not name:
            current = self._collect_item_names()
            new_names = current - pre_click_names
            if new_names:
                name = next(iter(new_names))

        # Prix : chercher un prix associé au nom trouvé (dans son parent direct)
        if name and not price:
            try:
                xp = f"//*[contains(@class,'_name_') and normalize-space(text())={name!r}]/ancestor::*[.//*[contains(@class,'_price_')]][1]"
                parent = self.driver.find_element(By.XPATH, xp)
                price = self._first_clean_price(parent)
            except Exception:
                pass

        return name, price

    @staticmethod
    def _first_clean_price(root_element):
        """Premier prix 'propre' (entier ou décimal court) trouvé dans root."""
        import re as _re
        try:
            for el in root_element.find_elements(By.CSS_SELECTOR, "[class*='_price_']"):
                try:
                    t = (el.text or "").strip().replace(",", ".").replace("\n", "")
                    m = _re.fullmatch(r"(\d{1,7}(?:\.\d{1,2})?)", t)
                    if m:
                        return m.group(1)
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _extract_item_from_container(self, container):
        """Extrait (name, price) d'un conteneur de drop."""
        name, price = None, None
        try:
            n = container.find_elements(By.CSS_SELECTOR, "[class*='_name_']")
            if n:
                t = (n[0].text or "").strip()
                if t and len(t) < 80:
                    name = t
        except Exception:
            pass
        price = self._first_clean_price(container)
        return name, price

    def run(self):
        print("=" * 60)
        print("🎮 HELLCASE - Ouverture automatique des caisses gratuites")
        print("=" * 60)
        print(f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

        print("\n🔍 Détection des caisses gratuites du compte...")
        cases = self._detect_free_cases()
        print(f"  → {len(cases)} caisse(s) détectée(s) : "
              f"{', '.join(c['name'] for c in cases)}")

        results = []
        for case in cases:
            results.append(self._open_case(case))
            time.sleep(2)

        opened = sum(1 for r in results if r["status"] == "opened")

        print("\n" + "=" * 60)
        print(f"📊 Résultat : {opened}/{len(cases)} caisse(s) ouverte(s)")
        print("=" * 60)

        print("\n📦 Récupération de l'inventaire Hellcase...")
        inventory = self._fetch_inventory_summary()
        if inventory:
            curr = inventory.get("currency")
            if curr:
                print(f"  🏳  Devise détectée : {curr}")
            balance = discord_notify._fmt_price(inventory.get("balance"), currency=curr)
            if balance:
                print(f"  💵 Solde  : {balance}")
            if inventory.get("items_count") is not None:
                print(f"  📦 Items  : {inventory['items_count']}")
            value = discord_notify._fmt_price(inventory.get("items_value"), currency=curr)
            if value:
                print(f"  💎 Valeur : {value}")

        self._persist_cookies()

        # Notification Discord (ignorée silencieusement si webhook non configuré)
        try:
            sent = discord_notify.notify_run_summary(results, inventory)
            if sent:
                print("\n📨 Rapport envoyé sur Discord")
        except Exception as e:
            print(f"\n⚠ Envoi Discord échoué : {e}")

        self.driver.quit()

    def _fetch_inventory_summary(self):
        """Scrape le profil pour récupérer solde / crédits / items.

        Retourne None si la page est inaccessible. Sinon un dict :
          {"balance": str, "credits": str, "items_count": int,
           "items_value": str, "recent_items": list[dict]}
        """
        try:
            self.driver.get(f"{BASE_URL}/fr/profile")
            time.sleep(5)
        except Exception:
            return None

        info = {"balance": None, "items_count": None,
                "items_value": None, "recent_items": [], "currency": None}

        # Solde — div avec class "_balances_" contient l'icône devise + prix
        # Format DOM : <div class="_balances_*"><span class="currency-icon">X</span>2.77</div>
        # Le contenu du span `core-currency-icon` désigne la devise (mapping
        # propre à la font Hellcase "Currencies" — voir _detect_currency).
        try:
            bal = self.driver.find_element(By.CSS_SELECTOR, "[class*='_balances_']")
            try:
                icon = bal.find_element(By.CSS_SELECTOR, ".core-currency-icon")
                code = (icon.text or "").strip()
                info["currency"] = CURRENCY_MAP.get(code)
            except NoSuchElementException:
                pass

            txt = (bal.text or "").strip().replace("\n", " ")
            import re as _re
            nums = _re.findall(r"\d+(?:[.,]\d{1,2})?", txt)
            if nums:
                # Le plus gros nombre décimal est le solde ; sinon le dernier nombre
                with_dec = [n for n in nums if "." in n or "," in n]
                info["balance"] = (with_dec[-1] if with_dec else nums[-1]).replace(",", ".")
        except NoSuchElementException:
            pass

        # Items d'inventaire : on associe chaque nom à un prix voisin en
        # remontant au parent commun (composant item Vue). La classe Vue
        # encode un hash stable par composant (ex: `_name_wz93x_29` et
        # `_price_wz93x_30` partagent le même suffixe `wz93x`).
        import re as _re

        def _clean_price(txt):
            # Ne garder que les prix entiers ou décimaux "propres" (pas les
            # rouleaux d'animation qui empilent 0-9 verticalement).
            t = (txt or "").strip().replace(",", ".").replace("\n", "")
            m = _re.fullmatch(r"(\d{1,7}(?:\.\d{1,2})?)", t)
            return float(m.group(1)) if m else None

        items = []
        try:
            name_els = self.driver.find_elements(By.CSS_SELECTOR, "[class*='_name_']")
        except Exception:
            name_els = []

        for name_el in name_els:
            try:
                name_text = (name_el.text or "").strip()
            except Exception:
                continue
            if not name_text or name_text.isdigit() or len(name_text) > 80:
                continue

            # Extraire le hash Vue du composant : `_name_wz93x_29` → `wz93x`
            cls = name_el.get_attribute("class") or ""
            m = _re.search(r"_name_([a-z0-9]+)_", cls)
            vue_hash = m.group(1) if m else None

            price_val = None
            try:
                # Remonter jusqu'au parent commun qui contient le prix associé
                parent = name_el
                for _ in range(5):
                    parent = parent.find_element(By.XPATH, "..")
                    price_selector = (
                        f"[class*='_price_{vue_hash}']" if vue_hash
                        else "[class*='_price_']"
                    )
                    prices_in_parent = parent.find_elements(By.CSS_SELECTOR, price_selector)
                    for p_el in prices_in_parent:
                        val = _clean_price(p_el.text)
                        if val is not None:
                            price_val = val
                            break
                    if price_val is not None:
                        break
            except Exception:
                pass

            items.append({"name": name_text, "price": price_val})

        # Dédoublonner par (name, price)
        seen = set()
        uniq_items = []
        for it in items:
            key = (it["name"], it["price"])
            if key in seen:
                continue
            seen.add(key)
            uniq_items.append(it)

        if uniq_items:
            info["items_count"] = len(uniq_items)
            info["recent_items"] = uniq_items[:10]
            total = sum(i["price"] for i in uniq_items if i["price"] is not None)
            if total > 0:
                # Valeur brute — sera formatée avec le symbole de devise config
                info["items_value"] = total

        return info

    def _persist_cookies(self):
        """Sauvegarde les cookies courants pour garder la session fraîche
        entre les runs (évite de re-scanner un QR tant que Hellcase ne
        révoque pas la session côté serveur)."""
        try:
            cookies = self.driver.get_cookies()
            if cookies:
                with open(self.cookies_file, 'w') as f:
                    json.dump(cookies, f, indent=2)
                print(f"💾 {len(cookies)} cookies rafraîchis dans '{self.cookies_file}'")
        except Exception as e:
            print(f"⚠ Impossible de sauvegarder les cookies : {e}")


def main():
    HellcaseAutoOpener(COOKIES_FILE).run()


if __name__ == '__main__':
    main()
