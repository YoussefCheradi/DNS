import codecs
import ipaddress
import json
import re
import socket
import time
from html.parser import HTMLParser
from html import unescape as html_unescape
from urllib.robotparser import RobotFileParser
from urllib.parse import (
    parse_qsl,
    urlencode,
    unquote,
    urljoin,
    urlparse,
    urlunparse,
)
from xml.etree import ElementTree

import requests


MAX_PAGES_PER_SITE = 12
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT = (5, 12)
MAX_RETRIES = 3
REQUEST_DELAY_SECONDS = 0.35
USER_AGENT = "GeoDomainContactResearch/1.0 (+local business contact research)"
EMAIL_PATTERN = re.compile(
    r"(?i)(?<![\w.+/@:-])[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+"
    r"(?:\.[a-z0-9-]+)+(?![\w/-])"
)
URL_PATTERN = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
SCRIPT_URL_PATTERN = re.compile(r"(?i)https?:(?:\\?/){2}[^'\"<>\s]+")
PLACEHOLDER_EMAILS = {
    "john@example.com",
    "jane@example.com",
    "name@example.com",
    "email@example.com",
    "user@example.com",
    "you@example.com",
    "john@company.com",
    "you@company.com",
    "user@company.com",
    "name@company.com",
    "user@website.com",
    "email@website.com",
    "name@yourdomain.com",
    "email@yourdomain.com",
}
EXAMPLE_EMAIL_DOMAINS = {"example.com", "example.org", "example.net"}
PERSONAL_EMAIL_DOMAINS = {
    "aol.com",
    "gmail.com",
    "googlemail.com",
    "hotmail.com",
    "icloud.com",
    "live.com",
    "outlook.com",
    "proton.me",
    "protonmail.com",
    "yahoo.com",
}
GENERIC_DOMAIN_LABELS = {
    "ac",
    "co",
    "com",
    "edu",
    "gov",
    "int",
    "mil",
    "net",
    "org",
    "test",
    "uk",
}
NON_BRAND_SUBDOMAINS = {"email", "mail", "smtp", "web", "www"}
PAGE_KEYWORDS = (
    "about",
    "contact",
    "team",
    "staff",
    "company",
    "support",
    "privacy",
    "cookie",
    "legal",
    "imprint",
    "locations",
    "people",
    "leadership",
)
SKIP_PATH_PARTS = {
    "login",
    "signin",
    "sign-in",
    "register",
    "account",
    "cart",
    "checkout",
    "search",
    "wp-admin",
    "wp-login",
    "feed",
}
SKIP_FILE_EXTENSIONS = {
    ".7z", ".avi", ".css", ".csv", ".dmg", ".doc", ".docx", ".eot", ".exe",
    ".gif", ".gz", ".ico", ".jpeg", ".jpg", ".js", ".json", ".map", ".mp3",
    ".mp4", ".pdf", ".png", ".ppt", ".pptx", ".rar", ".svg", ".tar", ".tif",
    ".ttf", ".webm", ".webp", ".woff", ".woff2", ".xls", ".xlsx", ".xml",
    ".zip",
}
TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
}
EMAIL_SOURCE_COLUMNS = {
    "Emails": "Email Source URLs",
    "Instagram URLs": "Instagram Source URLs",
    "LinkedIn URLs": "LinkedIn Source URLs",
    "Facebook URLs": "Facebook Source URLs",
    "X URLs": "X Source URLs",
}
COOKIE_TEXT_PATTERN = re.compile(
    r"(?i)\b(cookie|cookies|consent|tracking technologies|manage preferences)\b"
)


class _PageParser(HTMLParser):
    _void_tags = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.text_parts = []
        self.cookie_text_parts = []
        self.email_candidates = []
        self.structured_data = []
        self.script_parts = []
        self._tag_stack = []
        self._cookie_depth = 0
        self._skip_depth = 0
        self._json_ld_depth = 0
        self._script_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attributes = dict(attrs)
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag == "script":
            self._script_depth += 1
        if tag == "script" and "ld+json" in attributes.get("type", "").lower():
            self._json_ld_depth += 1
        if tag == "a" and attributes.get("href"):
            self.links.append(
                (
                    attributes["href"],
                    attributes.get("aria-label", ""),
                    attributes.get("title", ""),
                    attributes.get("rel", ""),
                    attributes.get("class", ""),
                )
            )
            if attributes["href"].lower().startswith("mailto:"):
                self.email_candidates.append(attributes["href"][7:])
            for attribute in ("aria-label", "title", "data-email"):
                if attributes.get(attribute):
                    self.email_candidates.append(attributes[attribute])
        for attribute in ("data-email", "data-contact", "aria-label", "title", "alt"):
            if attributes.get(attribute):
                self.email_candidates.append(attributes[attribute])
        itemprop = attributes.get("itemprop", "").lower()
        if "email" in itemprop and attributes.get("content"):
            self.email_candidates.append(attributes["content"])
        if attributes.get("name", "").lower() in {"email", "contact-email"}:
            self.email_candidates.append(attributes.get("content", ""))
        if attributes.get("property", "").lower() in {"email", "og:email"}:
            self.email_candidates.append(attributes.get("content", ""))
        marker = " ".join(
            (
                attributes.get("id", ""),
                attributes.get("class", ""),
                attributes.get("aria-label", ""),
            )
        ).lower()
        is_cookie_marker = any(word in marker for word in ("cookie", "consent", "privacy-notice"))
        if is_cookie_marker:
            self._cookie_depth += 1
        if tag not in self._void_tags:
            self._tag_stack.append(
                (
                    tag,
                    is_cookie_marker,
                    tag == "script" and "ld+json" in attributes.get("type", "").lower(),
                    tag == "script",
                )
            )

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self._void_tags:
            return
        while self._tag_stack:
            stacked_tag, is_cookie_marker, is_json_ld, is_script = self._tag_stack.pop()
            if is_cookie_marker:
                self._cookie_depth -= 1
            if is_json_ld:
                self._json_ld_depth -= 1
            if is_script:
                self._script_depth -= 1
            if stacked_tag in {"script", "style", "noscript", "svg"}:
                self._skip_depth -= 1
            if stacked_tag == tag:
                break

    def handle_data(self, data):
        if self._script_depth:
            self.script_parts.append(data)
        if self._json_ld_depth:
            self.structured_data.append(data)
        text = " ".join(data.split())
        if not text:
            return
        if not self._skip_depth:
            self.text_parts.append(text)
            if self._cookie_depth:
                self.cookie_text_parts.append(text)


def _validate_public_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("L’URL doit utiliser HTTP ou HTTPS.")
    if parsed.username or parsed.password:
        raise ValueError("Les identifiants intégrés dans les URL ne sont pas autorisés.")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("Les hôtes locaux ne sont pas autorisés.")
    try:
        address = ipaddress.ip_address(hostname)
        addresses = [address]
    except ValueError:
        try:
            addresses = [
                ipaddress.ip_address(result[4][0])
                for result in socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
            ]
        except OSError as exc:
            raise ValueError(f"Impossible de résoudre l’hôte {hostname}.") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Les adresses IP privées ou non publiques ne sont pas autorisées.")
    return urlunparse(parsed._replace(fragment=""))


def _fetch_public_page(session, url, cancel_check=None):
    current_url = _validate_public_url(url)
    for _ in range(6):
        if cancel_check is not None:
            cancel_check()
        response = None
        try:
            for attempt in range(MAX_RETRIES):
                if cancel_check is not None:
                    cancel_check()
                if attempt:
                    time.sleep(min(2 ** (attempt - 1), 4))
                try:
                    response = session.get(
                        current_url,
                        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
                        timeout=REQUEST_TIMEOUT,
                        stream=True,
                        allow_redirects=False,
                    )
                except requests.RequestException:
                    if attempt == MAX_RETRIES - 1:
                        raise
                    continue
                if response.status_code != 429 and response.status_code < 500:
                    break
                if attempt == MAX_RETRIES - 1:
                    return None, current_url
                retry_after = response.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    time.sleep(min(int(retry_after), 8))
                response.close()
                response = None

            if response is None:
                return None, current_url
            if response.is_redirect or response.is_permanent_redirect:
                destination = response.headers.get("Location")
                if not destination:
                    return None, current_url
                current_url = _validate_public_url(urljoin(current_url, destination))
                continue
            if response.status_code >= 400:
                return None, current_url
            content_type = response.headers.get("Content-Type", "").lower()
            if (
                "html" not in content_type
                and "text/" not in content_type
                and "xml" not in content_type
            ):
                return None, current_url

            body = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if cancel_check is not None:
                    cancel_check()
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ValueError("La page dépasse la taille maximale autorisée de 2 Mo.")
            encoding = (response.encoding or "").strip().lower().replace("_", "-")
            if encoding in {"utf8mb4", "utf8mb3"}:
                encoding = "utf-8"
            if not encoding:
                encoding = "utf-8-sig" if body.startswith(codecs.BOM_UTF8) else "utf-8"
            try:
                codecs.lookup(encoding)
            except LookupError:
                encoding = "utf-8"
            return body.decode(encoding, errors="replace"), current_url
        except requests.RequestException:
            if response is not None:
                response.close()
            raise
        finally:
            if response is not None:
                response.close()
    raise ValueError("Trop de redirections sur le site.")


def _canonical_site(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return host


def _normalize_url(url):
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return ""
    host = parsed.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    try:
        port = parsed.port
    except ValueError:
        return ""
    netloc = host if port in {None, 80 if parsed.scheme == "http" else 443} else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in TRACKING_PARAMETERS
            and not key.lower().startswith("utm_")
        ]
    )
    return urlunparse((parsed.scheme.lower(), netloc, path, "", query, ""))


def _social_network(url):
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if host == "instagram.com" or host.endswith(".instagram.com"):
        return "Instagram URLs"
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "LinkedIn URLs"
    if host in {"facebook.com", "fb.com"} or host.endswith((".facebook.com", ".fb.com")):
        return "Facebook URLs"
    if host in {"x.com", "twitter.com"} or host.endswith((".x.com", ".twitter.com")):
        return "X URLs"
    return None


def _is_social_profile(url, link_text=""):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path_parts = [part for part in parsed.path.split("/") if part]
    text = unquote(link_text).lower()
    if any(
        marker in f"{host}{parsed.path.lower()} {text}"
        for marker in (
            "/share",
            "sharer.php",
            "/intent/",
            "/login",
            "/signin",
            "/accounts/",
            "share on",
            "sign in",
            "log in",
            "share this",
        )
    ):
        return False
    network = _social_network(url)
    if network is None or not path_parts:
        return False
    if network == "LinkedIn URLs":
        return path_parts[0].lower() in {"company", "in", "school", "showcase"}
    if network == "Facebook URLs" and path_parts[0].lower() in {
        "plugins",
        "dialog",
        "events",
        "help",
        "watch",
    }:
        return False
    return True


def _clean_email(value):
    email = html_unescape(unquote(value)).strip().lower()
    email = re.sub(r"^(mailto:|email:)", "", email, flags=re.IGNORECASE)
    email = email.split("?", 1)[0].strip(" <>.,;:()[]{}")
    if not EMAIL_PATTERN.fullmatch(email):
        return None
    local_part, domain = email.rsplit("@", 1)
    domain_labels = domain.split(".")
    if (
        len(email) > 254
        or len(local_part) > 64
        or local_part.startswith(".")
        or local_part.endswith(".")
        or ".." in local_part
        or any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            for label in domain_labels
        )
    ):
        return None
    if domain in EXAMPLE_EMAIL_DOMAINS or domain.endswith(".example"):
        return None
    if email in PLACEHOLDER_EMAILS or local_part in {
        "email",
        "example",
        "firstname.lastname",
        "first.last",
        "insert-email",
        "name",
        "your-email",
        "yourname",
        "user",
    }:
        return None
    return email


def _domain_identity_tokens(host):
    labels = host.lower().rstrip(".").removeprefix("www.").split(".")
    if len(labels) > 1:
        labels.pop()
    if labels and labels[-1] in {"ac", "co", "com", "edu", "gov", "net", "org"}:
        labels.pop()
    return {
        token
        for label in labels
        if label not in GENERIC_DOMAIN_LABELS and label not in NON_BRAND_SUBDOMAINS
        for token in label.split("-")
        if len(token) >= 2
        and token not in GENERIC_DOMAIN_LABELS
        and token not in NON_BRAND_SUBDOMAINS
        and not token.isdigit()
    }


def _email_domain_matches_site(email, site_host):
    email_domain = email.rsplit("@", 1)[-1]
    if email_domain in PERSONAL_EMAIL_DOMAINS:
        return True
    return bool(_domain_identity_tokens(email_domain) & _domain_identity_tokens(site_host))


def _extract_emails(candidates):
    emails = set()
    for candidate in candidates:
        text = html_unescape(unquote(str(candidate)))
        text = re.sub(
            r"(?i)\s*(?:\[at\]|\(at\)|\{at\}|\s+at\s+)\s*",
            "@",
            text,
        )
        text = re.sub(
            r"(?i)\s*(?:\[dot\]|\(dot\)|\{dot\}|\s+dot\s+)\s*",
            ".",
            text,
        )
        text = re.sub(r"(?i)\s*(?:&#64;|&commat;)\s*", "@", text)
        text = URL_PATTERN.sub(" ", text)
        for match in EMAIL_PATTERN.finditer(text):
            email = _clean_email(match.group(0))
            if email:
                emails.add(email)
    return emails


def _structured_values(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"email", "sameas"}:
                if isinstance(item, list):
                    yield key.lower(), item
                else:
                    yield key.lower(), [item]
            yield from _structured_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _structured_values(item)


def _page_priority(url, label=""):
    path = unquote(urlparse(url).path).lower()
    segments = [segment for segment in path.split("/") if segment]
    segment_text = " ".join(segments)
    text = f"{segment_text} {label}".lower()
    if any(part in segment for segment in segments for part in SKIP_PATH_PARTS):
        return None
    if any(path.endswith(extension) for extension in SKIP_FILE_EXTENSIONS):
        return None
    if not segments:
        return 0
    if any(keyword in text for keyword in ("contact", "about", "team", "staff", "leadership")):
        return 1
    if any(keyword in text for keyword in ("company", "people", "location", "service", "privacy", "cookie", "legal")):
        return 2
    return None


def _sitemap_pages(session, root_url, cancel_check=None):
    parsed_root = urlparse(root_url)
    origin = f"{parsed_root.scheme}://{parsed_root.netloc}"
    sitemap_urls = [urljoin(origin, "/sitemap.xml")]
    robots_url = urljoin(origin, "/robots.txt")
    failures = []
    robots_parser = RobotFileParser()
    robots_parser.set_url(robots_url)
    try:
        text, _ = _fetch_public_page(session, robots_url, cancel_check)
        if text:
            robots_parser.parse(text.splitlines())
            sitemap_urls.extend(
                line.split(":", 1)[1].strip()
                for line in text.splitlines()
                if line.strip().lower().startswith("sitemap:")
            )
        else:
            robots_parser.parse([])
    except (requests.RequestException, ValueError, UnicodeError) as exc:
        failures.append(f"{robots_url} ({type(exc).__name__})")
        robots_parser.parse([])

    discovered = []
    seen_sitemaps = set()
    pending = list(dict.fromkeys(sitemap_urls))
    while pending and len(seen_sitemaps) < 3 and len(discovered) < 100:
        if cancel_check is not None:
            cancel_check()
        sitemap_url = pending.pop(0)
        if _canonical_site(sitemap_url) != _canonical_site(root_url):
            continue
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        try:
            xml_text, _ = _fetch_public_page(session, sitemap_url, cancel_check)
        except (requests.RequestException, ValueError, UnicodeError) as exc:
            failures.append(f"{sitemap_url} ({type(exc).__name__})")
            continue
        if not xml_text:
            continue
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError:
            failures.append(f"{sitemap_url} (XML invalide)")
            continue
        root_kind = root.tag.rsplit("}", 1)[-1].lower()
        locations = [
            (element.text or "").strip()
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1].lower() == "loc"
        ]
        if root_kind == "sitemapindex":
            pending.extend(locations)
            continue
        for candidate in locations:
            normalized = _normalize_url(candidate)
            if (
                normalized
                and _canonical_site(normalized) == _canonical_site(root_url)
                and _page_priority(normalized) is not None
            ):
                discovered.append(normalized)
    return list(dict.fromkeys(discovered)), failures, robots_parser


def _cookie_banner_text(parser):
    text = " ".join(parser.cookie_text_parts)
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1000]


def scrape_website_contacts(url, cancel_check=None, max_pages=MAX_PAGES_PER_SITE):
    result = {
        "Emails": set(),
        "Instagram URLs": set(),
        "LinkedIn URLs": set(),
        "Facebook URLs": set(),
        "X URLs": set(),
        "Email Source URLs": set(),
        "Instagram Source URLs": set(),
        "LinkedIn Source URLs": set(),
        "Facebook Source URLs": set(),
        "X Source URLs": set(),
        "Email Status": "not_found",
        "Email Format Status": "not_found",
        "Social Status": "not_found",
        "Social Association Status": "unverified",
        "Cookie Notice (public)": "",
        "Cookie Policy URL": "",
        "Cookie Policy Notes (public)": "",
        "Pages Scanned": 0,
        "Pages Visited": set(),
        "Pages Skipped": 0,
        "Skipped Page URLs": set(),
        "Pages Failed": 0,
        "Failed Page URLs": set(),
        "Scrape Status": "",
    }
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    try:
        start_url = _validate_public_url(str(url).strip())
        site = _canonical_site(start_url)
        pending = [(0, start_url)]
        visited = set()
        failed_pages = []
        skipped_pages = set()
        emails_by_source = {}
        social_by_source = {column: {} for column in EMAIL_SOURCE_COLUMNS.values() if column != "Email Source URLs"}
        cookie_policy_candidates = []

        sitemap_urls, sitemap_failures, robots_parser = _sitemap_pages(
            session, start_url, cancel_check
        )
        failed_pages.extend(sitemap_failures)
        for sitemap_page_url in sitemap_urls:
            priority = _page_priority(sitemap_page_url)
            if priority is not None:
                pending.append((priority, sitemap_page_url))

        while pending and len(visited) < max_pages:
            if cancel_check is not None:
                cancel_check()
            pending.sort(key=lambda item: (item[0], item[1]))
            _, page_url = pending.pop(0)
            normalized_url = _normalize_url(_validate_public_url(page_url))
            if not normalized_url or _canonical_site(normalized_url) != site:
                result["Pages Skipped"] += 1
                result["Skipped Page URLs"].add(page_url)
                continue
            if normalized_url in visited:
                continue
            if not robots_parser.can_fetch(USER_AGENT, normalized_url):
                skipped_pages.add(normalized_url)
                continue
            visited.add(normalized_url)

            try:
                html, final_url = _fetch_public_page(session, normalized_url, cancel_check)
            except (requests.RequestException, ValueError, UnicodeError) as exc:
                failed_pages.append(f"{normalized_url} ({type(exc).__name__})")
                continue
            if not html:
                failed_pages.append(f"{normalized_url} (HTTP/no HTML)")
                continue
            result["Pages Scanned"] += 1
            result["Pages Visited"].add(final_url)
            parser = _PageParser()
            parser.feed(html)
            if not result["Cookie Notice (public)"]:
                result["Cookie Notice (public)"] = _cookie_banner_text(parser)

            page_text = " ".join(parser.text_parts)
            page_path = unquote(urlparse(final_url).path).lower()
            if "cookie" in page_path or "privacy" in page_path:
                result["Cookie Policy URL"] = final_url
                policy_excerpts = re.findall(
                    r"[^.!?]*\b(?:cookies?|consent|tracking technologies|retention)\b[^.!?]*[.!?]?",
                    page_text,
                    flags=re.IGNORECASE,
                )
                result["Cookie Policy Notes (public)"] = " ".join(policy_excerpts)[:2500]
            emails = _extract_emails(
                [
                    *parser.text_parts,
                    *parser.cookie_text_parts,
                    *parser.email_candidates,
                    *parser.script_parts,
                ]
            )
            for json_data in parser.structured_data:
                try:
                    structured = json.loads(json_data)
                except (TypeError, json.JSONDecodeError):
                    continue
                for key, values in _structured_values(structured):
                    if key == "email":
                        emails.update(_extract_emails(values))
                    else:
                        for value in values:
                            social_url = _normalize_url(str(value))
                            column = _social_network(social_url)
                            if column and _is_social_profile(social_url):
                                result[column].add(social_url)
                                social_by_source[EMAIL_SOURCE_COLUMNS[column]].setdefault(
                                    social_url, set()
                                ).add(final_url)

            for email in emails:
                if not _email_domain_matches_site(email, site):
                    continue
                result["Emails"].add(email)
                emails_by_source.setdefault(email, set()).add(final_url)

            for script_text in parser.script_parts:
                for script_url in SCRIPT_URL_PATTERN.findall(script_text):
                    normalized_script_url = _normalize_url(
                        script_url.replace("\\/", "/").rstrip(".,);")
                    )
                    column = _social_network(normalized_script_url)
                    if column and _is_social_profile(normalized_script_url):
                        result[column].add(normalized_script_url)
                        social_by_source[EMAIL_SOURCE_COLUMNS[column]].setdefault(
                            normalized_script_url, set()
                        ).add(final_url)

            for href, label, title, rel, classes in parser.links:
                absolute_url = urljoin(final_url, href.strip())
                normalized_social_url = _normalize_url(absolute_url)
                network_column = _social_network(normalized_social_url)
                link_context = " ".join((label, title, rel, classes, href))
                if network_column and _is_social_profile(normalized_social_url, link_context):
                    result[network_column].add(normalized_social_url)
                    social_by_source[EMAIL_SOURCE_COLUMNS[network_column]].setdefault(
                        normalized_social_url, set()
                    ).add(final_url)
                if href.lower().startswith("mailto:"):
                    mailto_emails = _extract_emails([href[7:]])
                    mailto_emails = {
                        email for email in mailto_emails
                        if _email_domain_matches_site(email, site)
                    }
                    result["Emails"].update(mailto_emails)
                    for email in mailto_emails:
                        emails_by_source.setdefault(email, set()).add(final_url)

                parsed_link = urlparse(absolute_url)
                if parsed_link.scheme not in {"http", "https"}:
                    continue
                link_host = _canonical_site(absolute_url)
                if link_host != site:
                    continue
                link_text = unquote(" ".join((href, label, title))).lower()
                link_path = unquote(parsed_link.path).lower()
                if "cookie" in link_text or "cookie" in link_path:
                    cookie_policy_candidates.append((0, _normalize_url(absolute_url)))
                elif "privacy" in link_text or "privacy" in link_path:
                    cookie_policy_candidates.append((1, _normalize_url(absolute_url)))
                priority = _page_priority(absolute_url, link_text)
                if priority is None:
                    if any(keyword in link_text for keyword in PAGE_KEYWORDS):
                        skipped_pages.add(_normalize_url(absolute_url))
                    continue
                normalized_link = _normalize_url(absolute_url)
                if normalized_link and normalized_link not in visited:
                    pending.append((priority, normalized_link))

            if COOKIE_TEXT_PATTERN.search(page_text) and not result["Cookie Notice (public)"]:
                matches = re.findall(
                    r"[^.!?]*\b(?:cookies?|consent|tracking technologies|manage preferences)\b[^.!?]*[.!?]?",
                    page_text,
                    flags=re.IGNORECASE,
                )
                result["Cookie Notice (public)"] = " ".join(matches)[:1000]

            if pending and len(visited) < max_pages:
                time.sleep(REQUEST_DELAY_SECONDS)

        cookie_policy_url = next(
            (
                candidate
                for _, candidate in sorted(set(cookie_policy_candidates))
                if candidate not in visited
            ),
            None,
        )
        if cookie_policy_url and not result["Cookie Policy URL"] and len(visited) < max_pages:
            try:
                can_fetch_policy = robots_parser.can_fetch(USER_AGENT, cookie_policy_url)
                if can_fetch_policy:
                    visited.add(cookie_policy_url)
                    policy_html, final_policy_url = _fetch_public_page(
                        session, cookie_policy_url, cancel_check
                    )
                    if policy_html:
                        policy_parser = _PageParser()
                        policy_parser.feed(policy_html)
                        policy_text = " ".join(policy_parser.text_parts)
                        policy_emails = _extract_emails(
                            [
                                *policy_parser.text_parts,
                                *policy_parser.cookie_text_parts,
                                *policy_parser.email_candidates,
                                *policy_parser.script_parts,
                            ]
                        )
                        for email in policy_emails:
                            if _email_domain_matches_site(email, site):
                                result["Emails"].add(email)
                                emails_by_source.setdefault(email, set()).add(
                                    final_policy_url
                                )
                        excerpts = re.findall(
                            r"[^.!?]*\b(?:cookies?|consent|tracking technologies|retention)\b[^.!?]*[.!?]?",
                            policy_text,
                            flags=re.IGNORECASE,
                        )
                        result["Cookie Policy URL"] = final_policy_url
                        result["Cookie Policy Notes (public)"] = " ".join(excerpts)[:2500]
                        result["Pages Scanned"] += 1
                else:
                    skipped_pages.add(cookie_policy_url)
            except (requests.RequestException, ValueError, UnicodeError) as exc:
                failed_pages.append(f"{cookie_policy_url} ({type(exc).__name__})")

        result["Pages Failed"] = len(failed_pages)
        result["Pages Skipped"] += len(skipped_pages)
        result["Skipped Page URLs"].update(skipped_pages)
        result["Failed Page URLs"] = set(failed_pages)
        result["Email Source URLs"] = {
            f"{email} => {source}"
            for email, sources in emails_by_source.items()
            for source in sources
        }
        for email_sources_column, values_by_source in social_by_source.items():
            result[email_sources_column] = {
                f"{value} => {source}"
                for value, sources in values_by_source.items()
                for source in sources
            }
        result["Email Status"] = "unverified" if result["Emails"] else "not_found"
        result["Email Format Status"] = "valid_format" if result["Emails"] else "not_found"
        result["Social Status"] = (
            "found"
            if any(result[column] for column in EMAIL_SOURCE_COLUMNS if column != "Emails")
            else "not_found"
        )
        result["Social Association Status"] = (
            "unverified" if result["Social Status"] == "found" else "not_found"
        )
        result["Scrape Status"] = (
            f"Partiel : {len(failed_pages)} page(s) inaccessible(s)"
            if failed_pages or pending
            else "OK" if result["Pages Scanned"]
            else "Aucune page HTML accessible"
        )
    except (requests.RequestException, ValueError, UnicodeError) as exc:
        result["Scrape Status"] = f"Erreur : {type(exc).__name__}: {exc}"
    finally:
        session.close()

    for key, value in result.items():
        if isinstance(value, set):
            result[key] = "; ".join(sorted(value))
    return result
