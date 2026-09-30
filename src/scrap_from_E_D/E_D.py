import time
import random
import pandas as pd
import imaplib
import email
import re
import os
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime


def domain_to_net(domain):
    if pd.isna(domain):
        return domain
    value = str(domain).strip()
    if not value:
        return value
    return re.sub(r'\.com$', '.net', value, flags=re.IGNORECASE)


def get_verification_code_from_gmail(gmail_address, app_password, retries=5, delay=10):
    for attempt in range(retries):
        try:
            print(f"  Tentative {attempt+1} : connexion Gmail...")
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(gmail_address, app_password)
            mail.select("inbox")

            status, messages = mail.search(None, '(UNSEEN FROM "expireddomains")')

            if status == "OK" and messages[0]:
                email_ids = messages[0].split()
                latest_id = email_ids[-1]

                status, msg_data = mail.fetch(latest_id, "(RFC822)")
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                            break
                else:
                    body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

                code_match = re.search(r'\b(\d{6})\b', body)
                if code_match:
                    code = code_match.group(1)
                    print(f"  ✅ Code trouvé : {code}")
                    mail.store(latest_id, '+FLAGS', '\\Seen')
                    mail.logout()
                    return code

            mail.logout()
            print(f"  Code pas encore reçu, attente {delay}s...")
            time.sleep(delay)

        except Exception as e:
            print(f"  Erreur Gmail : {e}")
            time.sleep(delay)

    return None


def init_driver(headless=False):
    options = webdriver.ChromeOptions()
    chrome_binary = os.getenv("CHROME_BIN")
    driver_binary = os.getenv("CHROMEDRIVER_PATH")

    if chrome_binary:
        options.binary_location = chrome_binary
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")

    service = Service(driver_binary) if driver_binary else Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, 20)
    return driver, wait


def login(driver, wait, username, password, gmail_address, gmail_app_password, allow_manual_code=True):
    driver.get("https://expireddomains.net/login/")
    wait.until(EC.presence_of_element_located((By.NAME, "login"))).send_keys(username)
    driver.find_element(By.NAME, "password").send_keys(password)
    driver.find_element(By.XPATH, "//button[text()='Login']").click()
    print("Login clicked")
    time.sleep(5)

    verification_field = driver.find_elements(By.XPATH,
        "//input[@name='code'] | //input[contains(@placeholder,'code')] | //input[contains(@placeholder,'Code')] | //input[contains(@id,'code')]"
    )

    if verification_field:
        print("Page de vérification détectée → récupération du code Gmail...")
        if not allow_manual_code and not (gmail_address and gmail_app_password):
            raise RuntimeError(
                "La double authentification ExpiredDomains est activée. "
                "Renseignez l'adresse Gmail et son mot de passe d'application."
            )

        code = get_verification_code_from_gmail(gmail_address, gmail_app_password)

        if code:
            verification_field[0].clear()
            verification_field[0].send_keys(code)
            time.sleep(1)
            submit = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[text()='Verify Code']")))
            driver.execute_script("arguments[0].click();", submit)
            print("✅ Code soumis avec succès")
            time.sleep(5)
        else:
            print("❌ Code non trouvé dans Gmail")
            if not allow_manual_code:
                raise RuntimeError(
                    "Code de vérification Gmail indisponible. Vérifiez l'adresse Gmail "
                    "et le mot de passe d'application, puis relancez le traitement."
                )
            input("Entre le code manuellement, puis appuie sur Entrée pour continuer...")
    else:
        print("✅ Pas de vérification requise, connexion directe")


def setup_filters(driver, wait):
    driver.get("https://member.expireddomains.net/domains/expiredcom/")
    time.sleep(2)

    show_filter = wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "Show Filter")))
    driver.execute_script("arguments[0].click();", show_filter)
    time.sleep(2)

    # Common Tab
    common_tab = wait.until(EC.presence_of_element_located((By.XPATH, "//a[@data-target='#common']")))
    driver.execute_script("arguments[0].click();", common_tab)
    time.sleep(1)

    # heure_box = wait.until(EC.presence_of_element_located((By.ID, "flast48")))
    # if not heure_box.is_selected():
    #     driver.execute_script("arguments[0].click();", heure_box)

    Hyphens_box = wait.until(EC.presence_of_element_located((By.ID, "fsephost")))
    if not Hyphens_box.is_selected():
        driver.execute_script("arguments[0].click();", Hyphens_box)

    char_box = wait.until(EC.presence_of_element_located((By.ID, "fonlycharhost")))
    if not char_box.is_selected():
        driver.execute_script("arguments[0].click();", char_box)

    adult_box = wait.until(EC.presence_of_element_located((By.ID, "fadult")))
    if not adult_box.is_selected():
        driver.execute_script("arguments[0].click();", adult_box)

    domain_input = driver.find_element(By.NAME, "fdomainand")
    driver.execute_script("arguments[0].value = '';", domain_input)

    # Listing Settings
    whois_box = wait.until(EC.presence_of_element_located((By.ID, "fwhois")))
    if not whois_box.is_selected():
        driver.execute_script("arguments[0].click();", whois_box)

    Select(driver.find_element(By.ID, "flimit")).select_by_value("200")

    # Additional Tab
    additional_tab = wait.until(EC.presence_of_element_located((By.XPATH, "//a[@data-target='#additional']")))
    driver.execute_script("arguments[0].click();", additional_tab)
    time.sleep(1)

    TLD_box = wait.until(EC.presence_of_element_located((By.ID, "fstatusnetnot")))
    if not TLD_box.is_selected():
        driver.execute_script("arguments[0].click();", TLD_box)

    # SEO Tab
    seo_tab = wait.until(EC.presence_of_element_located((By.XPATH, "//a[@data-target='#seo']")))
    driver.execute_script("arguments[0].click();", seo_tab)
    time.sleep(1)

    sv = driver.find_element(By.ID, "fsg")
    driver.execute_script("arguments[0].value = '100';", sv)

    cpc = driver.find_element(By.ID, "fcpcfrom")
    driver.execute_script("arguments[0].value = '1';", cpc)

    print("✅ Filtres configurés")


def scrape_city(driver, wait, city):
    print(f"\n{'='*40}")
    print(f"Recherche pour la ville : {city}")
    print(f"{'='*40}")

    # Rouvrir le filtre si replié
    try:
        show_filter_btn = driver.find_elements(By.LINK_TEXT, "Show Filter")
        if show_filter_btn:
            driver.execute_script("arguments[0].click();", show_filter_btn[0])
            time.sleep(2)
    except:
        pass

    # Onglet Common
    try:
        common_tab = driver.find_element(By.XPATH, "//a[@data-target='#common']")
        driver.execute_script("arguments[0].click();", common_tab)
        time.sleep(1)
    except:
        pass

    # Modifier le champ Contains
    domain_input = wait.until(EC.presence_of_element_located((By.NAME, "fdomainand")))
    driver.execute_script("arguments[0].scrollIntoView(true);", domain_input)
    driver.execute_script("arguments[0].value = arguments[1];", domain_input, "")
    driver.execute_script("arguments[0].value = arguments[1];", domain_input, city)
    time.sleep(1)

    # Appliquer le filtre
    submit_btn = wait.until(EC.element_to_be_clickable((By.NAME, "button_submit")))
    driver.execute_script("arguments[0].click();", submit_btn)
    time.sleep(6)

    city_data = []

    for page in range(5):
        print(f"  Page {page + 1}...")

        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.base1 tbody tr")))
        except:
            print("  Tableau non trouvé, on passe.")
            break

        rows = driver.find_elements(By.CSS_SELECTOR, "table.base1 tbody tr")

        for row in rows:
            domain_els = row.find_elements(By.CSS_SELECTOR, "td.field_domain a")
            if domain_els:
                domain = domain_els[0].text.strip()
                if domain:
                    city_data.append({
                        "City": city,
                        "Domain": domain,
                        "Date Scraping from E_D": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })

        print(f"  → {len(city_data)} domaines pour {city} jusqu'ici")

        try:
            next_btn = driver.find_elements(By.LINK_TEXT, "Next Page")
            if not next_btn:
                print("  Dernière page.")
                break
            driver.execute_script("arguments[0].click();", next_btn[0])
            time.sleep(1)
            wait.until(EC.staleness_of(rows[0]))
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.base1 tbody tr")))
            time.sleep(random.uniform(2, 4))
        except Exception as e:
            print(f"  Erreur pagination : {e}")
            break

    print(f"  ✅ {len(city_data)} domaines trouvés pour {city}")
    return city_data


def save_to_excel(all_data, filepath="expired_domains_TLD_net.xlsx"):
    filepath = str(Path(filepath).expanduser()) if not os.path.isabs(filepath) else filepath
    if not os.path.isabs(filepath):
        filepath = str(Path(__file__).resolve().parents[2] / filepath)
    df_new = pd.DataFrame(all_data)

    if df_new.empty:
        print("\n⚠️  Aucune donnée collectée.")
        return

    if "Domain" in df_new.columns and "Domaine .net" not in df_new.columns:
        df_new["Domaine .net"] = df_new["Domain"].map(domain_to_net)

    try:
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            df_existing = pd.read_excel(filepath, engine="openpyxl")
            if "Domaine .net" not in df_existing.columns and "Domain" in df_existing.columns:
                df_existing["Domaine .net"] = df_existing["Domain"].map(domain_to_net)
            df_final = pd.concat([df_existing, df_new], ignore_index=True)
            print(f"  → {len(df_existing)} lignes existantes + {len(df_new)} nouvelles")
        else:
            raise FileNotFoundError
    except (FileNotFoundError, ValueError):
        df_final = df_new
        print("  → Nouveau fichier créé")

    # Trouver les doublons avant suppression
    duplicated_mask = df_final.duplicated(subset=["Domain"], keep="first")
    duplicated_domains = df_final[duplicated_mask]["Domain"].tolist()

    if duplicated_domains:
        print(f"  → {len(duplicated_domains)} doublons supprimés :")
        for d in duplicated_domains:
            print(f"      - {d}")
    else:
        print(f"  → Aucun doublon détecté")

    df_final = df_final[~duplicated_mask]

    df_final.to_excel(filepath, index=False, engine="openpyxl")
    print(f"\n✅ Excel mis à jour avec {len(df_final)} domaines au total → {filepath}")