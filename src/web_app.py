from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import random
import shutil
import tempfile
import threading
import time
import uuid

import pandas as pd
from flask import Flask, abort, jsonify, render_template, request, send_file
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

from scrap_from_E_D.E_D import (
    init_driver as init_expired_domains_driver,
    login,
    save_to_excel,
    scrape_city,
    setup_filters,
)
from scrap_from_Google.Google import enrich_with_google_data
from seowebchecker_bulk_domain_check import bulk_check_domains


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CITY_FILE = PROJECT_ROOT / "src" / "citys" / "us_cities_sample.xlsx"
OUTPUT_FILENAME = "expired_domains_TLD_net.xlsx"
MAX_CITIES = 50

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
LOCAL_ONLY = os.getenv("APP_LOCAL_ONLY", "true").lower() == "true"
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"
if os.getenv("TRUST_PROXY_HEADERS", "false").lower() == "true":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri="memory://")
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="domain-search")
jobs = {}
jobs_lock = threading.Lock()
JOB_TTL_SECONDS = 60 * 60


def _sample_cities(limit=10):
    try:
        frame = pd.read_excel(CITY_FILE, engine="openpyxl")
        column = "Ville" if "Ville" in frame.columns else frame.columns[0]
        return frame[column].dropna().astype(str).head(limit).tolist()
    except (FileNotFoundError, IndexError, ValueError):
        return []


@app.before_request
def restrict_to_local_machine():
    if LOCAL_ONLY and request.remote_addr not in {"127.0.0.1", "::1"}:
        abort(403)


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return render_template(
        "index.html",
        default_cities=_sample_cities(),
        demo_mode=DEMO_MODE,
        public_server=not LOCAL_ONLY,
    )


@app.get("/healthz")
def health_check():
    return jsonify(status="ok")


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


def _cleanup_expired_jobs():
    cutoff = time.time() - JOB_TTL_SECONDS
    expired_paths = []

    with jobs_lock:
        expired_ids = [
            job_id
            for job_id, job in jobs.items()
            if job["status"] not in {"queued", "running"}
            and job.get("created_at", cutoff) < cutoff
        ]
        for job_id in expired_ids:
            output_path = jobs[job_id].get("output_path")
            if output_path:
                expired_paths.append(Path(output_path).parent)
            del jobs[job_id]

    for path in expired_paths:
        shutil.rmtree(path, ignore_errors=True)


def _run_pipeline(job_id, cities, username, password, gmail_address, gmail_app_password, run_dns, run_google):
    driver = None
    job_dir = Path(tempfile.mkdtemp(prefix="fast_domain_name_"))
    output_path = job_dir / OUTPUT_FILENAME

    try:
        _set_job(job_id, status="running")
        if DEMO_MODE:
            _set_stage(job_id, "Création du classeur de démonstration", 45, "Génération de données fictives, sans requête externe…")
            sample_rows = [
                {
                    "City": cities[index % len(cities)],
                    "Domain": domain,
                    "Date Scraping from E_D": "DEMO",
                    "Domaine .net": domain,
                    "Status": "DEMO",
                    "HTTP Code": code,
                    "Resolved IP": ip,
                    "Note": "DONNÉES FICTIVES — aucun contrôle réel effectué.",
                    "Google Maps Pages": maps_pages,
                    "Sponsored Results": sponsored,
                }
                for index, (domain, code, ip, maps_pages, sponsored) in enumerate([
                    ("demo-plumbing.invalid", "200", "192.0.2.10", "3", "Oui"),
                    ("demo-bakery.invalid", "301", "192.0.2.11", "1", "Non"),
                    ("demo-repair.invalid", "—", "—", "0", "Non"),
                ])
            ]
            pd.DataFrame(sample_rows).to_excel(output_path, index=False, engine="openpyxl")
            _set_job(
                job_id,
                status="completed",
                stage="Fichier de démonstration prêt",
                progress=100,
                row_count=len(sample_rows),
                demo_mode=True,
                output_path=str(output_path),
                download_url=f"/api/jobs/{job_id}/download",
            )
            _append_log(job_id, "Simulation terminée. Les valeurs du fichier sont fictives.")
            return

        _set_stage(job_id, "Connexion à ExpiredDomains", 4, "Démarrage de Chrome pour ExpiredDomains…")
        driver, wait = init_expired_domains_driver(headless=True)
        login(
            driver,
            wait,
            username,
            password,
            gmail_address,
            gmail_app_password,
            allow_manual_code=False,
        )
        _set_stage(job_id, "Configuration des filtres", 12, "Compte connecté, configuration des filtres…")
        setup_filters(driver, wait)

        collected = []
        for index, city in enumerate(cities, start=1):
            progress = 16 + round((index - 1) / len(cities) * 42)
            _set_stage(
                job_id,
                f"Recherche {index}/{len(cities)} · {city}",
                progress,
                f"Recherche des domaines pour {city} ({index}/{len(cities)})…",
            )
            collected.extend(scrape_city(driver, wait, city))
            if index < len(cities):
                time.sleep(random.uniform(2, 4))

        driver.quit()
        driver = None

        if not collected:
            raise RuntimeError("Aucun domaine n’a été trouvé pour les villes sélectionnées.")

        save_to_excel(collected, str(output_path))
        if not output_path.is_file():
            raise RuntimeError("Le classeur Excel n’a pas pu être créé.")

        row_count = len(pd.read_excel(output_path, engine="openpyxl"))
        _set_job(job_id, row_count=row_count)
        _set_stage(job_id, "Vérification DNS et HTTP", 62, f"{row_count} domaines collectés.")

        if run_dns:
            try:
                if not bulk_check_domains(str(output_path), auto_close=True, headless=True):
                    _append_log(job_id, "SEO Web Checker n’a retourné aucune ligne ; le classeur collecté sera conservé.")
            except Exception as exc:
                _append_log(job_id, f"SEO Web Checker indisponible : {exc}")
        else:
            _append_log(job_id, "Vérification SEO Web Checker ignorée.")

        if run_google:
            _set_stage(job_id, "Enrichissement Google et Maps", 78, "Recherche des indicateurs Google…")
            try:
                enrich_with_google_data(str(output_path), headless=True)
            except Exception as exc:
                _append_log(job_id, f"Enrichissement Google interrompu : {exc}")
        else:
            _append_log(job_id, "Enrichissement Google ignoré.")

        row_count = len(pd.read_excel(output_path, engine="openpyxl"))
        _set_job(
            job_id,
            status="completed",
            stage="Fichier prêt",
            progress=100,
            row_count=row_count,
            output_path=str(output_path),
            download_url=f"/api/jobs/{job_id}/download",
        )
        _append_log(job_id, f"Traitement terminé : {row_count} domaines dans {OUTPUT_FILENAME}.")
    except Exception as exc:
        _set_job(job_id, status="failed", stage="Traitement interrompu", error=str(exc))
        _append_log(job_id, f"Erreur : {exc}")
        shutil.rmtree(job_dir, ignore_errors=True)
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


@app.post("/api/jobs")
@limiter.limit("5 per hour")
def create_job():
    _cleanup_expired_jobs()
    payload = request.get_json(silent=True) or request.form
    cities_text = str(payload.get("cities", ""))
    cities = list(dict.fromkeys(line.strip() for line in cities_text.splitlines() if line.strip()))
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))

    if not cities:
        return jsonify(error="Entrez au moins une ville."), 400
    if len(cities) > MAX_CITIES:
        return jsonify(error=f"La limite est de {MAX_CITIES} villes par traitement."), 400
    if not DEMO_MODE and (not username or not password):
        return jsonify(error="Le nom d’utilisateur et le mot de passe ExpiredDomains sont requis."), 400

    with jobs_lock:
        if any(job["status"] in {"queued", "running"} for job in jobs.values()):
            return jsonify(error="Un traitement est déjà en cours. Attendez sa fin avant d’en lancer un autre."), 409

        job_id = uuid.uuid4().hex
        jobs[job_id] = {
            "id": job_id,
            "created_at": time.time(),
            "status": "queued",
            "stage": "Dans la file d’attente",
            "progress": 0,
            "logs": ["Traitement ajouté à la file d’attente."],
            "row_count": 0,
            "error": None,
            "download_url": None,
            "demo_mode": DEMO_MODE,
        }

    executor.submit(
        _run_pipeline,
        job_id,
        cities,
        username,
        password,
        str(payload.get("gmail_address", "")).strip(),
        str(payload.get("gmail_app_password", "")),
        payload.get("run_dns") is True,
        payload.get("run_google") is True,
    )
    return jsonify(id=job_id, status_url=f"/api/jobs/{job_id}"), 202


@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    _cleanup_expired_jobs()
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            abort(404)
        public_job = {key: value for key, value in job.items() if key != "output_path"}
    return jsonify(public_job)


@app.get("/api/jobs/<job_id>/download")
def download_job(job_id):
    _cleanup_expired_jobs()
    with jobs_lock:
        job = jobs.get(job_id)
        if not job or job["status"] != "completed":
            abort(404)
        output_path = Path(job.get("output_path", ""))

    if not output_path.is_file():
        abort(404)
    return send_file(
        output_path,
        as_attachment=True,
        download_name=OUTPUT_FILENAME,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    print("Fast Domain Name disponible sur http://127.0.0.1:5000")
    app.run(host="127.0.0.1" if LOCAL_ONLY else "0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False, use_reloader=False, threaded=True)