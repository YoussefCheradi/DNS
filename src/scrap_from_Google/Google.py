import re
import time
import random
import pandas as pd
import os
from dotenv import load_dotenv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver

load_dotenv()


# ======================
# UTILITAIRES
# ======================

def domain_to_query(domain):
    name = re.sub(r'\.[a-z]{2,}$', '', domain, flags=re.IGNORECASE)
    words = re.sub(r'([A-Z])', r' \1', name).strip()
    return words


def set_google_region_us(driver, wait):
    try:
        print("  -> Configuration region Google : United States...")

        driver.get("https://www.google.com/preferences?hl=en&lang=1&prev=https://www.google.com/preferences?hl%3Den")
        time.sleep(random.uniform(3, 7))

        # Clic sur "Results region" / "Région pour les résultats"
        results_region = wait.until(EC.element_to_be_clickable(
            (By.XPATH,
                "//*[contains(text(),'Results region')] | "
                "//*[contains(text(),'gion pour les r')]"
            )
        ))
        driver.execute_script("arguments[0].click();", results_region)
        time.sleep(2)

        # Remplir via JavaScript directement
        search_input = wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "input.baeIxf")
        ))
        driver.execute_script("arguments[0].value = 'United States';", search_input)
        # Déclencher l'événement input pour que Google filtre la liste
        driver.execute_script("""
            var input = arguments[0];
            var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeInputValueSetter.call(input, 'United States');
            input.dispatchEvent(new Event('input', { bubbles: true }));
        """, search_input)
        time.sleep(2)

        # Sélectionner via data-value="US"
        us_option = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//span[@data-value='US']")
        ))
        driver.execute_script("arguments[0].click();", us_option)
        time.sleep(1)

        # Confirmer
        confirm_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH,
                "//span[@jsaction='Bx2hUb'] | "
                "//span[contains(text(),'Confirm')] | "
                "//span[contains(text(),'Confirmer')]"
            )
        ))
        driver.execute_script("arguments[0].click();", confirm_btn)
        time.sleep(2)

        print("  -> Region configuree : United States OK")

    except Exception as e:
        print(f"  Erreur configuration region : {e}")



def init_driver():
    import undetected_chromedriver as uc

    os.system("taskkill /F /IM chrome.exe 2>nul")
    time.sleep(3)

    options = uc.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument(r"--user-data-dir=C:\ChromeTemp")
    options.add_argument("--profile-directory=Default")

    driver = uc.Chrome(options=options, use_subprocess=True, version_main=146)
    wait = WebDriverWait(driver, 15)
    return driver, wait


def is_driver_alive(driver):
    """Vérifie si le driver est encore actif."""
    try:
        _ = driver.current_url
        return True
    except:
        return False
    

def get_or_restart_driver(driver, wait):
    """Redémarre le driver s'il est mort."""
    if not is_driver_alive(driver):
        print("  -> Driver mort, redemarrage...")
        try:
            driver.quit()
        except:
            pass
        driver, wait = init_driver()
        print("  -> Driver redémarre OK")
    return driver, wait


def check_captcha(driver, url):
    if "sorry" in driver.current_url or "captcha" in driver.page_source.lower():
        print("  reCAPTCHA detecte - attente 30s...")
        time.sleep(30)
        driver.get(url)
        time.sleep(random.uniform(3, 5))


def get_last_page_number(driver):
    """
    Lit le dernier numéro de page dans une pagination.
    Fonctionne pour Google Search et Google Maps.
    """
    time.sleep(2)

    selectors = [
        # Google Search pagination
        "//table[@class='AaVjTc']//td/a",
        "//div[@id='navcnt']//td/a",
        "//a[@aria-label[contains(.,'Page')]]",
        # Google Maps pagination
        "//button[@aria-label[contains(.,'Page')]]",
        "//div[contains(@class,'fontBodyMedium')]//button",
    ]

    for selector in selectors:
        elements = driver.find_elements(By.XPATH, selector)
        if elements:
            for el in reversed(elements):
                text = el.text.strip()
                if text.isdigit():
                    return int(text)

    return 1


# ======================
# GOOGLE ALL : DERNIER NUMERO DE PAGE
# ======================

def get_google_all_pages(driver, wait, query):
    try:
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}&hl=en&gl=us"
        driver.get(url)
        time.sleep(random.uniform(3, 6))
        check_captcha(driver, url)

        last_page = 1

        while True:
            # Récupérer tous les numéros de page visibles
            page_links = driver.find_elements(By.XPATH,
                "//table[@class='AaVjTc']//td/a | "
                "//div[@id='navcnt']//td/a"
            )

            if not page_links:
                print(f"  -> Google All Pages : {last_page}")
                break

            # Trouver le dernier numéro visible
            last_link = None
            last_num = 0

            for link in page_links:
                text = link.text.strip()
                if text.isdigit() and int(text) > last_num:
                    last_num = int(text)
                    last_link = link

            if not last_link or last_num <= last_page:
                print(f"  -> Google All Pages : {last_page}")
                break

            print(f"  -> Clic sur page {last_num}...")
            driver.execute_script("arguments[0].click();", last_link)
            last_page = last_num
            time.sleep(random.uniform(3, 5))
            check_captcha(driver, url)

            if last_page >= 50:
                print("  -> Limite 50 pages atteinte")
                break

        return last_page

    except Exception as e:
        print(f"  Erreur Google All pages pour '{query}' : {e}")
        return 0


def get_more_businesses_pages(driver, wait, query):
    try:
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}&hl=en&gl=us"
        driver.get(url)
        time.sleep(random.uniform(3, 7))
        check_captcha(driver, url)

        # Chercher bouton "More businesses"
        more_btn = None
        selectors = [
            "//*[contains(text(),'More businesses')]",
            "//*[contains(text(),'More places')]",
            "//*[contains(text(),'Plus d')]",
        ]

        for selector in selectors:
            elements = driver.find_elements(By.XPATH, selector)
            if elements:
                more_btn = elements[0]
                break

        if not more_btn:
            print(f"  Info : Pas de 'More businesses' pour '{query}'")
            return 0

        driver.execute_script("arguments[0].click();", more_btn)
        print(f"  OK 'More businesses' trouve -> clic")
        time.sleep(random.uniform(3, 7))

        page_num = 1

        while True:
            # Sélecteur exact basé sur l'inspect : g-right-button[aria-label="Next"]
            next_btns = driver.find_elements(By.CSS_SELECTOR,
                "g-right-button[aria-label='Next']"
            )

            if not next_btns:
                print(f"  -> More businesses pages : {page_num}")
                break

            btn = next_btns[0]

            # Vérifier si le bouton est désactivé
            is_disabled = (
                btn.get_attribute("disabled") is not None or
                btn.get_attribute("aria-disabled") == "true" or
                "disabled" in (btn.get_attribute("class") or "")
            )

            if is_disabled:
                print(f"  -> More businesses pages : {page_num}")
                break

            # Vérifier URL avant clic
            current_url = driver.current_url

            driver.execute_script("arguments[0].click();", btn)
            page_num += 1
            print(f"  -> More businesses page {page_num}...")
            time.sleep(random.uniform(3, 7))

            # Si URL n'a pas changé -> dernière page
            if driver.current_url == current_url:
                print(f"  -> URL inchangee, derniere page : {page_num}")
                break

            if page_num >= 20:
                print("  -> Limite 20 pages atteinte")
                break

        return page_num

    except Exception as e:
        print(f"  Erreur 'More businesses' pour '{query}' : {e}")
        return 0

# ======================
# FONCTION PRINCIPALE
# ======================

def enrich_with_google_data(filepath="expired_domains.xlsx"):

    df = pd.read_excel(filepath, engine="openpyxl")
    print(f"  -> {len(df)} domaines charges")

    if "Domain" not in df.columns:
        print("Colonne Domain introuvable.")
        return

    if "Google All Pages" not in df.columns:
        df["Google All Pages"] = None
    if "Google Maps Pages" not in df.columns:
        df["Google Maps Pages"] = None

    try:
        for idx, row in df.iterrows():
            domain = str(row["Domain"]).strip()

            google_val = row.get("Google All Pages")
            if pd.notna(google_val) and google_val > 0:
                print(f"  Skip : {domain}")
                continue

            query = domain_to_query(domain)
            print(f"\n[{idx+1}/{len(df)}] {domain} -> '{query}'")

            # Lancer Chrome pour cette recherche
            print(f"  -> Lancement Chrome...")
            driver, wait = init_driver()

            try:
                # Google All Pages
                all_pages = get_google_all_pages(driver, wait, query)
                print(f"  -> Google All Pages : {all_pages}")

                # More businesses Pages
                maps_pages = get_more_businesses_pages(driver, wait, query)
                print(f"  -> Google Maps Pages : {maps_pages}")

                df.at[idx, "Google All Pages"] = all_pages
                df.at[idx, "Google Maps Pages"] = maps_pages
                df.to_excel(filepath, index=False, engine="openpyxl")

            finally:
                # Fermer Chrome après chaque domaine
                try:
                    driver.quit()
                except:
                    pass
                os.system("taskkill /F /IM chrome.exe 2>nul")
                print(f"  -> Chrome ferme")
                time.sleep(random.uniform(3, 5))

    except Exception as e:
        print(f"\nErreur generale : {e}")

    finally:
        df.to_excel(filepath, index=False, engine="openpyxl")
        print(f"\nFichier mis a jour -> {filepath}")