import time
import random
import pandas as pd

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service

from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

from webdriver_manager.chrome import ChromeDriverManager


USERNAME = "wonderstory"
PASSWORD = "youssefmaroc"

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
wait = WebDriverWait(driver,20)


# ======================
# LOGIN
# ======================

driver.get("https://expireddomains.net/login/")

username = wait.until(
    EC.presence_of_element_located((By.NAME,"login"))
)

username.send_keys(USERNAME)

driver.find_element(By.NAME,"password").send_keys(PASSWORD)

driver.find_element(By.XPATH,"//button[text()='Login']").click()

print("Login clicked")

time.sleep(5)


# ======================
# PAGE EXPIRED DOMAINS
# ======================

driver.get("https://member.expireddomains.net/domains/expiredcom/")

time.sleep(5)


# ======================
# SHOW FILTER
# ======================

wait.until(
    EC.element_to_be_clickable((By.LINK_TEXT,"Show Filter"))
).click()

time.sleep(2)


# ======================
# COMMON TAB
# ======================

driver.find_element(By.XPATH,"//a[@data-target='#common']").click()

time.sleep(1)


# ======================
# DOMAIN NAME SETTINGS
# ======================

# only Characters
# only Characters
char_box = wait.until(
    EC.presence_of_element_located((By.ID,"fonlycharhost"))
)

if not char_box.is_selected():
    char_box.click()


# no Adult Names
adult_box = wait.until(
    EC.presence_of_element_located((By.ID,"fadult"))
)

if not adult_box.is_selected():
    adult_box.click()

# Domain Name Contains ... AND
domain_input = driver.find_element(By.NAME,"fdomainand")
domain_input.clear()
domain_input.send_keys("Stockton")


# ======================
# LISTING SETTINGS
# ======================

# only available Domains
whois_box = wait.until(
    EC.presence_of_element_located((By.ID,"fwhois"))
)

if not whois_box.is_selected():
    whois_box.click()

# Domains per Page = 100
select = Select(driver.find_element(By.ID,"flimit"))
select.select_by_value("100")


# ======================
# SEO TAB
# ======================

driver.find_element(By.XPATH,"//a[@data-target='#seo']").click()

time.sleep(1)


# ======================
# SEO FILTER
# ======================

# SV min
sv = driver.find_element(By.ID,"fsg")
sv.clear()
sv.send_keys("100")

# CPC min
cpc = driver.find_element(By.ID,"fcpcfrom")
cpc.clear()
cpc.send_keys("1")


# ======================
# APPLY FILTER
# ======================

wait.until(
    EC.element_to_be_clickable((By.NAME,"button_submit"))
).click()


time.sleep(6)

# ======================
# SCRAPING - DOMAINES SEULEMENT
# ======================

data = []

for page in range(5):
    print(f"Scraping page {page + 1}...")

    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.base1 tbody tr")))
    except:
        print("Tableau non trouvé, arrêt.")
        break

    rows = driver.find_elements(By.CSS_SELECTOR, "table.base1 tbody tr")
    print(f"  → {len(rows)} lignes trouvées")

    for row in rows:
        domain_els = row.find_elements(By.CSS_SELECTOR, "td.field_domain a")
        if domain_els:
            domain = domain_els[0].text.strip()
            if domain:
                data.append({"Domain": domain})

    print(f"  → {len(data)} domaines collectés au total")

    # Passage à la page suivante
    try:
        next_btn = driver.find_elements(By.LINK_TEXT, "Next Page")
        if not next_btn:
            print("Dernière page atteinte.")
            break
        driver.execute_script("arguments[0].click();", next_btn[0])
        time.sleep(1)
        wait.until(EC.staleness_of(rows[0]))
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.base1 tbody tr")))
        time.sleep(random.uniform(2, 4))
    except Exception as e:
        print(f"Erreur pagination : {e}")
        break

# Export Excel
df = pd.DataFrame(data)

if df.empty:
    print("⚠️  Aucune donnée collectée.")
else:
    df.to_excel("expired_domains.xlsx", index=False)
    print(f"✅ Excel créé avec {len(df)} domaines → expired_domains.xlsx")