# 🎮 Hellcase Daily Rewards - Script d'automatisation

Script Python simple et fonctionnel pour automatiser l'ouverture des caisses gratuites quotidiennes sur Hellcase.

✅ **Script testé et fonctionnel !**

## 📋 Prérequis

- Python 3.6 ou supérieur
- Bibliothèque `selenium`
- Chrome/Chromium et ChromeDriver

## 🚀 Installation

1. Installez Chrome et ChromeDriver :
```bash
# Sur Ubuntu/Debian/WSL
sudo apt update
sudo apt install chromium chromium-driver
```

2. Installez la bibliothèque Selenium :
```bash
pip install --break-system-packages selenium
# Ou
pip install -r requirements.txt
```

3. Récupérez vos cookies Hellcase :

   - Connectez-vous sur https://hellcase.com
   - Appuyez sur `F12` pour ouvrir les outils de développement
   - Allez dans l'onglet "Application" (Chrome) ou "Stockage" (Firefox)
   - Cliquez sur "Cookies" → "https://hellcase.com"
   - Copiez les cookies suivants et leurs valeurs :
     - `hellcase_session` (obligatoire)
     - `XSRF-TOKEN` (obligatoire)
     - `cf_clearance` (obligatoire)
     - `_ga` (recommandé)

4. Créez le fichier `cookies.json` avec ce format :

   ```json
   {
       "hellcase_session": "votre_valeur_ici",
       "XSRF-TOKEN": "votre_valeur_ici",
       "cf_clearance": "votre_valeur_ici",
       "_ga": "votre_valeur_ici",
       "i18n_lang_code": "fr"
   }
   ```

   **⚠️ Important :** Copiez les valeurs EXACTES depuis votre navigateur !

## 🎯 Utilisation

Lancez simplement le script :

```bash
python3 hellcase_auto.py
```

Le script va automatiquement :
1. Charger vos cookies depuis `cookies.json`
2. Ouvrir les 3 caisses gratuites quotidiennes :
   - Newbie
   - Gamer
   - Semi-Pro
3. Afficher les résultats

## 📁 Structure du projet

```
hellcase-daily-rewards/
├── hellcase_auto.py        # Script principal (Selenium)
├── discord_notify.py       # Notifications Discord via webhook
├── cookies.json            # Vos cookies (auto-généré, ignoré par git)
├── config.json             # URL webhook Discord (ignoré par git)
├── config.example.json     # Template de configuration
├── requirements.txt        # Dépendances Python
├── .gitignore              # Protège vos cookies & config
└── README.md               # Ce fichier
```

## 🔔 Notifications Discord

À chaque run, un rapport détaillé peut être envoyé sur Discord via webhook :
- ✅ statut des caisses (ouvertes / ignorées / erreurs)
- 🎁 item obtenu + prix pour chaque caisse
- 💵 solde + valeur totale de l'inventaire Hellcase
- 🔒 alerte automatique si la session Steam est expirée (cookies invalides)

### Configuration

1. Sur Discord, clic droit sur le salon cible → **Modifier le salon** → **Intégrations** → **Webhooks** → **Nouveau webhook** → copier l'URL.

2. Créer `config.json` (à partir de `config.example.json`) :

   ```json
   {
       "discord_webhook_url": "https://discord.com/api/webhooks/XXXXXXXX/YYYYYYYY",
       "currency_symbol": "$"
   }
   ```

   - `discord_webhook_url` : URL du webhook Discord (alternative : variable d'env `DISCORD_WEBHOOK_URL`, prioritaire).
   - `currency_symbol` : **override manuel** du symbole. En temps normal la devise est auto-détectée depuis la page (mapping interne `1=$`, `2=€`, `3=£`, `9=R$`, `50=zł`, `80=lei`). Ne remplir ce champ que si l'auto-détection échoue ou si tu veux forcer un autre symbole. Défaut : `"$"`.

3. Si la variable n'est pas définie et que `config.json` n'existe pas, les notifications sont simplement ignorées (aucune erreur).

### Exécution automatique quotidienne (cron)

```bash
crontab -e
```

Ajouter :

```
0 10 * * * cd /home/USER/hellcase-daily-rewards && /usr/bin/python3 hellcase_auto.py >> /var/log/hellcase.log 2>&1
```

→ tous les jours à 10h, le script ouvre les caisses et envoie le rapport Discord.

**Si les cookies expirent** (session Hellcase invalidée), le script détecte qu'il n'a pas de terminal interactif (cron) et envoie automatiquement une alerte Discord « Session expirée » avec les instructions pour rescanner le QR. Il suffit alors de se connecter en SSH et de lancer manuellement :

```bash
python3 hellcase_auto.py
```

Le QR s'affiche en ASCII dans le terminal, tu le scannes avec l'app Steam Mobile, les cookies sont sauvegardés automatiquement.

## ⚙️ Configuration

### Mode d'affichage
Par défaut, le script s'exécute en mode "headless" (sans fenêtre visible). Pour voir le navigateur en action :

```python
# Dans hellcase_auto.py, ligne 187 :
opener = HellcaseAutoOpener('cookies.json', headless=False)
```

### Personnalisation
Vous pouvez modifier les variables dans `hellcase_auto.py` :

- **Caisses à ouvrir** : Modifiez la liste `self.free_cases` (lignes 39-43)
- **Délais** : Ajustez les `time.sleep()` pour changer les temps d'attente

## 🔒 Sécurité

**IMPORTANT :** 
- Ne partagez JAMAIS votre fichier `cookies.json`
- Ne committez JAMAIS vos cookies sur Git
- Les cookies contiennent vos informations de session et permettent d'accéder à votre compte
- Changez vos mots de passe si vous pensez que vos cookies ont été compromis

## ⚠️ Avertissement

- L'automatisation peut être contraire aux conditions d'utilisation de Hellcase
- Utilisez ce script à vos propres risques
- Le script est fourni à titre éducatif uniquement
- Hellcase pourrait bloquer votre compte si vous abusez de l'automatisation

## 🐛 Dépannage

**Erreur "Unable to obtain driver for chrome"**
```bash
sudo apt install chromium chromium-driver
```

**Le script ne trouve pas le fichier cookies.json**
- Assurez-vous que le fichier existe dans le même répertoire que le script
- Vérifiez que le fichier est bien nommé `cookies.json` (et non `cookies.json.txt`)

**Erreur "JSON invalide"**
- Vérifiez la syntaxe de votre fichier JSON (virgules, guillemets)
- Utilisez un validateur JSON en ligne pour vérifier
- Les noms de cookies doivent correspondre exactement

**Le bouton d'ouverture n'est pas trouvé**
- Vos cookies sont peut-être expirés → Reconnectez-vous et récupérez de nouveaux cookies
- Vous avez peut-être déjà ouvert les caisses aujourd'hui
- Hellcase a peut-être modifié l'interface du site

**Le script se bloque ou est trop lent**
- Ajustez les délais `time.sleep()` dans le code
- Vérifiez votre connexion internet
- Essayez en mode non-headless pour voir ce qui se passe

## 📝 Notes

- Le script utilise Selenium pour simuler un vrai navigateur
- Les cookies expirent après un certain temps, vous devrez les renouveler régulièrement
- Si Hellcase modifie l'interface du site, le script devra être adapté
- Les délais entre les caisses simulent un comportement humain

## 🚀 Améliorations futures possibles

- Planifier l'exécution automatique quotidienne avec `cron`
- Ajouter des notifications (email, Discord, etc.)
- Gérer plusieurs comptes
- Logger les résultats dans un fichier

## 🤝 Contribution

N'hésitez pas à améliorer ce script et à partager vos modifications !

## 📄 Licence

Ce script est fourni tel quel, sans garantie d'aucune sorte.

