const form = document.querySelector("#search-form");
const submitButton = document.querySelector("#submit-button");
const formError = document.querySelector("#form-error");
const cityInput = document.querySelector("#cities");
const cityCount = document.querySelector("#city-count");
const manualCityFields = document.querySelector("#manual-city-fields");
const rangeCityFields = document.querySelector("#city-range-fields");
const cityStart = document.querySelector("#city-start");
const cityEnd = document.querySelector("#city-end");
const cityRangeCount = document.querySelector("#city-range-count");
const countrySelect = document.querySelector("#country");
const countryCityCount = document.querySelector("#country-city-count");
const rangeCityTotal = rangeCityFields.querySelector(".field-meta span:last-child");
const targetTld = document.querySelector("#target-tld");
const tldRecommendations = [...document.querySelectorAll(".tld-recommendations input[type='checkbox']")];
const scanAllCities = document.querySelector("#scan-all-cities");
const citySelectionOptions = document.querySelector("#city-selection-options");
const cityWorkflow = document.querySelector("#city-workflow");
const uploadWorkflow = document.querySelector("#upload-workflow");
const workbookFile = document.querySelector("#workbook-file");
const workbookFileName = document.querySelector("#workbook-file-name");
const statusTitle = document.querySelector("#status-title");
const statusDescription = document.querySelector("#status-description");
const retryButton = document.querySelector("#retry-button");
const cancelButton = document.querySelector("#cancel-button");
const restartButton = document.querySelector("#restart-button");
const progressFill = document.querySelector("#progress-fill");
const progressTrack = document.querySelector(".progress-track");
const progressValue = document.querySelector("#progress-value");
const activityState = document.querySelector("#activity-state");
const activityLog = document.querySelector("#activity-log");
const downloadBlock = document.querySelector("#download-block");
const downloadLink = document.querySelector("#download-link");
const resultCount = document.querySelector("#result-count");

let polling = false;
let loadedCountry = countrySelect.value;

function countCities() {
  const cities = cityInput.value.split(/\r?\n/).map((city) => city.trim()).filter(Boolean);
  const uniqueCities = new Set(cities.map((city) => city.toLocaleLowerCase("fr")));
  cityCount.textContent = `${uniqueCities.size} ${uniqueCities.size > 1 ? "villes" : "ville"}`;
}

function updateCityMode() {
  const allCities = scanAllCities.checked;
  const uploadMode = form.querySelector('input[name="workflow_mode"]:checked').value === "upload";
  citySelectionOptions.hidden = allCities;
  const mode = form.querySelector('input[name="city_mode"]:checked').value;
  const manual = mode === "manual" && !allCities;
  manualCityFields.hidden = !manual;
  rangeCityFields.hidden = !allCities && mode === "manual";
  cityInput.required = !uploadMode && manual;
  cityStart.required = !uploadMode && !allCities && mode === "range";
  cityEnd.required = !uploadMode && !allCities && mode === "range";
  updateRangeCount();
}

function updateWorkflowMode() {
  const uploadMode = form.querySelector('input[name="workflow_mode"]:checked').value === "upload";
  cityWorkflow.hidden = uploadMode;
  uploadWorkflow.hidden = !uploadMode;
  updateCityMode();
  submitButton.querySelector(".button-label").textContent = uploadMode
    ? "Analyser le classeur"
    : "Lancer la recherche";
}

function updateRangeCount() {
  const start = Number(cityStart.value);
  const end = Number(cityEnd.value);
  const count = end - start + 1;
  cityRangeCount.textContent = Number.isInteger(start) && Number.isInteger(end) && start > 0 && count > 0
    ? `${count} ${count > 1 ? "villes sélectionnées" : "ville sélectionnée"}`
    : "Vérifiez les positions de l’intervalle.";
}

async function loadCountryCities() {
  const previousLabel = countryCityCount.textContent;
  countrySelect.disabled = true;
  countryCityCount.textContent = "Chargement des villes…";

  try {
    const response = await fetch(`/api/cities?country=${encodeURIComponent(countrySelect.value)}`, {
      cache: "no-store",
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Impossible de charger les villes de ce pays.");

    const cities = result.cities;
    cityInput.value = cities.slice(0, 10).join("\n");
    cityEnd.max = String(result.total);
    cityEnd.value = String(Math.min(10, result.total));
    cityStart.max = String(result.total);
    cityStart.value = "1";
    cityCount.textContent = `${Math.min(10, result.total)} villes`;
    countryCityCount.textContent = `${result.total} villes disponibles`;
    rangeCityTotal.textContent = `${result.total} villes disponibles`;
    loadedCountry = countrySelect.value;
    countCities();
    updateCityMode();
    formError.hidden = true;
  } catch (error) {
    countrySelect.value = loadedCountry;
    countryCityCount.textContent = previousLabel;
    showError(error.message);
  } finally {
    countrySelect.disabled = false;
  }
}

function showError(message) {
  formError.textContent = message;
  formError.hidden = false;
}

function renderJob(job) {
  statusTitle.textContent = job.stage;
  statusDescription.textContent = job.status === "failed"
    ? (job.error || "Le traitement n’a pas pu aboutir.")
    : job.status === "cancelled"
      ? "Le traitement a été annulé. Les résultats déjà collectés restent enregistrés."
      : job.status === "cancelling"
        ? "Annulation demandée ; l’étape navigateur en cours peut devoir se terminer."
    : job.status === "completed"
      ? "Le classeur est prêt à être téléchargé sur cet ordinateur."
      : "Le traitement continue en arrière-plan sur cet ordinateur.";

  const progress = Math.max(0, Math.min(100, Number(job.progress) || 0));
  progressFill.style.width = `${progress}%`;
  progressTrack.setAttribute("aria-valuenow", String(progress));
  progressValue.textContent = `${progress}%`;
  activityState.textContent = job.status === "completed"
    ? "TERMINÉ"
    : job.status === "failed"
      ? "À VÉRIFIER"
      : job.status === "cancelled"
        ? "ANNULÉ"
        : job.status === "cancelling"
          ? "ANNULATION"
      : "EN COURS";

  activityLog.replaceChildren();
  for (const message of job.logs || []) {
    const item = document.createElement("li");
    item.textContent = message;
    activityLog.append(item);
  }
  if (!job.logs?.length) {
    const item = document.createElement("li");
    item.className = "log-muted";
    item.textContent = "En attente des premières étapes…";
    activityLog.append(item);
  }

  if (job.status === "completed" && job.download_url) {
    downloadLink.href = job.download_url;
    resultCount.textContent = `${job.row_count} ${job.row_count > 1 ? "domaines" : "domaine"}`;
    downloadBlock.hidden = false;
  }
  retryButton.hidden = job.status !== "failed";
  retryButton.disabled = false;
  retryButton.textContent = "Reprendre à la dernière étape acquise";
  restartButton.hidden = job.status !== "failed";
  restartButton.disabled = false;
  cancelButton.hidden = !["queued", "running", "cancelling", "failed"].includes(job.status);
  cancelButton.disabled = job.status === "cancelling";
  cancelButton.textContent = job.status === "cancelling"
    ? "Annulation en cours…"
    : job.status === "failed"
      ? "Annuler le processus"
      : "Annuler le traitement";

  const finished = ["completed", "failed", "cancelled"].includes(job.status);
  submitButton.disabled = !finished;
  submitButton.querySelector("span:first-child").textContent = finished ? "Lancer une autre recherche" : "Traitement en cours…";
  if (finished) polling = false;
}

async function pollJob(statusUrl) {
  if (polling) return;
  polling = true;

  while (polling) {
    try {
      const response = await fetch(statusUrl, { cache: "no-store" });
      const job = await response.json();
      if (!response.ok) throw new Error(job.error || "Impossible de lire l’état du traitement.");
      renderJob(job);
      if (["completed", "failed", "cancelled"].includes(job.status)) break;
    } catch (error) {
      showError(error.message);
      submitButton.disabled = false;
      polling = false;
      break;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1400));
  }
}

retryButton.addEventListener("click", async () => {
  retryButton.disabled = true;
  retryButton.textContent = "Relancement…";
  downloadBlock.hidden = true;
  statusTitle.textContent = "Nouvelle tentative";
  statusDescription.textContent = "Relancement de la même recherche…";

  try {
    const statusUrl = retryButton.dataset.statusUrl;
    const response = await fetch(`${statusUrl}/resume`, { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Impossible de relancer la recherche.");
    await pollJob(result.status_url);
  } catch (error) {
    showError(error.message);
    retryButton.disabled = false;
    retryButton.textContent = "Reprendre à la dernière étape acquise";
  }
});

restartButton.addEventListener("click", async () => {
  if (!window.confirm("Redémarrer la recherche depuis le début ? Le classeur existant ne sera pas supprimé.")) return;

  restartButton.disabled = true;
  restartButton.textContent = "Redémarrage…";
  downloadBlock.hidden = true;
  statusTitle.textContent = "Redémarrage depuis le début";
  statusDescription.textContent = "Les étapes précédentes vont être relancées ; les domaines existants ne seront pas dupliqués.";

  try {
    const statusUrl = retryButton.dataset.statusUrl;
    const response = await fetch(`${statusUrl}/restart`, { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Impossible de redémarrer la recherche.");
    await pollJob(result.status_url);
  } catch (error) {
    showError(error.message);
    restartButton.disabled = false;
    restartButton.textContent = "Redémarrer depuis le début";
  }
});

cancelButton.addEventListener("click", async () => {
  cancelButton.disabled = true;
  cancelButton.textContent = "Annulation en cours…";
  try {
    const statusUrl = retryButton.dataset.statusUrl;
    const response = await fetch(`${statusUrl}/cancel`, { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Impossible d’annuler le traitement.");
    if (result.status === "cancelled") {
      statusTitle.textContent = "Processus annulé";
      statusDescription.textContent = "Le processus en échec a été clôturé.";
      cancelButton.hidden = true;
    } else {
      statusTitle.textContent = "Annulation en cours";
      statusDescription.textContent = "Le navigateur termine son opération courante avant l’arrêt.";
    }
  } catch (error) {
    showError(error.message);
    cancelButton.disabled = false;
    cancelButton.textContent = "Annuler le processus";
  }
});

cityInput.addEventListener("input", countCities);
countrySelect.addEventListener("change", loadCountryCities);
form.querySelectorAll('input[name="city_mode"]').forEach((input) => input.addEventListener("change", updateCityMode));
form.querySelectorAll('input[name="workflow_mode"]').forEach((input) => input.addEventListener("change", updateWorkflowMode));
scanAllCities.addEventListener("change", updateCityMode);
cityStart.addEventListener("input", updateRangeCount);
cityEnd.addEventListener("input", updateRangeCount);
workbookFile.addEventListener("change", () => {
  workbookFileName.textContent = workbookFile.files[0]?.name || "Choisir un fichier Excel";
});
targetTld.addEventListener("input", () => {
  const value = targetTld.value.trim().toLowerCase();
  tldRecommendations.forEach((recommendation) => {
    recommendation.checked = recommendation.value === value;
  });
});
tldRecommendations.forEach((recommendation) => {
  recommendation.addEventListener("change", () => {
    if (recommendation.checked) {
      tldRecommendations.forEach((other) => {
        other.checked = other === recommendation;
      });
      targetTld.value = recommendation.value;
    } else if (targetTld.value.trim().toLowerCase() === recommendation.value) {
      targetTld.value = "";
    }
  });
});
countCities();
updateCityMode();
updateWorkflowMode();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.hidden = true;
  downloadBlock.hidden = true;

  const uploadMode = form.querySelector('input[name="workflow_mode"]:checked').value === "upload";
  if (uploadMode && !workbookFile.files.length) {
    showError("Sélectionnez un classeur Excel à analyser.");
    return;
  }
  const mode = form.querySelector('input[name="city_mode"]:checked').value;
  if (!uploadMode && !scanAllCities.checked) {
    if (mode === "manual") {
      const cities = cityInput.value.split(/\r?\n/).map((city) => city.trim()).filter(Boolean);
      if (!cities.length) {
        showError("Entrez au moins une ville, une par ligne.");
        return;
      }
      if (!uploadMode && !targetTld.value.trim()) {
        showError("Indiquez le TLD cible, par exemple .net ou .us.");
        targetTld.focus();
        return;
      }
    } else {
      const start = Number(cityStart.value);
      const end = Number(cityEnd.value);
      if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end < start || end > Number(cityEnd.max)) {
        showError(`Choisissez un intervalle valide entre 1 et ${cityEnd.max}.`);
        return;
      }
    }
  }

  const data = Object.fromEntries(new FormData(form));
  data.run_dns = document.querySelector("#run-dns").checked;
  data.run_google = document.querySelector("#run-google").checked;
  data.scan_all_cities = scanAllCities.checked;
  data.tld = targetTld.value.trim();
  const uploadData = new FormData();
  if (uploadMode) {
    uploadData.append("workbook", workbookFile.files[0]);
    uploadData.append("analysis", form.querySelector('input[name="upload_analysis"]:checked').value);
  }

  submitButton.disabled = true;
  submitButton.querySelector(".button-label").textContent = uploadMode ? "Importation…" : "Préparation…";
  statusTitle.textContent = "Demande envoyée";
  statusDescription.textContent = uploadMode
    ? "Importation du classeur et préparation de l’analyse…"
    : "Connexion au navigateur et préparation du traitement…";

  try {
    const response = await fetch(uploadMode ? "/api/upload-jobs" : "/api/jobs", uploadMode
      ? { method: "POST", body: uploadData }
      : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Impossible de démarrer le traitement.");
    retryButton.dataset.statusUrl = result.status_url;
    form.querySelectorAll("input, textarea, button").forEach((field) => { field.disabled = true; });
    await pollJob(result.status_url);
  } catch (error) {
    showError(error.message);
    submitButton.disabled = false;
    submitButton.querySelector(".button-label").textContent = uploadMode
      ? "Analyser le classeur"
      : "Lancer la recherche";
  } finally {
    form.querySelectorAll("input, textarea, button").forEach((field) => { field.disabled = false; });
  }
});