# Fast Domain Name

Projet Python qui collecte des domaines expirés, vérifie leur statut DNS/HTTP, puis ajoute des indicateurs issus de Google et Google Maps dans un classeur Excel.

> **Application web :** le formulaire local exécute le pipeline de collecte, de vérification et d’enrichissement. `src/main.py` reste un ancien point d’entrée en ligne de commande et ne lance actuellement que l’enrichissement Google.

## Sommaire

- [Fonctionnement](#fonctionnement)
- [Structure](#structure)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Configuration](#configuration)
- [Utilisation](#utilisation)
- [Classeur Excel](#classeur-excel)
- [Dépannage](#dépannage)

## Fonctionnement

Le pipeline envisagé comporte trois étapes :

1. **ExpiredDomains** : se connecter à `expireddomains.net`, appliquer les filtres définis dans le script et collecter des domaines pour des villes américaines.
2. **SEO Web Checker** : envoyer les domaines au vérificateur en ligne pour obtenir le statut, le code HTTP, l’adresse IP résolue et une note.
3. **Google et Google Maps** : rechercher les domaines avec un navigateur Chrome et compléter le classeur avec `Sponsored Results` et `Google Maps Pages`.

L’application web peut lancer les trois étapes à la suite. Le point d’entrée historique `src/main.py`, lui, ne lance actuellement que l’étape 3. L’enrichissement Google traite les domaines quel que soit leur code HTTP. Les lignes déjà renseignées pour les deux champs Google sont ignorées. Le classeur est sauvegardé après chaque domaine traité.

## Structure

| Chemin | Rôle |
| --- | --- |
| `src/main.py` | Orchestrateur. Actuellement, seul l’enrichissement Google Selenium est actif. |
| `src/web_app.py` | Application web locale, tâches en arrière-plan, progression et téléchargement du classeur. |
| `src/templates/index.html` | Formulaire et panneau de suivi. |
| `src/static/` | Styles et logique d’interface web. |
| `requirements.txt` | Dépendances Python du projet et de l’application web. |
| `src/scrap_from_E_D/E_D.py` | Connexion à ExpiredDomains, configuration des filtres, pagination et sauvegarde Excel. |
| `src/seowebchecker_bulk_domain_check.py` | Vérification en lot sur SEO Web Checker et fusion des colonnes DNS dans le classeur principal. |
| `src/scrap_from_Google/Google.py` | Recherche Google/Google Maps avec Selenium et `undetected_chromedriver`. C’est l’implémentation appelée par `main.py`. |
| `src/scrap_from_Google/Google2.py` | Variante utilisant l’API Serper. Elle n’est pas appelée par `main.py`. |
| `src/citys/us_cities_sample.xlsx` | Liste de villes utilisée par le scraper ExpiredDomains. Le bloc de `main.py`, s’il est activé, lit les 50 premières lignes. |
| `coordonner.py` | Petit utilitaire qui affiche les coordonnées de la souris après cinq secondes. |
| `solver_button.png` | Image utilisée par l’assistance CAPTCHA de `Google.py`. |
| `expired_domains_TLD_net_final.xlsx` | Classeur principal local, enrichi avec les nouveaux domaines et proposé au téléchargement. |

## Prérequis

- Windows et Python 3.10 ou plus récent.
- Google Chrome installé. `Google.py` utilise actuellement `undetected_chromedriver` avec la version majeure **156** ; si Chrome est mis à jour vers une autre version majeure, cette valeur dans `src/scrap_from_Google/Google.py` devra être adaptée.
- Une connexion Internet pour les sites consultés et le téléchargement éventuel des pilotes Chrome.
- Un compte ExpiredDomains pour l’étape de collecte. Gmail et un mot de passe d’application sont nécessaires seulement si la vérification en deux étapes demande un code par e-mail.
- Une clé Serper seulement pour la variante `Google2.py`.

## Installation

Depuis la racine du dépôt, ouvrez PowerShell et créez un environnement virtuel :

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Si PowerShell refuse l’activation de l’environnement, vous pouvez aussi appeler directement `.\.venv\Scripts\python.exe` pour exécuter les commandes Python.

Les bibliothèques `requests`, `pyautogui` et `pygetwindow` ne sont pas nécessaires au parcours web habituel ; elles sont utilisées par la variante Serper ou l’assistance CAPTCHA.

## Configuration

Créez un fichier `.env` à la racine du dépôt. N’y mettez pas de guillemets autour des valeurs et ne publiez pas ce fichier :

```dotenv
EXPIREDDOMAINS_USERNAME=votre_identifiant
EXPIREDDOMAINS_PASSWORD=votre_mot_de_passe
GMAIL_ADDRESS=votre_adresse@gmail.com
GMAIL_APP_PASSWORD=votre_mot_de_passe_application
SERPER_API_KEY=votre_cle_serper
```

Les quatre premières variables servent à l’étape ExpiredDomains et à sa vérification éventuelle par e-mail. `SERPER_API_KEY` sert uniquement à `Google2.py`. Les variables inutilisées par une étape peuvent être omises. Les secrets présents dans `.env` ne doivent jamais être copiés dans le code ni ajoutés au dépôt.

## Utilisation

Toutes les commandes ci-dessous sont à lancer depuis la racine du dépôt.

### Application web

Lancez le serveur local une fois :

```powershell
python src/web_app.py
```

#### Démarrer depuis le Bureau avec un fichier `.bat`

Pour lancer l’application sans ouvrir PowerShell manuellement, créez un fichier `Domain_finder.bat` sur le Bureau, au même niveau que le dossier `DNS`, puis copiez-y le code suivant :

```bat
@echo off
cd /d "%~dp0DNS"

if not exist "src\web_app.py" (
    echo Impossible de trouver le projet dans "%~dp0DNS".
    pause
    exit /b 1
)

if exist ".venv-1\Scripts\python.exe" (
    ".venv-1\Scripts\python.exe" "src\web_app.py"
) else if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "src\web_app.py"
) else (
    python "src\web_app.py"
)

pause
```

Double-cliquez sur `Domain_finder.bat` pour démarrer le serveur, puis ouvrez [http://127.0.0.1:5000](http://127.0.0.1:5000) dans votre navigateur. Pour arrêter le serveur, revenez à la fenêtre de commande et appuyez sur `Ctrl+C`.

Avant la première recherche Google, préparez le profil Chrome utilisé par l’application :

1. Installez l’extension Chrome **Buster: Captcha Solver for Humans** dans le profil `C:\ChromeTemp\Default` utilisé par le scraper Google. Une extension installée uniquement dans votre profil Chrome habituel peut ne pas être présente dans ce profil d’automatisation.
2. Ouvrez [les préférences de recherche Google](https://www.google.com/preferences?hl=en&lang=1&prev=https://www.google.com/preferences?hl%3Den), puis réglez **Region Settings** sur **United States (USA)** ou sur la région de votre choix. Enregistrez les préférences.

Ouvrez ensuite [http://127.0.0.1:5000](http://127.0.0.1:5000). Le serveur de développement redémarre automatiquement après une modification du code Python ; les templates et les fichiers CSS/JavaScript sont servis sans cache. Actualisez la page du navigateur pour afficher les changements visuels. Choisissez « Rechercher par ville » pour la collecte habituelle, puis sélectionnez les États-Unis (`src/citys/us_cities_sample.xlsx`) ou le Canada (`src/citys/villes_canada.xlsx`). La liste des villes et les positions de l’intervalle sont actualisées selon le pays. Vous pouvez saisir des villes manuellement, choisir un intervalle inclusif à partir de la position 1, ou cocher « Scanner toutes les villes ». Les dix premières villes du pays choisi sont proposées par défaut. Renseignez les identifiants ExpiredDomains et, si nécessaire, Gmail pour cette collecte.

Choisissez « Analyser un Excel » pour importer un classeur `.xlsx` de 30 Mo maximum contenant une colonne `Domain` ou `Domaine .net`. Sélectionnez soit « Statut DNS et HTTP », soit « Google et Maps » ; l’application analyse le classeur importé sans lancer la collecte de villes et propose le fichier enrichi au téléchargement. L’import est traité dans un dossier temporaire local et n’écrase pas le classeur principal du projet.

Choisissez ensuite les analyses SEO Web Checker et Google/Maps à exécuter. Le champ TLD accepte par exemple `.net`, `.us`, `.com` ou `.co.uk`. Le filtre « Name in TLD is registered » d’ExpiredDomains reçoit ce TLD, puis les domaines correspondants sont ajoutés au classeur et envoyés aux analyses sélectionnées. Chaque combinaison pays/TLD possède son propre classeur : `.net` aux États-Unis utilise `expired_domains_TLD_net_final.xlsx`, tandis que `.net` au Canada utilise `expired_domains_CA_TLD_net_final.xlsx`. Les autres pays utilisent leur code dans le nom, par exemple `expired_domains_FR_TLD_net_final.xlsx`. Les domaines collectés dans un pays ne sont donc pas fusionnés avec ceux d’un autre. La page affiche le nom et le lien de téléchargement du classeur choisi. Vous pouvez annuler un traitement actif ; les domaines déjà collectés sont enregistrés. En cas d’erreur, vous pouvez reprendre à la dernière étape acquise, annuler/clôturer le processus ou le redémarrer depuis le début. La reprise conserve les villes et domaines déjà traités ; pendant la collecte, une ville interrompue avant sa fin est relancée en entier. Un redémarrage ne supprime pas les classeurs et réanalyse aussi les nouveaux domaines de la tentative échouée. Les points de reprise sont gardés en mémoire et sont perdus si le serveur est redémarré. Chrome s’ouvre sur la machine locale pendant les vérifications. Un seul traitement peut tourner à la fois.

L’application écoute uniquement sur `127.0.0.1` et n’est pas configurée pour être exposée sur Internet. Les identifiants sont transmis au processus local pour le traitement et ne sont pas écrits dans un fichier ; les champs de mot de passe sont effacés du formulaire après le démarrage du traitement. Si la récupération automatique du code de vérification Gmail échoue, le traitement s’arrête avec une erreur au lieu d’attendre une saisie dans le terminal.

Les états des traitements sont conservés en mémoire : le téléchargement est disponible tant que le serveur est lancé. Un redémarrage du serveur efface les liens de téléchargement affichés dans l’application. Les erreurs SEO Web Checker et Google/Maps sont consignées comme avertissements ; si la collecte initiale a produit un classeur, celui-ci reste téléchargeable même si une analyse optionnelle a échoué.

### Enrichissement Google en ligne de commande

Le classeur `expired_domains_TLD_net_final.xlsx` contient les résultats. Lancez le pipeline avec :

```powershell
python src/main.py
```

Le point d’entrée utilise les États-Unis par défaut. Pour collecter les villes canadiennes dans un classeur séparé, définissez `COUNTRY=ca` dans `.env` avant de lancer la commande ; le fichier produit sera `expired_domains_CA_TLD_net_final.xlsx`. Les villes supportées sont définies dans `COUNTRY_CITY_FILES` de `src/main.py`, et chaque nouveau code pays utilisera son propre nom de classeur.

Ce point d’entrée ouvre Chrome, traite les lignes éligibles et met à jour `Google Maps Pages` et `Sponsored Results` dans le classeur principal. Chrome reste visible pendant la recherche. Une vérification CAPTCHA peut interrompre le traitement ou demander une intervention ; l’assistance d’écran de `Google.py` dépend de `pyautogui`, `pygetwindow` et éventuellement de `solver_button.png`.

### Vérification SEO Web Checker

Pour lancer cette étape seule sur le classeur par défaut :

```powershell
python src/seowebchecker_bulk_domain_check.py
```

Le script lit `Domaine .net` (ou `Domain` en remplacement), limite l’envoi à 500 domaines, puis fusionne les colonnes `Status`, `HTTP Code`, `Resolved IP` et `Note`. Les valeurs déjà présentes dans ces colonnes ne sont pas écrasées. Le fichier temporaire `dns_checker_results.xlsx` est supprimé après une fusion réussie.

### Collecte ExpiredDomains et pipeline complet

Les appels à ExpiredDomains, SEO Web Checker et la boucle de collecte sont commentés dans `src/main.py`. Pour réaliser une collecte, configurez d’abord les identifiants dans `.env`, puis réactivez les blocs correspondants dans cet orchestrateur. La collecte lit les 50 premières villes de `src/citys/us_cities_sample.xlsx`, parcourt jusqu’à cinq pages par ville et ajoute les nouveaux résultats au classeur principal sans conserver les doublons de `Domain`.

L’ordre prévu est : collecte ExpiredDomains, vérification SEO Web Checker, puis enrichissement Google. Si vous ne réactivez que certaines étapes, assurez-vous que le classeur contient les colonnes nécessaires à l’étape suivante.

### Variante API Serper

`Google2.py` n’est pas utilisée par `main.py`. Elle nécessite `SERPER_API_KEY` dans `.env` et ajoute `Google All Pages` ainsi que `Google Maps Pages` au fichier fourni. Depuis la racine :

```powershell
python -c "import sys; sys.path.insert(0, 'src'); from scrap_from_Google.Google2 import enrich_with_google_data; enrich_with_google_data('expired_domains_TLD_net_final.xlsx')"
```

L’utilisation de l’API dépend des quotas et conditions de votre compte Serper.

### Utilitaire de coordonnées

Pour afficher les coordonnées courantes de la souris après cinq secondes :

```powershell
python coordonner.py
```

## Classeur Excel

Les scripts en ligne de commande et l’application web utilisent le fichier `expired_domains_TLD_net_final.xlsx` à la racine. Les domaines déjà présents ne sont pas ajoutés une seconde fois ; les recherches SEO et Google ne portent que sur les nouveaux domaines de la collecte courante. Le classeur complet mis à jour est téléchargeable depuis l’application web. Pour le vérificateur SEO, la colonne de domaine reconnue est `Domaine .net`, avec `Domain` comme solution de repli. Pour l’enrichissement Google, le nom requis est `Domain`.

Colonnes utilisées ou ajoutées par les scripts :

| Colonne | Description |
| --- | --- |
| `City` | Ville associée au domaine, lors d’une collecte ExpiredDomains. |
| `Domain` | Domaine d’origine, utilisé pour les recherches Google. |
| `Date Scraping from E_D` | Date et heure de collecte. |
| `Domaine .net` | Domaine envoyé au vérificateur DNS/HTTP. |
| `Status` | Statut affiché par SEO Web Checker. |
| `HTTP Code` | Code HTTP utilisé aussi par le filtre de l’étape Google. |
| `Resolved IP` | Adresse IP renvoyée par le vérificateur. |
| `Note` | Commentaire du vérificateur. |
| `Google Maps Pages` | Indicateur de pagination Google Maps obtenu par `Google.py`, ou nombre de lieux via Serper dans `Google2.py`. |
| `Sponsored Results` | Présence de résultats sponsorisés, obtenue par `Google.py`. |
| `Google All Pages` | Nombre de pages estimé par `Google2.py` uniquement. |

Faites une copie du classeur avant une exécution importante. Fermez-le dans Excel pendant que les scripts l’écrivent afin d’éviter les erreurs d’accès au fichier.

## Dépannage

- **`ModuleNotFoundError`** : activez `.venv` et installez les dépendances listées plus haut.
- **Chrome ou ChromeDriver ne démarre pas** : vérifiez que Chrome est installé, que sa version majeure correspond à celle configurée dans `Google.py`, et que le téléchargement du pilote est autorisé par le réseau.
- **Aucun domaine n’est envoyé à Google** : vérifiez les valeurs exactes de `HTTP Code` (`200`, `301`, `302`, `405`) et que la colonne `Domain` existe.
- **Une ligne Google est ignorée** : si `Google Maps Pages` et `Sponsored Results` sont déjà renseignées, le script la considère comme terminée.
- **Le tableau SEO Web Checker n’est pas complet** : le script attend jusqu’à 300 secondes que toutes les lignes soumises apparaissent. En cas d’échec, l’exception indique le nombre attendu et le nombre détecté.
- **Erreur d’écriture Excel** : fermez le classeur dans Excel et relancez le script.
- **Le site ou un CAPTCHA bloque l’automatisation** : vérifiez la fenêtre Chrome et intervenez si une validation manuelle est demandée. Les sélecteurs Selenium peuvent aussi devoir être actualisés si le site change son interface.