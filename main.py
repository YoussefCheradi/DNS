import time
import random
import pandas as pd
from dotenv import load_dotenv
import os
from src.scrap_from_E_D.E_D import init_driver, login, setup_filters, scrape_city, save_to_excel
from src.scrap_from_Google.Google import enrich_with_google_data

load_dotenv()

USERNAME           = os.getenv("EXPIREDDOMAINS_USERNAME")
PASSWORD           = os.getenv("EXPIREDDOMAINS_PASSWORD")
GMAIL_ADDRESS      = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")


# ======================
# SCRAPING EXPIRED DOMAINS
# ======================

df_cities = pd.read_excel("src\\citys\\us_cities_sample.xlsx")
cities = df_cities.iloc[:5, 0].dropna().tolist()
print(f"Villes chargées : {cities}")

driver, wait = init_driver()
login(driver, wait, USERNAME, PASSWORD, GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
setup_filters(driver, wait)

all_data = []
for city in cities:
    city_data = scrape_city(driver, wait, city)
    all_data.extend(city_data)
    time.sleep(random.uniform(2, 4))

save_to_excel(all_data)
driver.quit()


# ======================
# ENRICHISSEMENT GOOGLE + MAPS
# ======================

print("\n🔍 Enrichissement Google & Google Maps...")
enrich_with_google_data("expired_domains.xlsx")

print("\n🎉 Pipeline complet terminé !")