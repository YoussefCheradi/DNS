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
        print("  reCAPTCHA detecte - verification iframe...")

        # Verifier si l'iframe recaptcha est vraiment presente
        iframes = driver.find_elements(By.XPATH, "//iframe[contains(@src,'recaptcha') and contains(@src,'anchor')]")
        if not iframes:
            print("  -> Iframe reCAPTCHA absente (extension a resolu) - skip resolution")
            return

        print("  -> Iframe presente - tentative de resolution...")
        try:
            driver.switch_to.frame(iframes[0])
            print("  -> Switch iframe reCAPTCHA OK")
            time.sleep(random.uniform(1, 2))

            # Clic sur la checkbox
            checkbox = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "span#recaptcha-anchor"))
            )
            driver.execute_script("arguments[0].click();", checkbox)
            print("  -> Checkbox cliquee")

            # Retour au contexte principal
            driver.switch_to.default_content()
            print("  -> Retour contexte principal")
            time.sleep(random.uniform(3, 5))

            try:
                import pyautogui
                import pygetwindow as gw

                pyautogui.FAILSAFE = False

                chrome_windows = gw.getWindowsWithTitle("Google")
                if chrome_windows:
                    chrome_windows[0].activate()
                    time.sleep(1)

                try:
                    btn_pos = pyautogui.locateOnScreen('solver_button.png', confidence=0.7)
                    if btn_pos:
                        btn_x, btn_y = pyautogui.center(btn_pos)
                        print(f"  -> Bouton trouve par image : ({btn_x}, {btn_y})")
                    else:
                        raise Exception("Image non trouvee")
                except:
                    btn_x, btn_y = 3189, 1243
                    print(f"  -> Fallback coordonnees fixes : ({btn_x}, {btn_y})")

                pyautogui.moveTo(btn_x, btn_y, duration=0.5)
                time.sleep(0.5)
                pyautogui.click(btn_x, btn_y)
                print(f"  -> Bouton Solve clique ({btn_x}, {btn_y})")
                time.sleep(random.uniform(4, 8))

            except Exception as e2:
                print(f"  -> pyautogui erreur : {e2}")
                print("  -> Attente manuelle 30s...")
                time.sleep(30)

        except Exception as e:
            print(f"  Erreur resolution captcha : {e}")
            print("  -> Attente manuelle 30s...")
            time.sleep(30)

        finally:
            try:
                driver.switch_to.default_content()
            except:
                pass

        driver.get(url)
        time.sleep(random.uniform(3, 5))
# ======================
# GOOGLE ALL : DERNIER NUMERO DE PAGE
# ======================


def get_more_businesses_pages(driver, wait, query):
    try:
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}&hl=en&gl=us"
        driver.get(url)
        time.sleep(random.uniform(3, 7))
        check_captcha(driver, url)

        # Chercher bouton "More businesses" OU "More places"
        more_btn = None
        selectors = [
            "//*[contains(text(),'More businesses')]",
            "//*[contains(text(),'More places')]",
            "//*[contains(text(),'Plus d')]",
            "//*[contains(text(),'Plus de lieux')]",
        ]
        for selector in selectors:
            elements = driver.find_elements(By.XPATH, selector)
            if elements:
                more_btn = elements[0]
                print(f"  OK Bouton trouve : '{elements[0].text.strip()}'")
                break

        if not more_btn:
            print(f"  Info : Pas de 'More businesses' ni 'More places' pour '{query}'")
            return 0

        driver.execute_script("arguments[0].click();", more_btn)
        time.sleep(random.uniform(3, 7))

        # Compter les span.SJajHc = nombre de pages
        o_elements = driver.find_elements(By.CSS_SELECTOR, "span.SJajHc")
        o_count = len(o_elements)
        o_count = max(0, o_count - 2)
        if o_count == 0:
            result = "1"
        elif o_count >= 10:
            result = "10+"
        else:
            result = str(o_count)

        print(f"  -> Google Maps Pages : {result}")
        return result

    except Exception as e:
        print(f"  Erreur 'More businesses/places' pour '{query}' : {e}")
        return 0


def check_sponsored_results(driver):
    try:
        sponsored_selectors = [
            "//*[contains(text(),'Sponsored')]",
            "//*[contains(text(),'Sponsorisé')]",
            "//*[@aria-label='Ads']",
            "//span[contains(@class,'x2VHCd')]",
            "//div[contains(@class,'commercial-unit')]",
        ]
        for selector in sponsored_selectors:
            elements = driver.find_elements(By.XPATH, selector)
            if elements:
                print(f"  -> Sponsored Results : Oui")
                return "Oui"

        print(f"  -> Sponsored Results : Non")
        return "Non"

    except Exception as e:
        print(f"  Erreur check sponsored : {e}")
        return "Non"


def enrich_with_google_data(filepath="expired_domains.xlsx"):

    df = pd.read_excel(filepath, engine="openpyxl")
    print(f"  -> {len(df)} domaines charges")

    if "Domain" not in df.columns:
        print("Colonne Domain introuvable.")
        return

    if "Google All Pages" in df.columns:
        df.drop(columns=["Google All Pages"], inplace=True)

    if "Google Maps Pages" not in df.columns:
        df["Google Maps Pages"] = None
    if "Sponsored Results" not in df.columns:
        df["Sponsored Results"] = None

    print(f"  -> Lancement Chrome...")
    driver, wait = init_driver()

    try:
        for idx, row in df.iterrows():
            domain = str(row["Domain"]).strip()

            maps_val = row.get("Google Maps Pages")
            sponsored_val = row.get("Sponsored Results")

            # if pd.notna(maps_val) and pd.notna(sponsored_val):
            #     print(f"  Skip : {domain}")
            #     continue

            if pd.notna(maps_val) and str(maps_val).strip() != "0" and pd.notna(sponsored_val):
                print(f"  Skip : {domain}")
                continue

            query = domain_to_query(domain)
            print(f"\n[{idx+1}/{len(df)}] {domain} -> '{query}'")

            # More businesses Pages
            maps_pages = get_more_businesses_pages(driver, wait, query)

            # Sponsored Results (meme page deja chargee)
            sponsored = check_sponsored_results(driver)

            df.at[idx, "Google Maps Pages"] = maps_pages
            df.at[idx, "Sponsored Results"] = sponsored
            df.to_excel(filepath, index=False, engine="openpyxl")

            # Delai humain entre chaque domaine
            delay = random.uniform(5, 15)
            print(f"  -> Attente {delay:.1f}s avant prochain domaine...")
            time.sleep(delay)

    except Exception as e:
        print(f"\nErreur generale : {e}")

    finally:
        try:
            driver.quit()
        except:
            pass
        df.to_excel(filepath, index=False, engine="openpyxl")
        print(f"\nFichier mis a jour -> {filepath}")