import re
import time
import random
import pandas as pd
import os
import requests
from dotenv import load_dotenv

load_dotenv()

SERPER_API_KEY = os.getenv("SERPER_API_KEY")


def domain_to_query(domain):
    name = re.sub(r'\.[a-z]{2,}$', '', domain, flags=re.IGNORECASE)
    words = re.sub(r'([A-Z])', r' \1', name).strip()
    return words


def get_google_all_pages(query):
    try:
        url = "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": SERPER_API_KEY,
            "Content-Type": "application/json"
        }

        # Première requête pour avoir totalResults
        payload = {
            "q": query,
            "gl": "us",
            "hl": "en",
            "num": 10,
            "page": 1
        }
        response = requests.post(url, headers=headers, json=payload)
        data = response.json()

        # Essayer totalResults
        total_str = data.get("searchInformation", {}).get("totalResults", "0")
        total = int(str(total_str).replace(",", ""))

        if total > 0:
            # Calculer le nombre de pages depuis totalResults
            pages = (total // 10) + (1 if total % 10 > 0 else 0)
            # Limiter à 100 pages max (Google limite à ~100 pages)
            pages = min(pages, 100)
            print(f"  -> Google All Pages : {pages} ({total} resultats)")
            return pages

        # Si pas de totalResults → compter en paginant
        total_results = 0
        page = 1

        while True:
            payload["page"] = page
            response = requests.post(url, headers=headers, json=payload)
            data = response.json()

            organic = data.get("organic", [])
            if not organic:
                break

            total_results += len(organic)
            page += 1

            if page > 50:
                break

            time.sleep(0.5)

        pages = page - 1
        print(f"  -> Google All Pages : {pages} ({total_results} resultats)")
        return pages

    except Exception as e:
        print(f"  Erreur Serper pour '{query}' : {e}")
        return 0


def get_google_maps_pages(query):
    try:
        url = "https://google.serper.dev/places"
        headers = {
            "X-API-KEY": SERPER_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "q": query,
            "gl": "us",
            "hl": "en"
        }
        response = requests.post(url, headers=headers, json=payload)
        data = response.json()

        places = data.get("places", [])
        total = len(places)
        print(f"  -> Google Maps Places : {total} businesses")
        return total

    except Exception as e:
        print(f"  Erreur Serper Places pour '{query}' : {e}")
        return 0
def enrich_with_google_data(filepath="expired_domains.xlsx"):

    if not SERPER_API_KEY:
        print("SERPER_API_KEY manquant dans .env")
        return

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

            all_pages = get_google_all_pages(query)
            maps_pages = get_google_maps_pages(query)

            df.at[idx, "Google All Pages"] = all_pages
            df.at[idx, "Google Maps Pages"] = maps_pages
            df.to_excel(filepath, index=False, engine="openpyxl")

            time.sleep(random.uniform(1, 2))

    except Exception as e:
        print(f"\nErreur generale : {e}")

    finally:
        df.to_excel(filepath, index=False, engine="openpyxl")
        print(f"\nFichier mis a jour -> {filepath}")