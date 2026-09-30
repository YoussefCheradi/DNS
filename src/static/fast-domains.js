const form = document.querySelector("#search-form");
const submitButton = document.querySelector("#submit-button");
const formError = document.querySelector("#form-error");
const cityInput = document.querySelector("#cities");
const cityCount = document.querySelector("#city-count");
const statusTitle = document.querySelector("#status-title");
const statusDescription = document.querySelector("#status-description");
const progressFill = document.querySelector("#progress-fill");
const progressTrack = document.querySelector(".progress-track");
const progressValue = document.querySelector("#progress-value");
const activityState = document.querySelector("#activity-state");
const activityLog = document.querySelector("#activity-log");
const downloadBlock = document.querySelector("#download-block");
const downloadLink = document.querySelector("#download-link");
const resultCount = document.querySelector("#result-count");

let polling = false;

function countCities() {
  const cities = cityInput.value.split(/\r?\n/).map((city) => city.trim()).filter(Boolean);
  const uniqueCities = new Set(cities.map((city) => city.toLocaleLowerCase("fr")));
  cityCount.textContent = `${uniqueCities.size} ${uniqueCities.size > 1 ? "villes" : "ville"}`;
}

function showError(message) {
  formError.textContent = message;
  formError.hidden = false;
}

function renderJob(job) {
  statusTitle.textContent = job.stage;
  statusDescription.textContent = job.status === "failed"
    ? (job.error || "Le traitement n’a pas pu aboutir.")
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

  const finished = job.status === "completed" || job.status === "failed";
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
      if (job.status === "completed" || job.status === "failed") break;
    } catch (error) {
      showError(error.message);
      submitButton.disabled = false;
      polling = false;
      break;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1400));
  }
}

cityInput.addEventListener("input", countCities);
countCities();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.hidden = true;
  downloadBlock.hidden = true;

  const cities = cityInput.value.split(/\r?\n/).map((city) => city.trim()).filter(Boolean);
  if (!cities.length || cities.length > 50) {
    showError("Entrez entre 1 et 50 villes, une par ligne.");
    return;
  }

  const data = Object.fromEntries(new FormData(form));
  data.run_dns = document.querySelector("#run-dns").checked;
  data.run_google = document.querySelector("#run-google").checked;

  submitButton.disabled = true;
  submitButton.querySelector("span:first-child").textContent = "Préparation…";
  statusTitle.textContent = "Demande envoyée";
  statusDescription.textContent = "Connexion au navigateur et préparation du traitement…";

  try {
    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Impossible de démarrer le traitement.");
    document.querySelector("#password").value = "";
    document.querySelector("#gmail-app-password").value = "";
    form.querySelectorAll("input, textarea, button").forEach((field) => { field.disabled = true; });
    await pollJob(result.status_url);
  } catch (error) {
    showError(error.message);
    submitButton.disabled = false;
    submitButton.querySelector("span:first-child").textContent = "Lancer la recherche";
  } finally {
    form.querySelectorAll("input, textarea, button").forEach((field) => { field.disabled = false; });
  }
});