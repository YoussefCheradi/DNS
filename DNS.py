import time
import random
import pandas as pd
import imaplib
import email
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

USERNAME       = os.getenv("EXPIREDDOMAINS_USERNAME")
PASSWORD       = os.getenv("EXPIREDDOMAINS_PASSWORD")
GMAIL_ADDRESS      = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
wait = WebDriverWait(driver, 20)


# ======================
# CHARGER LES VILLES
# ======================

df_cities = pd.read_excel("us_cities_sample.xlsx")
cities = df_cities.iloc[:10, 0].dropna().tolist()
print(f"Villes chargées : {cities}")


# ======================
# FONCTION : RÉCUPÉRER LE CODE GMAIL
# ======================

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


# ======================
# LOGIN (une seule fois)
# ======================

driver.get("https://expireddomains.net/login/")
wait.until(EC.presence_of_element_located((By.NAME, "login"))).send_keys(USERNAME)
driver.find_element(By.NAME, "password").send_keys(PASSWORD)
driver.find_element(By.XPATH, "//button[text()='Login']").click()
print("Login clicked")
time.sleep(5)

# Détecter la page de vérification
# ✅ Sélecteur précis : champ code only (pas le champ username)
verification_field = driver.find_elements(By.XPATH,
    "//input[@name='code'] | //input[contains(@placeholder,'code')] | //input[contains(@placeholder,'Code')] | //input[contains(@id,'code')]"
)

if verification_field:
    print("Page de vérification détectée → récupération du code Gmail...")
    code = get_verification_code_from_gmail(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)

    if code:
        verification_field[0].clear()
        verification_field[0].send_keys(code)
        time.sleep(1)
        submit = driver.find_element(By.XPATH, "//button[@type='submit'] | //input[@type='submit']")
        driver.execute_script("arguments[0].click();", submit)
        print("✅ Code soumis avec succès")
        time.sleep(5)
    else:
        print("❌ Code non trouvé dans Gmail")
        input("Entre le code manuellement, puis appuie sur Entrée pour continuer...")
else:
    print("✅ Pas de vérification requise, connexion directe")


# ======================
# PAGE EXPIRED DOMAINS
# ======================

driver.get("https://member.expireddomains.net/domains/expiredcom/")
time.sleep(2)


# ======================
# SHOW FILTER
# ======================

show_filter = wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "Show Filter")))
driver.execute_script("arguments[0].click();", show_filter)
time.sleep(2)

# ======================
# COMMON TAB
# ======================

common_tab = wait.until(EC.presence_of_element_located((By.XPATH, "//a[@data-target='#common']")))
driver.execute_script("arguments[0].click();", common_tab)
time.sleep(1)


# ======================
# DOMAIN NAME SETTINGS
# ======================

char_box = wait.until(EC.presence_of_element_located((By.ID, "fonlycharhost")))
if not char_box.is_selected():
    driver.execute_script("arguments[0].click();", char_box)

adult_box = wait.until(EC.presence_of_element_located((By.ID, "fadult")))
if not adult_box.is_selected():
    driver.execute_script("arguments[0].click();", adult_box)

# On laisse le champ vide ici, il sera rempli dans la boucle
domain_input = driver.find_element(By.NAME, "fdomainand")
driver.execute_script("arguments[0].value = '';", domain_input)


# ======================
# LISTING SETTINGS
# ======================

whois_box = wait.until(EC.presence_of_element_located((By.ID, "fwhois")))
if not whois_box.is_selected():
    driver.execute_script("arguments[0].click();", whois_box)

Select(driver.find_element(By.ID, "flimit")).select_by_value("100")


# ======================
# SEO TAB
# ======================

seo_tab = wait.until(EC.presence_of_element_located((By.XPATH, "//a[@data-target='#seo']")))
driver.execute_script("arguments[0].click();", seo_tab)
time.sleep(1)

sv = driver.find_element(By.ID, "fsg")
driver.execute_script("arguments[0].value = '100';", sv)

cpc = driver.find_element(By.ID, "fcpcfrom")
driver.execute_script("arguments[0].value = '1';", cpc)


# ======================
# BOUCLE PAR VILLE
# ======================

all_data = []

for city in cities:
    print(f"\n{'='*40}")
    print(f"Recherche pour la ville : {city}")
    print(f"{'='*40}")

    # ── Rouvrir le filtre s'il est replié ──
    try:
        show_filter_btn = driver.find_elements(By.LINK_TEXT, "Show Filter")
        if show_filter_btn:
            show_filter_btn[0].click()
            time.sleep(2)
    except:
        pass

    # ── S'assurer qu'on est sur l'onglet Common ──
    try:
        common_tab = driver.find_element(By.XPATH, "//a[@data-target='#common']")
        driver.execute_script("arguments[0].click();", common_tab)
        time.sleep(1)
    except:
        pass

    # ── Modifier uniquement le champ "Contains" via JavaScript ──
    domain_input = wait.until(EC.presence_of_element_located((By.NAME, "fdomainand")))
    driver.execute_script("arguments[0].scrollIntoView(true);", domain_input)
    driver.execute_script("arguments[0].value = '';", domain_input)
    driver.execute_script(f"arguments[0].value = '{city}';", domain_input)
    time.sleep(1)

    # ── Appliquer le filtre ──
    submit_btn = wait.until(EC.element_to_be_clickable((By.NAME, "button_submit")))
    driver.execute_script("arguments[0].click();", submit_btn)
    time.sleep(6)

    # ── Scraper les pages ──
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
                        "Date Scraping": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })

        print(f"  → {len(city_data)} domaines pour {city} jusqu'ici")

        # Pagination
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
    all_data.extend(city_data)
    time.sleep(random.uniform(2, 4))


# Export Excel FINAL
df_new = pd.DataFrame(all_data)

if df_new.empty:
    print("\n⚠️  Aucune donnée collectée.")
else:
    try:
        df_existing = pd.read_excel("expired_domains.xlsx")
        df_final = pd.concat([df_existing, df_new], ignore_index=True)
        print(f"  → {len(df_existing)} lignes existantes + {len(df_new)} nouvelles")
    except FileNotFoundError:
        df_final = df_new
        print("  → Nouveau fichier créé")

    df_final.to_excel("expired_domains.xlsx", index=False)
    print(f"\n✅ Excel mis à jour avec {len(df_final)} domaines au total → expired_domains.xlsx")