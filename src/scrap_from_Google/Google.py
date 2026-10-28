import re
import time
import random
import pandas as pd
import os
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from dotenv import load_dotenv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

load_dotenv()

MORE_BUSINESSES_SELECTORS = [
    "//*[contains(text(),'More businesses')]",
    "//*[contains(text(),'More places')]",
    "//*[contains(text(),'More locations')]",
    "//*[contains(text(),'Plus d')]",
    "//*[contains(text(),'Plus de lieux')]",
]
CHROME_CLOSE_DELAY_SECONDS = 2
BUSINESS_PANEL_SETTLE_SECONDS = 10


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

    print("  -> Initialisation Chrome 156...", flush=True)
    driver = uc.Chrome(options=options, use_subprocess=True, version_main=156)
    print("  -> Chrome prêt", flush=True)

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


def _find_more_businesses_button(driver):
    for selector in MORE_BUSINESSES_SELECTORS:
        elements = driver.find_elements(By.XPATH, selector)
        if elements:
            return elements[0]
    return None


def _extract_website_links(driver):
    links = []
    candidates = driver.execute_script(
        """
        return [...document.querySelectorAll(
            'a.cevG5.NJ7wce[href], a.yYlJEf.L48Cpd[href], a[href]'
        )]
            .filter(a =>
                a.matches('.cevG5.NJ7wce, .yYlJEf.L48Cpd') ||
                [...a.querySelectorAll('span')].some(
                    span => span.textContent.trim() === 'Website'
                )
            )
            .map(a => a.href);
        """
    )
    candidates.extend(
        re.findall(
            r'\["(https?://[^"\\]+)"\s*,\s*\d+\s*,\s*7\s*,\s*1\s*,'
            r'\s*\[[^\]]*\]\s*,\s*"Place website"\]',
            driver.page_source,
        )
    )
    for href in candidates:
        if not href:
            continue
        parsed = urlparse(href)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        host = parsed.hostname.lower() if parsed.hostname else ""
        if host == "google.com" or host.endswith(".google.com"):
            redirect = parse_qs(parsed.query)
            target = (redirect.get("url") or redirect.get("q") or [None])[0]
            if target:
                href = target
                parsed = urlparse(href)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            links.append(urlunparse(parsed._replace(fragment="")))
    return list(dict.fromkeys(links))


def _extract_links_by_opening_business_cards(driver, page_number, cancel_check=None):
    heading_selector = ".VkpGBb .dbg0pd"
    heading_count = driver.execute_script(
        "return document.querySelectorAll(arguments[0]).length;",
        heading_selector,
    )
    links = []

    for index in range(heading_count):
        if cancel_check is not None:
            cancel_check()
        previous_links = set(
            driver.execute_script(
                "return [...document.querySelectorAll('a.cevG5.NJ7wce[href]')].map(a => a.href);"
            )
        )
        business_name = driver.execute_script(
            """
            const heading = document.querySelectorAll(arguments[0])[arguments[1]];
            if (!heading) return null;
            const card = heading.closest('[role="button"]') || heading;
            const name = heading.innerText.trim();
            card.click();
            return name;
            """,
            heading_selector,
            index,
        )
        if business_name is None:
            continue

        try:
            WebDriverWait(driver, 5).until(
                lambda current_driver: any(
                    href not in previous_links
                    for href in current_driver.execute_script(
                        "return [...document.querySelectorAll('a.cevG5.NJ7wce[href]')].map(a => a.href);"
                    )
                )
            )
        except TimeoutException:
            pass

        time.sleep(BUSINESS_PANEL_SETTLE_SECONDS)
        business_links = [
            href
            for href in driver.execute_script(
                "return [...document.querySelectorAll('a.cevG5.NJ7wce[href]')].map(a => a.href);"
            )
            if href not in previous_links
        ]
        if business_links:
            links.extend(business_links)
            print(f"  -> {business_name or 'Résultat'} : {business_links[0]}")
        else:
            print(f"  -> {business_name or 'Résultat'} : aucun lien Website")

    return list(dict.fromkeys(links))


def _wait_for_website_links(driver, timeout=15):
    try:
        WebDriverWait(driver, timeout).until(
            lambda current_driver: current_driver.find_elements(
                By.XPATH,
                "//a[@href and .//span[normalize-space()='Website']]",
            )
            or current_driver.find_elements(
                By.CSS_SELECTOR,
                "a.yYlJEf.L48Cpd[href]",
            )
            or '"Place website"' in current_driver.page_source
        )
    except TimeoutException:
        return False
    return True


def _wait_for_maps_results(driver, timeout=10):
    try:
        WebDriverWait(driver, timeout).until(
            lambda current_driver: (
                current_driver.find_elements(By.CSS_SELECTOR, "a.yYlJEf.L48Cpd[href]")
                or _find_more_businesses_button(current_driver)
            )
        )
    except TimeoutException:
        return False
    return True


def _maps_pagination_links(driver):
    pages = {}
    for element in driver.find_elements(By.XPATH, "//a[@href]"):
        href = element.get_attribute("href")
        if not href:
            continue
        parsed = urlparse(href)
        if parsed.path != "/search" or not parsed.hostname:
            continue
        host = parsed.hostname.lower()
        if host != "google.com" and not host.endswith(".google.com"):
            continue
        start_values = parse_qs(parsed.query).get("start", [])
        if not start_values:
            continue
        try:
            start = int(start_values[0])
        except ValueError:
            continue
        if start > 0:
            pages.setdefault(start, href)
    return [pages[start] for start in sorted(pages)]


def scrape_google_website_links(
    domain,
    pages: int | None,
    progress_callback: Callable[[str], None] | None = None,
    cancel_check: Callable[[], None] | None = None,
    result_callback: Callable[[dict], None] | None = None,
):
    print("  -> Lancement Chrome pour le scraping des liens...", flush=True)
    driver, _ = init_driver()
    results = []
    seen_links = set()

    try:
        def collect_current_page(page_number):
            page_links = _extract_links_by_opening_business_cards(
                driver,
                page_number,
                cancel_check=cancel_check,
            )
            if not page_links:
                page_links = _extract_website_links(driver)
            for href in page_links:
                if href not in seen_links:
                    result = {"Google Maps Page": page_number, "Website URL": href}
                    results.append(result)
                    seen_links.add(href)
                    if result_callback is not None:
                        result_callback(result)
            return len(page_links)

        search_queries = list(dict.fromkeys((domain, domain_to_query(domain))))
        selected_query = None
        current_page_url = None
        for query in search_queries:
            search_url = "https://www.google.com/search?" + urlencode(
                {"q": query, "hl": "en", "gl": "us"}
            )
            if progress_callback is not None:
                progress_callback(f"Recherche Google : {query}")
            driver.get(search_url)
            time.sleep(random.uniform(3, 5))
            check_captcha(driver, search_url)

            if cancel_check is not None:
                cancel_check()
            _wait_for_maps_results(driver)
            more_button = _find_more_businesses_button(driver)
            if more_button:
                driver.execute_script("arguments[0].click();", more_button)
                time.sleep(random.uniform(3, 5))
                current_page_url = driver.current_url
                check_captcha(driver, current_page_url)
                _wait_for_website_links(driver)
                page_one_link_count = collect_current_page(1)
                selected_query = query if seen_links else None
                if selected_query:
                    break
            else:
                current_page_url = driver.current_url

            if progress_callback is not None:
                progress_callback(
                    f"Résultats pour « {query} » : {len(seen_links)} lien(s) après ouverture de Maps, "
                    f"bloc More businesses {'présent' if more_button else 'absent'}."
                )

        if selected_query is None:
            if progress_callback is not None:
                progress_callback(
                    "Aucun résultat Google Maps avec un lien Website trouvé pour "
                    f"{', '.join(search_queries)}. "
                    f"Page affichée : {driver.title} ({driver.current_url})."
                )
            return results

        current_start_values = parse_qs(urlparse(current_page_url).query).get("start", [])
        visited_starts = {int(current_start_values[0]) if current_start_values else 0}

        page_number = 1
        while pages is None or page_number <= pages:
            if cancel_check is not None:
                cancel_check()

            if page_number > 1:
                current_start_values = parse_qs(urlparse(current_page_url).query).get("start", [])
                current_start = (
                    int(current_start_values[0])
                    if current_start_values and current_start_values[0].isdigit()
                    else 0
                )
                pagination_links = _maps_pagination_links(driver)
                next_url = next(
                    (
                        href for href in pagination_links
                        if (
                            (start_values := parse_qs(urlparse(href).query).get("start", []))
                            and start_values[0].isdigit()
                            and int(start_values[0]) > current_start
                            and int(start_values[0]) not in visited_starts
                        )
                    ),
                    None,
                )
                if next_url is None:
                    break
                current_page_url = next_url
                next_start = int(parse_qs(urlparse(next_url).query)["start"][0])
                visited_starts.add(next_start)
                driver.get(current_page_url)
                time.sleep(random.uniform(3, 7))
                check_captcha(driver, current_page_url)
                _wait_for_website_links(driver)

            page_link_count = (
                page_one_link_count
                if page_number == 1
                else collect_current_page(page_number)
            )
            if progress_callback is not None:
                page_limit = "toutes" if pages is None else str(pages)
                progress_callback(
                    f"Page Google Maps {page_number}/{page_limit} : "
                    f"{page_link_count} lien(s) Website trouvé(s)."
                )
            page_number += 1

        return results
    finally:
        print(
            f"  -> Chrome restera ouvert {CHROME_CLOSE_DELAY_SECONDS} secondes...",
            flush=True,
        )
        try:
            time.sleep(CHROME_CLOSE_DELAY_SECONDS)
        finally:
            driver.quit()


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
        more_btn = _find_more_businesses_button(driver)
        if more_btn:
            print(f"  OK Bouton trouve : '{more_btn.text.strip()}'")

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

def enrich_with_google_data(
    filepath="expired_domains_TLD_net_final.xlsx",
    domains=None,
    progress_callback: Callable[[str], None] | None = None,
    cancel_check: Callable[[], None] | None = None,
    target_tld: str | None = None,
):
    project_root = Path(__file__).resolve().parents[2]
    target_path = project_root / "expired_domains_TLD_net_final.xlsx"

    if filepath:
        custom_path = Path(filepath).expanduser()
        if custom_path.is_absolute():
            target_path = custom_path
        elif custom_path.name.lower() == "expired_domains.xlsx":
            target_path = project_root / "expired_domains_TLD_net_final.xlsx"
        else:
            target_path = project_root / custom_path.name

    filepath = str(target_path)

    if not os.path.exists(filepath):
        print(f"  -> Fichier introuvable : {filepath}")
        print("  -> Vérifie que le scraping a bien généré expired_domains_TLD_net_final.xlsx avant de lancer l'enrichissement Google.")
        return

    if cancel_check is not None:
        cancel_check()
    df = pd.read_excel(filepath, engine="openpyxl")
    print(f"  -> {len(df)} domaines charges")

    if "Domain" not in df.columns:
        print("Colonne Domain introuvable.")
        return

    print(f"  -> {len(df)} domaines conserves pour Google, tous codes HTTP inclus")

    target_column = f"Domaine {target_tld}" if target_tld else None
    if target_column and target_column not in df.columns:
        df[target_column] = df["Domain"].map(
            lambda domain: re.sub(r"\.[^.]+$", target_tld, str(domain), flags=re.IGNORECASE)
            if str(domain).strip()
            else domain
        )
    elif not target_tld and "Domaine .net" not in df.columns:
        df["Domaine .net"] = df["Domain"].map(
            lambda domain: re.sub(r"\.com$", ".net", str(domain), flags=re.IGNORECASE)
            if str(domain).strip()
            else domain
        )
    search_column = target_column if target_column and target_column in df.columns else "Domain"

    if "Google All Pages" in df.columns:
        df.drop(columns=["Google All Pages"], inplace=True)

    if "Google Maps Pages" not in df.columns:
        df["Google Maps Pages"] = None
    if "Sponsored Results" not in df.columns:
        df["Sponsored Results"] = None
    df["Google Maps Pages"] = df["Google Maps Pages"].astype("object")
    df["Sponsored Results"] = df["Sponsored Results"].astype("object")

    rows_to_process = df.copy()
    if domains is not None:
        requested_domains = {
            str(domain).strip().lower().rstrip(".")
            for domain in domains
            if str(domain).strip()
        }
        rows_to_process = rows_to_process.loc[
            rows_to_process[search_column].map(
                lambda domain: str(domain).strip().lower().rstrip(".")
            ).isin(requested_domains)
        ]

    print(f"  -> {len(rows_to_process)} nouveaux domaines à rechercher sur Google")
    if rows_to_process.empty:
        return

    print(f"  -> Lancement Chrome...")
    driver, wait = init_driver()
    processed_count = 0

    try:
        for idx, row in rows_to_process.iterrows():
            if cancel_check is not None:
                cancel_check()
            domain = str(row[search_column]).strip()

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

            result_message = (
                f"Google · {domain} : {df.at[idx, 'Google Maps Pages']} page(s) Maps ; "
                f"résultats sponsorisés : {df.at[idx, 'Sponsored Results']}."
            )
            print(result_message)
            if progress_callback is not None:
                progress_callback(result_message)
            processed_count += 1
            if cancel_check is not None:
                cancel_check()

            delay = random.uniform(5, 15)
            print(f"  -> Attente {delay:.1f}s avant prochain domaine...")
            time.sleep(delay)

    except Exception as e:
        print(f"\nErreur generale : {e}")
        raise

    finally:
        try:
            driver.quit()
        except:
            pass
        df.to_excel(filepath, index=False, engine="openpyxl")
        print(f"\nGoogle : {processed_count}/{len(rows_to_process)} domaine(s) traité(s).")
        print(f"Fichier mis a jour -> {filepath}")