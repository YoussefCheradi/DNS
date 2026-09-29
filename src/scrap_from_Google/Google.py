import re
import time
import random
import pandas as pd
import os
from pathlib import Path
from dotenv import load_dotenv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

load_dotenv()


# ======================
# UTILITAIRES
# ======================

def domain_to_query(domain):
    name = re.sub(r'\.[a-z]{2,}$', '', domain, flags=re.IGNORECASE)
    words = re.sub(r'([A-Z])', r' \1', name).strip()
    return words


def init_driver():
    options = uc.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument(r"--user-data-dir=C:\ChromeTemp")
    options.add_argument("--profile-directory=Default")

    try:
        driver = uc.Chrome(options=options, use_subprocess=True)
    except Exception:
        driver = uc.Chrome(options=options, use_subprocess=True, version_main=154)

    wait = WebDriverWait(driver, 15)
    return driver, wait


def is_driver_alive(driver):
    try:
        _ = driver.current_url
        return True
    except:
        return False


def get_or_restart_driver(driver, wait):
    if not is_driver_alive(driver):
        print("  -> Driver mort, redemarrage...")
        try:
            driver.quit()
        except:
            pass
        driver, wait = init_driver()
        print("  -> Driver redemarre OK")
    return driver, wait




def check_captcha(driver, url):
    if "sorry" in driver.current_url or "captcha" in driver.page_source.lower():
        print("  reCAPTCHA detecte - verification iframe...")

        iframes = driver.find_elements(By.XPATH, "//iframe[contains(@src,'recaptcha') and contains(@src,'anchor')]")
        if not iframes:
            print("  -> Iframe reCAPTCHA absente (extension a resolu) - skip resolution")
            return

        print("  -> Iframe presente - tentative de resolution...")
        try:
            driver.switch_to.frame(iframes[0])
            print("  -> Switch iframe reCAPTCHA OK")
            time.sleep(random.uniform(1, 2))

            checkbox = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "span#recaptcha-anchor"))
            )
            driver.execute_script("arguments[0].click();", checkbox)
            print("  -> Checkbox cliquee")

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
                    btn_x, btn_y = 3189, 793
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
            time.sleep(30)

        finally:
            try:
                driver.switch_to.default_content()
            except:
                pass

        driver.get(url)
        time.sleep(random.uniform(3, 5))


# ======================
# SPONSORED RESULTS
# ======================

def check_sponsored_results(driver, query):
    try:
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}&hl=en&gl=us"
        driver.get(url)
        time.sleep(random.uniform(3, 7))
        check_captcha(driver, url)

        sponsored_selectors = [
            "//*[contains(text(),'Sponsored')]",
            "//*[contains(text(),'Sponsorise')]",
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


# ======================
# GOOGLE MAPS : MORE BUSINESSES
# ======================

def get_more_businesses_pages(driver, wait, query):
    try:
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}&hl=en&gl=us"
        driver.get(url)
        time.sleep(random.uniform(3, 7))
        check_captcha(driver, url)

        more_btn = None
        selectors = [
            "//*[contains(text(),'More businesses')]",
            "//*[contains(text(),'More places')]",
            "//*[contains(text(),'More locations')]",
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
            print(f"  Info : Pas de 'More businesses' ni 'More locations' ni 'More places' pour '{query}'")
            return 0

        driver.execute_script("arguments[0].click();", more_btn)
        time.sleep(random.uniform(3, 7))

        # Vérifier captcha après clic More businesses
        check_captcha(driver, url)

        # Compter le nombre de pages Google Maps via les lettres O du tableau de pagination
        page_count = 0

        try:
            table = driver.find_element(By.XPATH, "//tbody")
            o_elements = table.find_elements(By.XPATH, ".//span[contains(@class,'D2pCqd')]")
            page_count = len(o_elements)
            print(f"  -> O count tableau pagination : {page_count}")
        except Exception:
            page_count = 0

        if page_count <= 0:
            page_candidates = driver.find_elements(By.XPATH, "//a[contains(@href,'start=') or contains(@aria-label,'Page') or contains(@aria-label,'page')] ")
            if page_candidates:
                page_count = len(page_candidates)

        page_count = max(0, page_count - 2)

        if page_count <= 0:
            result = "1"
        elif page_count >= 10:
            result = "10"
        else:
            result = str(page_count)

        print(f"  -> Google Maps Pages : {result}")
        return result

    except Exception as e:
        print(f"  Erreur 'More businesses/places' pour '{query}' : {e}")
        return 0


# ======================
# FONCTION PRINCIPALE
# ======================

def enrich_with_google_data(filepath="expired_domains_TLD_net.xlsx"):
    project_root = Path(__file__).resolve().parents[2]
    target_path = project_root / "expired_domains_TLD_net.xlsx"

    if filepath:
        custom_path = Path(filepath).expanduser()
        if custom_path.is_absolute():
            target_path = custom_path
        elif custom_path.name.lower() == "expired_domains.xlsx":
            target_path = project_root / "expired_domains_TLD_net.xlsx"
        else:
            target_path = project_root / custom_path.name

    filepath = str(target_path)

    if not os.path.exists(filepath):
        print(f"  -> Fichier introuvable : {filepath}")
        print("  -> Vérifie que le scraping a bien généré expired_domains_TLD_net.xlsx avant de lancer l'enrichissement Google.")
        return

    df = pd.read_excel(filepath, engine="openpyxl")
    print(f"  -> {len(df)} domaines charges")

    if "Domain" not in df.columns:
        print("Colonne Domain introuvable.")
        return

    valid_mask = pd.Series(True, index=df.index)
    if "HTTP Code" in df.columns:
        valid_mask = df["HTTP Code"].fillna("").astype(str).str.strip().isin(["200", "301", "302"])
        valid_count = int(valid_mask.sum())
        print(f"  -> {valid_count} domaines conserves pour Google (HTTP Code 200/301/302 sur {len(df)})")
        if valid_count == 0:
            print("  -> Aucun domaine ne correspond au filtre HTTP Code 200/301/302. Google search non lance.")
            return
    else:
        print("  -> Colonne HTTP Code absente : Google search applique sur tous les domaines.")

    if "Domaine .net" not in df.columns:
        df["Domaine .net"] = df["Domain"].map(lambda d: re.sub(r'\.com$', '.net', str(d), flags=re.IGNORECASE) if str(d).strip() else d)

    if "Google All Pages" in df.columns:
        df.drop(columns=["Google All Pages"], inplace=True)

    if "Google Maps Pages" not in df.columns:
        df["Google Maps Pages"] = None
    if "Sponsored Results" not in df.columns:
        df["Sponsored Results"] = None

    rows_to_process = df.loc[valid_mask].copy()

    print(f"  -> Lancement Chrome...")
    driver, wait = init_driver()

    try:
        for idx, row in rows_to_process.iterrows():
            domain = str(row["Domain"]).strip()

            maps_val = df.at[idx, "Google Maps Pages"]
            sponsored_val = df.at[idx, "Sponsored Results"]

            has_maps = pd.notna(maps_val) and str(maps_val).strip() != ""
            has_sponsored = pd.notna(sponsored_val) and str(sponsored_val).strip() != ""

            if has_maps and has_sponsored:
                print(f"  Skip : {domain}")
                continue

            query = domain_to_query(domain)
            print(f"\n[{idx+1}/{len(df)}] {domain} -> '{query}'")

            # Vérifier driver vivant
            driver, wait = get_or_restart_driver(driver, wait)

            sponsored = sponsored_val if has_sponsored else "Non"
            maps_pages = maps_val if has_maps else "0"

            if not has_sponsored:
                # 1. Sponsored Results (charge Google Search + check captcha)
                sponsored = check_sponsored_results(driver, query)

            # 2. Check captcha entre sponsored et more businesses
            url = f"https://www.google.com/search?q={query.replace(' ', '+')}&hl=en&gl=us"
            check_captcha(driver, url)

            if not has_maps:
                # 3. More businesses Pages (charge Google Search + check captcha)
                maps_pages = get_more_businesses_pages(driver, wait, query)

            if not has_maps:
                df.at[idx, "Google Maps Pages"] = maps_pages
            if not has_sponsored:
                df.at[idx, "Sponsored Results"] = sponsored
            df.to_excel(filepath, index=False, engine="openpyxl")

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