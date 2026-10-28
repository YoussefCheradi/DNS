from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import random
import re
import tempfile
import threading
import time
import uuid
from urllib.parse import urlparse

import pandas as pd
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, render_template, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from scrap_from_E_D.E_D import (
    init_driver as init_expired_domains_driver,
    login,
    normalize_tld,
    save_to_excel,
    scrape_city,
    setup_filters,
)
from scrap_from_Google.Google import enrich_with_google_data, scrape_google_website_links
from scrap_from_Google.website_contacts import scrape_website_contacts
from seowebchecker_bulk_domain_check import bulk_check_domains


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

EXPIREDDOMAINS_USERNAME = os.getenv("EXPIREDDOMAINS_USERNAME")
EXPIREDDOMAINS_PASSWORD = os.getenv("EXPIREDDOMAINS_PASSWORD")
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
CITY_FILE = PROJECT_ROOT / "src" / "citys" / "us_cities_sample.xlsx"
COUNTRY_CITY_FILES = {
    "us": CITY_FILE,
    "ca": PROJECT_ROOT / "src" / "citys" / "villes_canada.xlsx",
}
def _output_filename_for_country_tld(country, tld):
    suffix = normalize_tld(tld)[1:]
    tld_suffix = suffix.replace(".", "_")
    country_code = country.strip().lower()
    if country_code == "us":
        return f"expired_domains_TLD_{tld_suffix}_final.xlsx"
    return f"expired_domains_{country_code.upper()}_TLD_{tld_suffix}_final.xlsx"


OUTPUT_FILENAME = _output_filename_for_country_tld("us", ".net")

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="domain-search")
jobs = {}
jobs_lock = threading.Lock()


class JobCancelled(Exception):
    pass


def _check_cancelled(cancel_event):
    if cancel_event.is_set():
        raise JobCancelled("Annulation demandée par l’utilisateur.")


def _finish_cancelled_job(job_id, message="Traitement annulé par l’utilisateur."):
    _set_job(
        job_id,
        status="cancelled",
        stage="Traitement annulé",
        error=None,
        download_url=None,
    )
    _append_log(job_id, message)


def _all_cities(country="us"):
    city_file = COUNTRY_CITY_FILES.get(country)
    if city_file is None:
        return []
    try:
        frame = pd.read_excel(city_file, engine="openpyxl")
        column = "Ville" if "Ville" in frame.columns else frame.columns[0]
        return [city.strip() for city in frame[column].dropna().astype(str) if city.strip()]
    except (FileNotFoundError, IndexError, ValueError):
        return []


@app.errorhandler(RequestEntityTooLarge)
def handle_upload_too_large(error):
    return jsonify(error=f"Le fichier dépasse la taille maximale autorisée de 30 Mo ({error.name})."), 413


@app.before_request
def restrict_to_local_machine():
    if request.remote_addr not in {"127.0.0.1", "::1"}:
        abort(403)


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    cities = _all_cities()
    return render_template(
        "index.html",
        default_cities=cities[:10],
        city_total=len(cities),
        country="us",
    )


@app.get("/api/cities")
def city_list():
    country = request.args.get("country", "us").lower()
    if country not in COUNTRY_CITY_FILES:
        return jsonify(error="Choisissez un pays valide."), 400
    cities = _all_cities(country)
    if not cities:
        return jsonify(error="Aucune ville disponible pour ce pays."), 404
    return jsonify(cities=cities, total=len(cities))


def _append_log(job_id, message):
    with jobs_lock:
        job = jobs.get(job_id)
        if job:
            job["logs"].append(message)
            job["logs"] = job["logs"][-60:]


def _set_job(job_id, **updates):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(updates)


def _set_stage(job_id, stage, progress, message=None):
    _set_job(job_id, stage=stage, progress=progress)
    if message:
        _append_log(job_id, message)


def _new_checkpoint(cities):
    return {
        "phase": "scrape",
        "remaining_cities": list(cities),
        "collected": [],
        "new_domains": [],
        "retry_domains": [],
    }


def _store_checkpoint(job_id, checkpoint):
    _set_job(
        job_id,
        _checkpoint={
            **checkpoint,
            "remaining_cities": list(checkpoint["remaining_cities"]),
            "collected": list(checkpoint["collected"]),
            "new_domains": list(checkpoint["new_domains"]),
            "retry_domains": list(checkpoint["retry_domains"]),
        },
    )


def _run_pipeline(
    job_id,
    cities,
    username,
    password,
    gmail_address,
    gmail_app_password,
    run_dns,
    run_google,
    cancel_event,
    tld=".net",
    country="us",
):
    driver = None
    output_filename = _output_filename_for_country_tld(country, tld)
    output_path = PROJECT_ROOT / output_filename
    checkpoint = jobs[job_id]["_checkpoint"]

    try:
        _check_cancelled(cancel_event)
        _set_job(job_id, status="running")
        if checkpoint["phase"] == "scrape":
            _set_stage(job_id, "Connexion à ExpiredDomains", 4, "Démarrage de Chrome pour ExpiredDomains…")
            driver, wait = init_expired_domains_driver()
            _check_cancelled(cancel_event)
            login(
                driver,
                wait,
                username,
                password,
                gmail_address,
                gmail_app_password,
                allow_manual_code=False,
            )
            _check_cancelled(cancel_event)
            _set_stage(job_id, "Configuration des filtres", 12, "Compte connecté, configuration des filtres…")
            setup_filters(driver, wait, tld=tld)
            _check_cancelled(cancel_event)

            collected = list(checkpoint["collected"])
            remaining_cities = list(checkpoint["remaining_cities"])
            completed_cities = len(cities) - len(remaining_cities)
            for offset, city in enumerate(remaining_cities):
                _check_cancelled(cancel_event)
                index = completed_cities + offset + 1
                progress = 16 + round((index - 1) / len(cities) * 42)
                _set_stage(
                    job_id,
                    f"Recherche {index}/{len(cities)} · {city}",
                    progress,
                    f"Recherche des domaines pour {city} ({index}/{len(cities)})…",
                )
                city_domains = scrape_city(
                    driver,
                    wait,
                    city,
                    cancel_check=lambda: _check_cancelled(cancel_event),
                    progress_callback=lambda message: _append_log(job_id, message),
                )
                collected.extend(city_domains)
                checkpoint.update(
                    collected=list(collected),
                    remaining_cities=list(remaining_cities[offset + 1:]),
                )
                _store_checkpoint(job_id, checkpoint)
                if index < len(cities) and cancel_event.wait(random.uniform(2, 4)):
                    break

            driver.quit()
            driver = None

            if cancel_event.is_set():
                if collected:
                    save_to_excel(collected, str(output_path), tld=tld)
                _finish_cancelled_job(
                    job_id,
                    f"Traitement annulé. Les domaines déjà collectés ont été enregistrés dans {output_filename}.",
                )
                return
            if not collected:
                raise RuntimeError("Aucun domaine n’a été trouvé pour les villes sélectionnées.")

            collection_summary = save_to_excel(collected, str(output_path), tld=tld)
            checkpoint.update(
                phase="dns",
                remaining_cities=[],
                collected=list(collected),
                new_domains=list(dict.fromkeys(
                    [*checkpoint["retry_domains"], *collection_summary["new_domains"]]
                )),
                retry_domains=[],
            )
            _store_checkpoint(job_id, checkpoint)
            new_domains = list(checkpoint["new_domains"])
            if not output_path.is_file():
                raise RuntimeError("Le classeur Excel n’a pas pu être créé.")

            row_count = len(pd.read_excel(output_path, engine="openpyxl"))
            _set_job(job_id, row_count=row_count)
            collected_count = collection_summary["collected_count"]
            new_domain_count = len(new_domains)
            _append_log(
                job_id,
                f"Collecte : {collected_count} "
                f"{'domaine trouvé' if collected_count == 1 else 'domaines trouvés'}, "
                f"{new_domain_count} "
                f"{'nouveau domaine' if new_domain_count == 1 else 'nouveaux domaines'}, "
                f"{collection_summary['existing_duplicates'] + collection_summary['batch_duplicates']} doublons "
                f"({collection_summary['existing_duplicates']} déjà présents, "
                f"{collection_summary['batch_duplicates']} répétés dans la collecte).",
            )
        else:
            new_domains = list(checkpoint["new_domains"])
            if not output_path.is_file():
                raise FileNotFoundError(
                    f"Classeur nécessaire à la reprise introuvable : {output_path}"
                )
            _append_log(
                job_id,
                f"Reprise à l’étape {checkpoint['phase']} ; les {len(new_domains)} nouveaux domaines déjà collectés sont conservés.",
            )

        _set_stage(
            job_id, "Vérification DNS et HTTP", 62,
            f"{len(new_domains)} nouveaux domaines à vérifier.",
        )

        if checkpoint["phase"] == "dns" and run_dns and new_domains:
            try:
                if not bulk_check_domains(
                    str(output_path),
                    auto_close=True,
                    domains=new_domains,
                    cancel_check=lambda: _check_cancelled(cancel_event),
                    target_tld=tld,
                ):
                    raise RuntimeError(
                        "SEO Web Checker n’a retourné aucun résultat ; l’étape DNS pourra être reprise."
                    )
            except Exception as exc:
                if cancel_event.is_set():
                    _finish_cancelled_job(job_id, "Traitement annulé pendant la vérification DNS.")
                    return
                _append_log(job_id, f"Erreur SEO Web Checker ({type(exc).__name__}) : {exc!r}")
                raise
        elif checkpoint["phase"] == "dns" and run_dns:
            _append_log(job_id, "Aucun nouveau domaine à vérifier avec SEO Web Checker.")
        elif checkpoint["phase"] == "dns":
            _append_log(job_id, "Vérification SEO Web Checker ignorée.")

        if checkpoint["phase"] == "dns":
            checkpoint["phase"] = "google"
            _store_checkpoint(job_id, checkpoint)
        _check_cancelled(cancel_event)
        if checkpoint["phase"] == "google" and run_google and new_domains:
            _set_stage(job_id, "Enrichissement Google et Maps", 78, "Recherche des indicateurs Google…")
            try:
                enrich_with_google_data(
                    str(output_path),
                    domains=new_domains,
                    progress_callback=lambda message: _append_log(job_id, message),
                    cancel_check=lambda: _check_cancelled(cancel_event),
                    target_tld=tld,
                )
            except Exception as exc:
                if cancel_event.is_set():
                    _finish_cancelled_job(job_id, "Traitement annulé pendant la recherche Google.")
                    return
                _append_log(
                    job_id,
                    f"Erreur Google/Chrome ({type(exc).__name__}) : {exc!r}",
                )
                raise
        elif checkpoint["phase"] == "google" and run_google:
            _append_log(job_id, "Aucun nouveau domaine à rechercher sur Google.")
        elif checkpoint["phase"] == "google":
            _append_log(job_id, "Enrichissement Google ignoré.")

        _check_cancelled(cancel_event)
        checkpoint["phase"] = "done"
        _store_checkpoint(job_id, checkpoint)
        row_count = len(pd.read_excel(output_path, engine="openpyxl"))
        _set_job(
            job_id,
            status="completed",
            stage="Fichier prêt",
            progress=100,
            row_count=row_count,
            output_path=str(output_path),
            download_url=f"/api/jobs/{job_id}/download",
            _download_name=output_filename,
        )
        _append_log(job_id, f"Traitement terminé : {row_count} domaines dans {output_filename}.")
    except Exception as exc:
        if isinstance(exc, JobCancelled) or cancel_event.is_set():
            if checkpoint["phase"] == "scrape" and checkpoint["collected"]:
                save_to_excel(checkpoint["collected"], str(output_path), tld=tld)
            _finish_cancelled_job(job_id)
            return
        _set_job(
            job_id,
            status="failed",
            stage="Traitement interrompu",
            error=f"{type(exc).__name__}: {exc}",
        )
        _append_log(job_id, f"Erreur ({type(exc).__name__}) : {exc!r}")
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def _run_uploaded_workbook(job_id, cancel_event):
    job = jobs[job_id]
    output_path = Path(job["_output_path"])
    analysis = job["_upload_analysis"]

    try:
        _check_cancelled(cancel_event)
        _set_job(job_id, status="running")
        frame = pd.read_excel(output_path, engine="openpyxl")
        if analysis == "contacts":
            website_column = "Website URL" if "Website URL" in frame.columns else "Website"
            websites = frame[website_column].dropna().astype(str).str.strip()
            websites = list(dict.fromkeys(value for value in websites if value))
            if not websites:
                raise ValueError("Le classeur ne contient aucun lien dans « Website URL » ou « Website ».")
            _append_log(job_id, f"Classeur chargé : {len(websites)} site(s) à enrichir.")
        else:
            domain_column = "Domain" if "Domain" in frame.columns else "Domaine .net"
            domains = frame[domain_column].dropna().astype(str).str.strip()
            domains = list(dict.fromkeys(value for value in domains if value))
            if not domains:
                raise ValueError("Le classeur ne contient aucun domaine à analyser.")
            _append_log(job_id, f"Classeur chargé : {len(domains)} domaine(s) détecté(s).")

        if analysis == "dns":
            _set_stage(job_id, "Vérification DNS et HTTP", 15, "Lancement de la vérification DNS et HTTP…")
            if not bulk_check_domains(
                str(output_path),
                auto_close=True,
                cancel_check=lambda: _check_cancelled(cancel_event),
            ):
                raise RuntimeError("SEO Web Checker n’a retourné aucun résultat.")
        elif analysis == "google":
            _set_stage(job_id, "Enrichissement Google et Maps", 15, "Lancement de la recherche Google et Maps…")
            enrich_with_google_data(
                str(output_path),
                domains=domains,
                progress_callback=lambda message: _append_log(job_id, message),
                cancel_check=lambda: _check_cancelled(cancel_event),
            )
        else:
            contact_columns = [
                "Website",
                "Emails",
                "Instagram URLs",
                "LinkedIn URLs",
                "Facebook URLs",
                "X URLs",
                "Email Source URLs",
                "Instagram Source URLs",
                "LinkedIn Source URLs",
                "Facebook Source URLs",
                "X Source URLs",
                "Email Status",
                "Email Format Status",
                "Social Status",
                "Social Association Status",
                "Cookie Notice (public)",
                "Cookie Policy URL",
                "Cookie Policy Notes (public)",
                "Pages Scanned",
                "Pages Visited",
                "Pages Skipped",
                "Skipped Page URLs",
                "Pages Failed",
                "Failed Page URLs",
                "Discovered At UTC",
                "Scrape Status",
            ]
            for column in contact_columns:
                if column == "Pages Scanned":
                    if column in frame.columns:
                        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
                    else:
                        frame[column] = pd.Series(pd.NA, index=frame.index, dtype="Int64")
                elif column in frame.columns:
                    frame[column] = frame[column].astype(object)
                else:
                    frame[column] = pd.Series(index=frame.index, dtype=object)
            website_values = frame[website_column].fillna("").astype(str).str.strip()
            unique_websites = list(dict.fromkeys(value for value in website_values if value))
            partial_path = output_path.with_name(f"{output_path.stem}.writing.xlsx")
            completed_sites = 0
            try:
                for website in unique_websites:
                    _check_cancelled(cancel_event)
                    result = scrape_website_contacts(
                        website,
                        cancel_check=lambda: _check_cancelled(cancel_event),
                    )
                    matching_rows = website_values.eq(website)
                    result["Website"] = website
                    result["Discovered At UTC"] = pd.Timestamp.now(tz="UTC").isoformat()
                    for column in contact_columns:
                        frame.loc[matching_rows, column] = result[column]
                    completed_sites += 1
                    frame.to_excel(partial_path, index=False, engine="openpyxl")
                    os.replace(partial_path, output_path)
                    progress = 15 + round(completed_sites / len(unique_websites) * 80)
                    _set_stage(
                        job_id,
                        f"Enrichissement des sites · {completed_sites}/{len(unique_websites)}",
                        progress,
                        f"{website} : {result['Scrape Status']}, "
                        f"{len(result['Emails'].split('; ')) if result['Emails'] else 0} email(s), "
                        f"{result['Pages Scanned']} page(s) consultée(s), "
                        f"{result['Pages Failed']} échec(s).",
                    )
                    _set_job(job_id, row_count=completed_sites, result_unit="site")
                    time.sleep(0.25)
            finally:
                partial_path.unlink(missing_ok=True)

        _check_cancelled(cancel_event)
        row_count = len(pd.read_excel(output_path, engine="openpyxl"))
        _set_job(
            job_id,
            status="completed",
            stage="Fichier prêt",
            progress=100,
            row_count=completed_sites if analysis == "contacts" else row_count,
            result_unit="site" if analysis == "contacts" else "domaine",
            output_path=str(output_path),
            download_url=f"/api/jobs/{job_id}/download",
        )
        _append_log(job_id, f"Analyse terminée : {row_count} ligne(s) dans le classeur.")
    except Exception as exc:
        if isinstance(exc, JobCancelled) or cancel_event.is_set():
            partial_path = output_path.with_name(f"{output_path.stem}.writing.xlsx")
            partial_path.unlink(missing_ok=True)
            _set_job(
                job_id,
                status="cancelled",
                stage="Analyse du classeur annulée",
                error=None,
                output_path=str(output_path) if output_path.is_file() else None,
                download_url=f"/api/jobs/{job_id}/download" if output_path.is_file() else None,
            )
            _append_log(job_id, "Analyse annulée ; le classeur déjà sauvegardé reste disponible.")
            return
        _set_job(
            job_id,
            status="failed",
            stage="Analyse du classeur interrompue",
            error=f"{type(exc).__name__}: {exc}",
            output_path=str(output_path) if output_path.is_file() else None,
            download_url=f"/api/jobs/{job_id}/download" if output_path.is_file() else None,
        )
        _append_log(job_id, f"Erreur ({type(exc).__name__}) : {exc!r}")


def _submit_uploaded_workbook(job_id):
    job = jobs[job_id]
    executor.submit(_run_uploaded_workbook, job_id, job["_cancel_event"])


def _normalize_search_domain(value):
    value = str(value or "").strip()
    if not value:
        raise ValueError("Entrez un domaine ou des mots-clés, par exemple « seo services ottawa ».")
    if len(value) > 200 or any(ord(character) < 32 for character in value):
        raise ValueError("La recherche doit contenir au maximum 200 caractères.")
    if "://" in value:
        try:
            parsed = urlparse(value)
        except ValueError as exc:
            raise ValueError("Entrez un domaine valide ou des mots-clés de recherche.") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Entrez un domaine valide ou des mots-clés de recherche.")
        return parsed.hostname.lower().removeprefix("www.")
    return " ".join(value.split())


def _run_website_scrape(job_id, domain, pages, output_path, cancel_event):
    columns = ["Domain", "Google Maps Page", "Website URL"]
    partial_path = output_path.with_name(f"{output_path.stem}.writing.xlsx")
    rows = []
    seen_urls = set()

    def save_results():
        frame = pd.DataFrame(rows, columns=columns)
        try:
            frame.to_excel(partial_path, index=False, engine="openpyxl")
            os.replace(partial_path, output_path)
        finally:
            partial_path.unlink(missing_ok=True)

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            existing = pd.read_excel(output_path, engine="openpyxl")
            rows.extend(existing[columns].to_dict("records"))
            seen_urls.update(str(row["Website URL"]) for row in rows)
        else:
            save_results()

        _check_cancelled(cancel_event)
        _set_job(job_id, status="running")
        _set_stage(job_id, "Démarrage de Chrome", 5, "Initialisation de Chrome pour Google Maps…")
        completed_pages = 0

        def save_result(result):
            url = result["Website URL"]
            if url in seen_urls:
                return
            rows.append({"Domain": domain, **result})
            save_results()
            seen_urls.add(url)
            _set_job(job_id, row_count=len(rows))

        def report_progress(message):
            nonlocal completed_pages
            if not message.startswith("Page Google Maps "):
                _append_log(job_id, message)
                return
            completed_pages += 1
            progress = (
                min(90, 10 + completed_pages)
                if pages is None
                else min(90, 10 + round(completed_pages / pages * 80))
            )
            page_limit = "toutes" if pages is None else str(pages)
            _set_stage(
                job_id,
                f"Scraping Google Maps · page {completed_pages}/{page_limit}",
                progress,
                message,
            )

        page_limit = "toutes les pages disponibles" if pages is None else f"{pages} page(s) maximum"
        _append_log(job_id, f"Recherche Google « {domain} » sur {page_limit}.")
        scrape_google_website_links(
            domain,
            pages,
            progress_callback=report_progress,
            cancel_check=lambda: _check_cancelled(cancel_event),
            result_callback=save_result,
        )
        _check_cancelled(cancel_event)
        _set_job(
            job_id,
            status="completed",
            stage="Fichier prêt",
            progress=100,
            row_count=len(rows),
            result_unit="lien",
            output_path=str(output_path),
            download_url=f"/api/jobs/{job_id}/download",
        )
        _append_log(job_id, f"Scraping terminé : {len(rows)} lien(s) enregistré(s) dans le fichier Excel.")
    except Exception as exc:
        if isinstance(exc, JobCancelled) or cancel_event.is_set():
            _set_job(
                job_id,
                status="cancelled",
                stage="Scraping annulé",
                error=None,
                row_count=len(rows),
                output_path=str(output_path) if output_path.is_file() else None,
                download_url=f"/api/jobs/{job_id}/download" if output_path.is_file() else None,
            )
            _append_log(job_id, "Scraping des liens Google Maps annulé ; les résultats enregistrés restent disponibles.")
            return
        _set_job(
            job_id,
            status="failed",
            stage="Scraping interrompu",
            error=f"{type(exc).__name__}: {exc}",
            row_count=len(rows),
            output_path=str(output_path) if output_path.is_file() else None,
            download_url=f"/api/jobs/{job_id}/download" if output_path.is_file() else None,
        )
        _append_log(job_id, f"Erreur ({type(exc).__name__}) : {exc!r}")


@app.post("/api/upload-jobs")
def create_upload_job():
    uploaded_file = request.files.get("workbook")
    analysis = request.form.get("analysis")
    if analysis not in {"dns", "google", "contacts"}:
        return jsonify(error="Choisissez une analyse DNS/HTTP, Google/Maps ou contacts."), 400
    if uploaded_file is None or not uploaded_file.filename:
        return jsonify(error="Sélectionnez un classeur Excel à analyser."), 400

    safe_name = secure_filename(uploaded_file.filename)
    if Path(safe_name).suffix.lower() != ".xlsx":
        return jsonify(error="Le fichier doit être au format .xlsx."), 400

    job_id = uuid.uuid4().hex
    job_directory = Path(tempfile.mkdtemp(prefix=f"geo-domain-{job_id}-"))
    output_path = job_directory / "workbook.xlsx"
    try:
        uploaded_file.save(output_path)
        frame = pd.read_excel(output_path, engine="openpyxl")
        if analysis == "contacts":
            website_column = "Website URL" if "Website URL" in frame.columns else "Website"
            if website_column not in frame.columns:
                raise ValueError("Le classeur doit contenir une colonne « Website URL » ou « Website ».")
            websites = frame[website_column].dropna().astype(str).str.strip()
            if not websites.map(bool).any():
                raise ValueError("Le classeur ne contient aucun lien de site web.")
        else:
            if "Domain" not in frame.columns and "Domaine .net" not in frame.columns:
                raise ValueError("Le classeur doit contenir une colonne « Domain » ou « Domaine .net ».")
            if "Domain" not in frame.columns:
                frame["Domain"] = frame["Domaine .net"]
            elif "Domaine .net" in frame.columns:
                missing_domain = frame["Domain"].isna() | frame["Domain"].astype(str).str.strip().eq("")
                frame.loc[missing_domain, "Domain"] = frame.loc[missing_domain, "Domaine .net"]
            domains = frame["Domain"].dropna().astype(str).str.strip()
            if not domains.map(bool).any():
                raise ValueError("Le classeur ne contient aucun domaine à analyser.")
        frame.to_excel(output_path, index=False, engine="openpyxl")
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        job_directory.rmdir()
        return jsonify(error=f"Classeur Excel invalide : {exc}"), 400

    stem = Path(safe_name).stem or "domaines"
    with jobs_lock:
        if any(job["status"] in {"queued", "running", "cancelling"} for job in jobs.values()):
            output_path.unlink(missing_ok=True)
            job_directory.rmdir()
            return jsonify(error="Un traitement est déjà en cours. Attendez sa fin avant d’en lancer un autre."), 409

        jobs[job_id] = {
            "id": job_id,
            "status": "queued",
            "stage": "Dans la file d’attente",
            "progress": 0,
            "logs": [f"Classeur « {safe_name} » ajouté à la file d’attente."],
            "row_count": 0,
            "error": None,
            "download_url": None,
            "_job_type": "upload",
            "_output_path": str(output_path),
            "_download_name": f"{stem}_{'contacts' if analysis == 'contacts' else 'analyse'}.xlsx",
            "_upload_analysis": analysis,
            "_cancel_event": threading.Event(),
        }

    _submit_uploaded_workbook(job_id)
    return jsonify(id=job_id, status_url=f"/api/jobs/{job_id}"), 202


@app.post("/api/website-scrape-jobs")
def create_website_scrape_job():
    payload = request.get_json(silent=True) or {}
    try:
        domain = _normalize_search_domain(payload.get("domain"))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    all_pages = payload.get("all_pages") is True
    pages = payload.get("pages")
    if all_pages:
        pages = None
    elif isinstance(pages, bool) or not isinstance(pages, int) or not 1 <= pages <= 10:
        return jsonify(error="Choisissez un nombre de pages compris entre 1 et 10."), 400

    job_id = uuid.uuid4().hex
    safe_domain = re.sub(r"[^a-z0-9.-]+", "-", domain.lower()).strip(".-") or "google-maps"
    with jobs_lock:
        if any(job["status"] in {"queued", "running", "cancelling"} for job in jobs.values()):
            return jsonify(error="Un traitement est déjà en cours. Attendez sa fin avant d’en lancer un autre."), 409

        job_directory = Path(tempfile.mkdtemp(prefix=f"google-links-{job_id}-"))
        output_path = job_directory / f"{safe_domain}_website_links.xlsx"
        jobs[job_id] = {
            "id": job_id,
            "status": "queued",
            "stage": "Dans la file d’attente",
            "progress": 0,
            "logs": [f"Scraping des liens Website pour {domain} ajouté à la file d’attente."],
            "row_count": 0,
            "result_unit": "lien",
            "error": None,
            "download_url": None,
            "output_path": None,
            "_output_path": str(output_path),
            "_download_name": output_path.name,
            "_job_type": "website_scrape",
            "_website_domain": domain,
            "_website_pages": pages,
            "_cancel_event": threading.Event(),
        }

    executor.submit(
        _run_website_scrape,
        job_id,
        domain,
        pages,
        output_path,
        jobs[job_id]["_cancel_event"],
    )
    return jsonify(id=job_id, status_url=f"/api/jobs/{job_id}"), 202


@app.post("/api/jobs")
def create_job():
    payload = request.get_json(silent=True) or request.form
    country = str(payload.get("country", "us")).lower()
    if country not in COUNTRY_CITY_FILES:
        return jsonify(error="Choisissez un pays valide."), 400
    city_mode = str(payload.get("city_mode", "manual"))
    if payload.get("scan_all_cities") is True or city_mode == "all":
        cities = _all_cities(country)
        if not cities:
            return jsonify(error="Aucune ville disponible pour le pays sélectionné."), 400
    elif city_mode == "range":
        available_cities = _all_cities(country)
        try:
            start = int(payload.get("city_start", ""))
            end = int(payload.get("city_end", ""))
        except (TypeError, ValueError):
            return jsonify(error="Indiquez les positions de début et de fin de l’intervalle."), 400

        if start < 1 or end < start or end > len(available_cities):
            return jsonify(error=f"L’intervalle doit être compris entre 1 et {len(available_cities)}."), 400
        cities = available_cities[start - 1:end]
    elif city_mode == "manual":
        cities_text = str(payload.get("cities", ""))
        cities = list(dict.fromkeys(line.strip() for line in cities_text.splitlines() if line.strip()))
    else:
        return jsonify(error="Choisissez un mode de sélection des villes valide."), 400

    if not cities:
        return jsonify(error="Entrez au moins une ville."), 400
    try:
        tld = normalize_tld(payload.get("tld", ".net"))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if not EXPIREDDOMAINS_USERNAME or not EXPIREDDOMAINS_PASSWORD:
        return jsonify(
            error="Configurez EXPIREDDOMAINS_USERNAME et EXPIREDDOMAINS_PASSWORD dans le fichier .env."
        ), 400

    run_dns = payload.get("run_dns") is True
    run_google = payload.get("run_google") is True
    with jobs_lock:
        if any(job["status"] in {"queued", "running", "cancelling"} for job in jobs.values()):
            return jsonify(error="Un traitement est déjà en cours. Attendez sa fin avant d’en lancer un autre."), 409

        job_id = uuid.uuid4().hex
        output_filename = _output_filename_for_country_tld(country, tld)
        jobs[job_id] = {
            "id": job_id,
            "status": "queued",
            "stage": "Dans la file d’attente",
            "progress": 0,
            "logs": ["Traitement ajouté à la file d’attente."],
            "row_count": 0,
            "error": None,
            "download_url": None,
            "_cities": cities,
            "_country": country,
            "_tld": tld,
            "_output_path": str(PROJECT_ROOT / output_filename),
            "_download_name": output_filename,
            "_run_dns": run_dns,
            "_run_google": run_google,
            "_cancel_event": threading.Event(),
            "_checkpoint": _new_checkpoint(cities),
        }
        cancel_event = jobs[job_id]["_cancel_event"]

    executor.submit(
        _run_pipeline,
        job_id,
        cities,
        EXPIREDDOMAINS_USERNAME,
        EXPIREDDOMAINS_PASSWORD,
        GMAIL_ADDRESS,
        GMAIL_APP_PASSWORD,
        run_dns,
        run_google,
        cancel_event,
        tld,
        country,
    )
    return jsonify(id=job_id, status_url=f"/api/jobs/{job_id}"), 202


@app.post("/api/jobs/<job_id>/cancel")
def cancel_job(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            abort(404)
        if job["status"] == "failed":
            job.update(
                status="cancelled",
                stage="Traitement annulé",
                error=None,
                download_url=None,
            )
            job["logs"].append("Traitement clôturé par l’utilisateur après l’échec.")
            job["logs"] = job["logs"][-60:]
            return jsonify(id=job_id, status="cancelled"), 202
        if job["status"] not in {"queued", "running"}:
            return jsonify(error="Ce traitement n’est pas en cours."), 409
        cancel_event = job["_cancel_event"]
        cancel_event.set()
        job.update(status="cancelling", stage="Annulation en cours")
        job["logs"].append("Annulation demandée ; arrêt après l’étape navigateur en cours.")
        job["logs"] = job["logs"][-60:]

    return jsonify(id=job_id, status="cancelling"), 202


@app.post("/api/jobs/<job_id>/retry")
@app.post("/api/jobs/<job_id>/resume")
def retry_job(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            abort(404)
        if job["status"] != "failed":
            return jsonify(error="Seul un traitement en erreur peut être relancé."), 409
        if any(other["status"] in {"queued", "running", "cancelling"} for other in jobs.values()):
            return jsonify(error="Un autre traitement est déjà en cours."), 409

        is_upload = job.get("_job_type") == "upload"
        is_website_scrape = job.get("_job_type") == "website_scrape"
        cities = job.get("_cities", [])
        website_domain = job.get("_website_domain")
        website_pages = job.get("_website_pages")
        run_dns = job.get("_run_dns", False)
        run_google = job.get("_run_google", False)
        tld = job.get("_tld", ".net")
        country = job.get("_country", "us")
        cancel_event = job["_cancel_event"]
        cancel_event.clear()
        job.update(
            status="queued",
            stage="Dans la file d’attente",
            progress=0,
            error=None,
            download_url=None,
            output_path=None,
            row_count=0,
        )
        if not is_upload and not is_website_scrape:
            checkpoint = job["_checkpoint"]
            job["logs"].append(
                f"Reprise demandée à la dernière étape acquise : {checkpoint['phase']}."
            )
        elif is_website_scrape:
            job["logs"].append("Nouvelle tentative du scraping des liens Google Maps.")
        else:
            job["logs"].append("Nouvelle tentative de l’analyse du classeur.")
        job["logs"] = job["logs"][-60:]

    if is_upload:
        _submit_uploaded_workbook(job_id)
        return jsonify(id=job_id, status_url=f"/api/jobs/{job_id}"), 202
    if is_website_scrape:
        executor.submit(
            _run_website_scrape,
            job_id,
            website_domain,
            website_pages,
            Path(job["_output_path"]),
            cancel_event,
        )
        return jsonify(id=job_id, status_url=f"/api/jobs/{job_id}"), 202
    executor.submit(
        _run_pipeline,
        job_id,
        cities,
        EXPIREDDOMAINS_USERNAME,
        EXPIREDDOMAINS_PASSWORD,
        GMAIL_ADDRESS,
        GMAIL_APP_PASSWORD,
        run_dns,
        run_google,
        cancel_event,
        tld,
        country,
    )
    return jsonify(id=job_id, status_url=f"/api/jobs/{job_id}"), 202


@app.post("/api/jobs/<job_id>/restart")
def restart_job(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            abort(404)
        if job["status"] != "failed":
            return jsonify(error="Seul un traitement en erreur peut redémarrer."), 409
        if any(other["status"] in {"queued", "running", "cancelling"} for other in jobs.values()):
            return jsonify(error="Un autre traitement est déjà en cours."), 409

        is_upload = job.get("_job_type") == "upload"
        is_website_scrape = job.get("_job_type") == "website_scrape"
        cities = list(job.get("_cities", []))
        website_domain = job.get("_website_domain")
        website_pages = job.get("_website_pages")
        run_dns = job.get("_run_dns", False)
        run_google = job.get("_run_google", False)
        retry_domains = list(job.get("_checkpoint", {}).get("new_domains", []))
        tld = job.get("_tld", ".net")
        country = job.get("_country", "us")
        cancel_event = job["_cancel_event"]
        cancel_event.clear()
        if is_upload:
            job.update(
                status="queued",
                stage="Relancement de l’analyse du classeur",
                progress=0,
                error=None,
                download_url=None,
                output_path=None,
                row_count=0,
            )
            job["logs"].append("Nouvelle tentative de l’analyse du classeur.")
            job["logs"] = job["logs"][-60:]
        elif is_website_scrape:
            job.update(
                status="queued",
                stage="Relancement du scraping Google Maps",
                progress=0,
                error=None,
                download_url=None,
                output_path=None,
                row_count=0,
            )
            job["logs"].append("Redémarrage du scraping des liens Google Maps demandé.")
            job["logs"] = job["logs"][-60:]
        else:
            job.update(
                status="queued",
                stage="Redémarrage depuis le début",
                progress=0,
                error=None,
                download_url=None,
                output_path=None,
                row_count=0,
                _checkpoint={
                    **_new_checkpoint(cities),
                    "retry_domains": retry_domains,
                },
            )
        job["logs"].append(
            "Redémarrage de l’analyse du classeur demandé."
            if is_upload
            else (
                "Redémarrage du scraping des liens Google Maps demandé."
                if is_website_scrape
                else "Redémarrage depuis le début demandé. Le classeur existant n’est pas supprimé."
            )
        )
        job["logs"] = job["logs"][-60:]

    if is_upload:
        _submit_uploaded_workbook(job_id)
        return jsonify(id=job_id, status_url=f"/api/jobs/{job_id}"), 202
    if is_website_scrape:
        executor.submit(
            _run_website_scrape,
            job_id,
            website_domain,
            website_pages,
            Path(job["_output_path"]),
            cancel_event,
        )
        return jsonify(id=job_id, status_url=f"/api/jobs/{job_id}"), 202
    executor.submit(
        _run_pipeline,
        job_id,
        cities,
        EXPIREDDOMAINS_USERNAME,
        EXPIREDDOMAINS_PASSWORD,
        GMAIL_ADDRESS,
        GMAIL_APP_PASSWORD,
        run_dns,
        run_google,
        cancel_event,
        tld,
        country,
    )
    return jsonify(id=job_id, status_url=f"/api/jobs/{job_id}"), 202


@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            abort(404)
        public_job = {
            key: value
            for key, value in job.items()
            if not key.startswith("_") and key != "output_path"
        }
    return jsonify(public_job)


@app.get("/api/jobs/<job_id>/download")
def download_job(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job or (
            job["status"] != "completed"
            and not (
                job["status"] in {"failed", "cancelled"}
                and job.get("download_url")
            )
        ):
            abort(404)
        output_path = Path(job.get("output_path", ""))
        download_name = job.get("_download_name", OUTPUT_FILENAME)

    if not output_path.is_file():
        abort(404)
    return send_file(
        output_path,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    print("Fast Domain Name disponible sur http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=True, threaded=True)