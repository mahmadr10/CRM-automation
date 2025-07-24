import requests
from bs4 import BeautifulSoup
import re
from bs4 import Tag

HUNTER_API_KEY = "977abb4ede805ad28aed27a6c38181fc07929335"

def extract_emails_from_text(text):
    return re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', text)

def get_company_domain(company_name):
    try:
        query = f"{company_name} official site"
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, "html.parser")

        for a_tag in soup.find_all("a", href=True):
            if isinstance(a_tag, Tag):
                href = a_tag.get("href")
                if href and "http" in href and "google" not in href:
                    clean_links = re.findall(r"https?://[^&]+", str(href))
                    if clean_links:
                        domain = clean_links[0].split("//")[-1].split("/")[0]
                        if "." in domain and not domain.startswith("www.google."):
                            return domain
    except Exception as e:
        print("[ERROR] Failed to get company domain:", e)

    return None

def use_hunter_api(domain):
    try:
        url = f"https://api.hunter.io/v2/domain-search?domain={domain}&api_key={HUNTER_API_KEY}"
        res = requests.get(url).json()
        emails = [e['value'] for e in res.get("data", {}).get("emails", [])]
        return emails
    except Exception as e:
        print("[WARN] Hunter API failed:", e)
        return []

def scrape_company_contact_page(domain):
    try:
        for path in ["contact", "about", "contact-us"]:
            url = f"https://{domain}/{path}"
            headers = {"User-Agent": "Mozilla/5.0"}
            res = requests.get(url, headers=headers, timeout=5)
            emails = extract_emails_from_text(res.text)
            if emails:
                return emails
    except Exception as e:
        print(f"[WARN] Failed to scrape company site: {e}")
    return []

def google_email_fallback(name, company):
    try:
        query = f'"{name}" "{company}" email'
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers)
        emails = extract_emails_from_text(res.text)
        return emails
    except Exception as e:
        print("[WARN] Google fallback failed:", e)
        return []

def scrape_emails_google(name, company):
    emails = []

    domain = get_company_domain(company)
    if domain:
        emails = use_hunter_api(domain)

    if not emails and domain:
        emails = scrape_company_contact_page(domain)

    if not emails:
        emails = google_email_fallback(name, company)

    return emails[0] if emails else None
