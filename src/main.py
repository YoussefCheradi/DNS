import time
import random
import pandas as pd
from dotenv import load_dotenv
import os
from pathlib import Path
from scrap_from_E_D.E_D import init_driver, login, setup_filters, scrape_city, save_to_excel
from scrap_from_Google.Google import enrich_with_google_data
from seowebchecker_bulk_domain_check import bulk_check_domains

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXCEL_PATH = PROJECT_ROOT / "expired_domains_TLD_net.xlsx"
CITYS_PATH = PROJECT_ROOT / "src" / "citys" / "us_cities_sample.xlsx"

USERNAME           = os.getenv("EXPIREDDOMAINS_USERNAME")
PASSWORD           = os.getenv("EXPIREDDOMAINS_PASSWORD")
GMAIL_ADDRESS      = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")


# ======================
# SCRAPING EXPIRED DOMAINS
# ======================

# df_cities = pd.read_excel(CITYS_PATH)
# cities = df_cities.iloc[:50, 0].dropna().tolist()
# print(f"Villes chargées : {cities}")

# driver, wait = init_driver()
# login(driver, wait, USERNAME, PASSWORD, GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
# setup_filters(driver, wait)

# all_data = []
# for city in cities:
#     city_data = scrape_city(driver, wait, city)
#     all_data.extend(city_data)
#     time.sleep(random.uniform(2, 4))

# save_to_excel(all_data, str(EXCEL_PATH))
# driver.quit()


# ======================
# DNS CHECKER
# ======================

# print("\n🔍 DNS Checker (SEO Web Checker)...")
# bulk_check_domains(str(EXCEL_PATH), auto_close=True)


# # ======================
# # ENRICHISSEMENT GOOGLE + MAPS
# # ======================

print("\n🔍 Enrichissement Google & Google Maps...")
enrich_with_google_data(str(EXCEL_PATH))

print("\n🎉 Pipeline complet terminé !")