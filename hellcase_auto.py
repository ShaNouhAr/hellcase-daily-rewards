#!/usr/bin/env python3
"""
Script d'automatisation pour ouvrir les caisses gratuites quotidiennes sur Hellcase
Version Selenium - Simule un vrai navigateur
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import json
import time
from datetime import datetime


class HellcaseAutoOpener:
    def __init__(self, cookies_file='cookies.json', headless=True):
        """
        Initialise le script avec Selenium
        """
        print("🚀 Initialisation du navigateur...")
        
        # Configuration de Chrome
        chrome_options = Options()
        if headless:
            chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        # Initialiser le driver
        try:
            # Essayer avec le chemin par défaut de chromedriver
            service = Service('/usr/bin/chromedriver')
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
        except Exception as e:
            # Essayer sans spécifier le service
            try:
                self.driver = webdriver.Chrome(options=chrome_options)
            except Exception as e2:
                print(f"✗ Erreur lors de l'initialisation de Chrome : {e2}")
                print("\n💡 Assurez-vous que Chrome et ChromeDriver sont installés.")
                print("   Installation : sudo apt install chromium chromium-driver")
                exit(1)
        
        self.base_url = "https://hellcase.com"
        self.wait = WebDriverWait(self.driver, 10)
        
        # URLs des caisses gratuites
        self.free_cases = [
            {'name': 'NEWBIE', 'url': '/fr/open/newbie'},
            {'name': 'GAMER', 'url': '/fr/open/gamer'},
            {'name': 'SEMI-PRO', 'url': '/fr/open/semi-pro'}
        ]
        
        # Charger les cookies
        self.load_cookies(cookies_file)
    
    def load_cookies(self, cookies_file):
        """
        Charge les cookies depuis un fichier JSON
        """
        try:
            with open(cookies_file, 'r') as f:
                cookies_data = json.load(f)
            
            # Aller sur le site d'abord pour pouvoir ajouter les cookies
            self.driver.get(self.base_url)
            time.sleep(2)
            
            # Ajouter les cookies
            if isinstance(cookies_data, dict):
                for name, value in cookies_data.items():
                    self.driver.add_cookie({
                        'name': name,
                        'value': value,
                        'domain': '.hellcase.com'
                    })
            elif isinstance(cookies_data, list):
                for cookie in cookies_data:
                    self.driver.add_cookie(cookie)
            
            print("✓ Cookies chargés")
            
            # Rafraîchir la page pour appliquer les cookies
            self.driver.refresh()
            time.sleep(2)
            
        except FileNotFoundError:
            print(f"✗ Erreur : Le fichier {cookies_file} n'existe pas")
            self.driver.quit()
            exit(1)
        except Exception as e:
            print(f"✗ Erreur lors du chargement des cookies : {e}")
            self.driver.quit()
            exit(1)
    
    def open_case(self, case_info):
        """
        Tente d'ouvrir une caisse gratuite
        """
        case_name = case_info['name']
        case_url = self.base_url + case_info['url']
        
        print(f"\n🎁 Tentative d'ouverture de la caisse {case_name}...")
        
        try:
            # Aller sur la page de la caisse
            self.driver.get(case_url)
            time.sleep(3)
            
            # Chercher le bouton d'ouverture
            # Les sélecteurs possibles pour le bouton
            selectors = [
                "//button[contains(@class, 'open')]",
                "//button[contains(text(), 'Ouvrir')]",
                "//button[contains(text(), 'Open')]",
                "//div[contains(@class, 'open-button')]",
                "//a[contains(@class, 'open')]",
                "//button[contains(@class, 'btn-open')]",
                "//button[contains(@class, 'case-open')]"
            ]
            
            button_found = False
            for selector in selectors:
                try:
                    button = self.wait.until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    button_found = True
                    break
                except:
                    continue
            
            if not button_found:
                print(f"  ℹ Bouton d'ouverture non trouvé (peut-être déjà ouverte aujourd'hui)")
                return False
            
            # Cliquer sur le bouton
            button.click()
            print(f"  ✓ Bouton cliqué !")
            
            # Attendre le résultat
            time.sleep(5)
            
            # Essayer de trouver le résultat
            try:
                result_elements = self.driver.find_elements(By.CLASS_NAME, "item-name")
                if result_elements:
                    item_name = result_elements[0].text
                    print(f"  🎉 Item obtenu : {item_name}")
            except:
                pass
            
            return True
            
        except Exception as e:
            print(f"  ✗ Erreur : {str(e)}")
            return False
    
    def run(self):
        """
        Exécute le script pour ouvrir toutes les caisses gratuites
        """
        print("=" * 60)
        print("🎮 HELLCASE - Ouverture automatique des caisses gratuites")
        print("=" * 60)
        print(f"⏰ Date et heure : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        
        success_count = 0
        total_cases = len(self.free_cases)
        
        for case_info in self.free_cases:
            if self.open_case(case_info):
                success_count += 1
            time.sleep(2)
        
        print("\n" + "=" * 60)
        print(f"📊 Résultat : {success_count}/{total_cases} caisses ouvertes")
        print("=" * 60)
        
        # Fermer le navigateur
        self.driver.quit()


def main():
    """
    Point d'entrée principal du script
    """
    opener = HellcaseAutoOpener('cookies.json')
    opener.run()


if __name__ == '__main__':
    main()

