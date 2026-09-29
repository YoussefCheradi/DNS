import time
from pathlib import Path

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def find_excel_file() -> Path:
    preferred = PROJECT_ROOT / "expired_domains_TLD_net.xlsx"
    if preferred.exists():
        return preferred

    legacy = PROJECT_ROOT / "expired_domains.xlsx"
    if legacy.exists():
        return legacy

    src_preferred = PROJECT_ROOT / "src" / "expired_domains_TLD_net.xlsx"
    if src_preferred.exists():
        return src_preferred

    src_legacy = PROJECT_ROOT / "src" / "expired_domains.xlsx"
    if src_legacy.exists():
        return src_legacy

    return preferred


def get_domains_from_excel(file_path: Path):
    df = pd.read_excel(file_path, engine="openpyxl")

    if "Domaine .net" in df.columns:
        col_name = "Domaine .net"
    elif "Domain" in df.columns:
        col_name = "Domain"
    else:
        raise ValueError(f"Aucune colonne 'Domaine .net' ou 'Domain' trouvée dans {file_path}.")

    values = df[col_name].dropna().astype(str).str.strip()
    domains = []
    seen = set()

    for value in values:
        if not value:
            continue
        if value not in seen:
            seen.add(value)
            domains.append(value)

    if not domains:
        raise ValueError(f"La colonne '{col_name}' est vide dans {file_path}.")

    return domains


def normalize_domain(value):
    if pd.isna(value):
        return ""
    text = str(value).strip().lower().rstrip('.')
    return text


def merge_dns_results_into_main_excel(main_excel_path: Path, dns_results_path: Path):
    main_df = pd.read_excel(main_excel_path, engine="openpyxl")
    dns_df = pd.read_excel(dns_results_path, engine="openpyxl")

    if "Domaine .net" not in main_df.columns and "Domain" in main_df.columns:
        main_df["Domaine .net"] = main_df["Domain"].map(lambda d: d.replace(".com", ".net") if isinstance(d, str) and ".com" in d.lower() else d)

    if "Domaine .net" not in dns_df.columns and "Domain" in dns_df.columns:
        dns_df["Domaine .net"] = dns_df["Domain"].map(lambda d: d.replace(".com", ".net") if isinstance(d, str) and ".com" in d.lower() else d)

    for col in ["Status", "HTTP Code", "Resolved IP", "Note"]:
        if col not in main_df.columns:
            main_df[col] = pd.Series([None] * len(main_df), dtype="object")
        else:
            main_df[col] = main_df[col].astype("object")

    dns_df = dns_df[["Domaine .net", "Status", "HTTP Code", "Resolved IP", "Note"]].copy()
    dns_df["Domaine .net"] = dns_df["Domaine .net"].map(normalize_domain)
    dns_df = dns_df.drop_duplicates(subset=["Domaine .net"], keep="last")

    main_df["__join_domain"] = main_df["Domaine .net"].map(normalize_domain)

    for idx, row in main_df.iterrows():
        key = row["__join_domain"]
        if not key:
            continue
        match = dns_df[dns_df["Domaine .net"] == key]
        if match.empty:
            continue
        for col in ["Status", "HTTP Code", "Resolved IP", "Note"]:
            value = match.iloc[0][col]
            if pd.notna(value) and str(value).strip() not in ("", "nan", "None"):
                existing_value = main_df.at[idx, col]
                if pd.isna(existing_value) or str(existing_value).strip() in ("", "nan", "None"):
                    main_df.at[idx, col] = value

    main_df = main_df.drop(columns=["__join_domain"], errors="ignore")
    main_df.to_excel(main_excel_path, index=False, engine="openpyxl")
    print(f"✅ Jointure effectuée sur Domaine .net dans : {main_excel_path}")
    return main_df


def init_driver():
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
    wait = WebDriverWait(driver, 20)
    return driver, wait


def extract_results_table(driver, wait):
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.results-table tbody tr")))
    time.sleep(2)

    rows = driver.find_elements(By.CSS_SELECTOR, "table.results-table tbody tr")
    result_rows = []

    for row in rows:
        cells = row.find_elements(By.TAG_NAME, "td")
        if len(cells) < 6:
            continue

        domain = cells[1].text.strip()
        status = cells[2].text.strip()
        http_code = cells[3].text.strip()
        resolved_ip = cells[4].text.strip()
        note = cells[5].text.strip()

        result_rows.append({
            "Domaine .net": domain,
            "Status": status,
            "HTTP Code": http_code,
            "Resolved IP": resolved_ip,
            "Note": note,
        })

    return result_rows


def bulk_check_domains(file_path: str | Path | None = None, auto_close: bool = False):
    if file_path is None:
        excel_path = PROJECT_ROOT / "expired_domains_TLD_net.xlsx"
    else:
        excel_path = Path(file_path)
        if not excel_path.exists():
            excel_path = PROJECT_ROOT / "expired_domains_TLD_net.xlsx"

    if excel_path.name.lower() == "expired_domains.xlsx":
        excel_path = PROJECT_ROOT / "expired_domains_TLD_net.xlsx"

    domains = get_domains_from_excel(excel_path)

    if len(domains) > 500:
        print(f"{len(domains)} domaines trouvés. Seuls les 500 premiers seront envoyés.")
        domains = domains[:500]

    print(f"Chargement de {len(domains)} domaines depuis : {excel_path}")

    driver, wait = init_driver()
    try:
        driver.get("https://seowebchecker.com/bulk-domain-search")
        wait.until(EC.presence_of_element_located((By.ID, "domainInput")))

        textarea = driver.find_element(By.ID, "domainInput")
        domain_text = "\n".join(domains)

        driver.execute_script(
            "arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('input', {bubbles: true}));",
            textarea,
            domain_text,
        )

        time.sleep(1)

        button = wait.until(EC.element_to_be_clickable((By.ID, "checkBtn")))
        driver.execute_script("arguments[0].click();", button)

        print("✅ Bouton 'Check Domains' cliqué.")
        print("Le site traite maintenant les domaines envoyés.")

        rows = extract_results_table(driver, wait)
        df_results = pd.DataFrame(rows)

        raw_results_path = PROJECT_ROOT / "dns_checker_results.xlsx"
        if df_results.empty:
            print("⚠️ Aucune ligne détectée dans le tableau de résultats.")
            return False

        df_results.to_excel(raw_results_path, index=False, engine="openpyxl")
        merge_dns_results_into_main_excel(excel_path, raw_results_path)

        if raw_results_path.exists():
            raw_results_path.unlink()
            print(f"✅ Fichier temporaire supprimé : {raw_results_path}")

        return True
    finally:
        if auto_close:
            driver.quit()
        else:
            input("Appuie sur Entrée pour fermer le navigateur...")
            driver.quit()


def main():
    bulk_check_domains(auto_close=True)


if __name__ == "__main__":
    main()
