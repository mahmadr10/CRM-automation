import streamlit as st
import requests
import re
import smtplib
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup
import urllib.parse
import time
import random
import json
import sqlite3

# --- SQLite DB Setup ---
DB_PATH = "a.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            title TEXT,
            company TEXT,
            email TEXT UNIQUE,
            linkedin TEXT,
            snippet TEXT
        )
    """)
    conn.commit()
    conn.close()

def insert_lead(lead):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("""
            INSERT OR IGNORE INTO leads (name, title, company, email, linkedin, snippet)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            lead.get("Name"),
            lead.get("Title"),
            lead.get("Company"),
            lead.get("Email"),
            lead.get("LinkedIn"),
            lead.get("Snippet"),
        ))
        conn.commit()
    finally:
        conn.close()

# Initialize DB at startup
init_db()

# --- Config ---
st.set_page_config(page_title="Email Outreach Tool", layout="centered")
st.markdown("<h3 style='text-align: left;'> FineIT's Automated Email Outreach for CRM by M.Ahmad </h3>", unsafe_allow_html=True)

SERPAPI_API_KEY = "2e265cccb6297a0f417c10856d6c410b1506bf48715714cd81d550fe3067e7a2"

EMAIL_REGEX = re.compile(r'''
    \b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b
''', re.VERBOSE)

BLOCKED_DOMAINS = {
    "ingest.sentry.io", "example.com", "test.com", "tempmail.com", "disposablemail.com",
    "protonmail.com", "gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
    "aol.com", "icloud.com", "live.com",
}

def is_valid_email(email: str) -> bool:
    return re.fullmatch(EMAIL_REGEX, email) is not None

def is_valid_business_email(email: str) -> bool:
    if not is_valid_email(email):
        return False
    domain = email.split("@")[-1].lower()
    if domain in BLOCKED_DOMAINS:
        return False
    local_part = email.split("@")[0]
    if len(local_part) > 20 and re.fullmatch(r"[a-f0-9]+", local_part):
        return False
    return True

def serpapi_Google_Search(query, pages=1, show_debug=True):
    all_results = []
    if show_debug:
        progress_bar = st.progress(0)
    for page in range(pages):
        if show_debug:
            progress_bar.progress((page) / pages)
        start = page * 10
        params = {
            "engine": "google",
            "q": query,
            "api_key": SERPAPI_API_KEY,
            "start": start,
            "hl": "en",
            "gl": "us",
            "num": 10
        }
        if show_debug:
            st.write(f"**Page {page+1}:** Making request with params:")
            st.json(params)
        try:
            response = requests.get("https://serpapi.com/search", params=params, timeout=15)
            if show_debug:
                st.write(f"**Response Status:** {response.status_code}")
            if response.status_code == 401:
                st.error("❌ Unauthorized: Check your API key")
                break
            elif response.status_code == 429:
                st.error("❌ Too many requests: Rate limit exceeded")
                break
            elif response.status_code != 200:
                st.error(f"❌ HTTP {response.status_code}: {response.text[:200]}")
                break
            content_type = response.headers.get('content-type', '')
            if 'application/json' not in content_type:
                st.error(f"❌ Expected JSON but got: {content_type}")
                st.write(f"Response content: {response.text[:500]}")
                break
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                st.error(f"❌ JSON decode error: {e}")
                st.write(f"Raw response: {response.text[:500]}")
                break
            if show_debug:
                with st.expander(f"Raw API Response - Page {page+1}"):
                    st.json(data)
            if "error" in data:
                st.error(f"SerpAPI Error: {data['error']}")
                break
            results = data.get("organic_results", [])
            if show_debug:
                st.info(f"Page {page+1}: Found {len(results)} raw results")
            for r in results:
                all_results.append({
                    "title": r.get("title"),
                    "link": r.get("link"),
                    "snippet": r.get("snippet") or ""
                })
            if len(results) == 0:
                if show_debug:
                    st.warning(f"No more results found on page {page+1}")
                break
            time.sleep(random.uniform(1, 3))
        except requests.exceptions.Timeout:
            st.error(f"❌ Request timeout on page {page+1}")
            break
        except requests.exceptions.RequestException as e:
            st.error(f"❌ Request error on page {page+1}: {e}")
            break
        except Exception as e:
            st.error(f"❌ Unexpected error on page {page+1}: {e}")
            break
    if show_debug:
        progress_bar.progress(1.0)
        st.success(f"Total results collected: {len(all_results)}")
    return all_results

def extract_emails_from_text(text):
    emails_found = set()
    matches = EMAIL_REGEX.findall(text)
    for email in matches:
        if is_valid_business_email(email):
            emails_found.add(email.strip())
    return list(emails_found)

def extract_emails_from_url(url, max_depth=1, visited=None):
    if visited is None:
        visited = set()
    emails_found = set()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
    try:
        if url in visited or max_depth < 0:
            return []
        visited.add(url)
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        html = response.text

        soup = BeautifulSoup(html, 'html.parser')

        # 1. Look for mailto links
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.startswith('mailto:'):
                email = href[len('mailto:'):].split('?')[0]
                if is_valid_business_email(email):
                    emails_found.add(email.strip())

        # 2. Search for emails in the entire text of the page
        page_text = soup.get_text()
        emails_from_text = extract_emails_from_text(page_text)
        emails_found.update(emails_from_text)

        # 3. If not found, follow "Contact" or "About" links (one level deep)
        if max_depth > 0 and not emails_found:
            base_url = urllib.parse.urljoin(url, '/')
            for link in soup.find_all('a', href=True):
                href = link['href'].lower()
                if any(word in href for word in ['contact', 'about']):
                    next_url = urllib.parse.urljoin(base_url, link['href'])
                    if next_url not in visited:
                        emails_found.update(extract_emails_from_url(next_url, max_depth-1, visited))
                        if emails_found:
                            break

    except requests.exceptions.RequestException as e:
        st.warning(f"Could not access {url}: {e}")
    except Exception as e:
        st.warning(f"Error scraping {url}: {e}")
    return list(emails_found)

def search_company_email_via_serpapi(company_name):
    """Search Google for 'company name email' and extract emails from snippets."""
    query = f'"{company_name}" email'
    st.info(f"🔎 Searching for emails with query: {query}")
    results = serpapi_Google_Search(query, pages=1, show_debug=False)
    for res in results:
        snippet = res.get("snippet", "")
        emails = extract_emails_from_text(snippet)
        if emails:
            st.success(f"📧 Found email for {company_name} via Google: {emails[0]}")
            return emails[0]
    st.warning(f" No emails found for {company_name} via Google search.")
    return None

def extract_company_from_snippet(title, snippet, link, debug=False):
    company = ""
    # 1. Try to extract from snippet using common patterns
    snippet_patterns = [
        r'works\s+(?:at|for)\s*[:\-]?\s*([A-Za-z0-9&.,\-\'\(\) ]+)',
        r'at\s*[:\-]?\s*([A-Za-z0-9&.,\-\'\(\) ]+)',
        r'@([A-Za-z0-9&.,\-\'\(\) ]+)',
        r'for\s*([A-Za-z0-9&.,\-\'\(\) ]+)',
        r'with\s*([A-Za-z0-9&.,\-\'\(\) ]+)',
    ]
    for pattern in snippet_patterns:
        match = re.search(pattern, snippet, re.IGNORECASE)
        if match:
            company = match.group(1).strip(" .,-:;")
            break
    # 2. If not found in snippet, try title (LinkedIn style)
    if not company:
        title_match = re.search(r'(?:at|@)\s*([A-Za-z0-9&.,\-\'\(\) ]+)', title, re.IGNORECASE)
        if title_match:
            company = title_match.group(1).strip(" .,-:;")
        else:
            parts = re.split(r'[|\-–—]', title)
            if len(parts) > 1:
                possible_company = parts[-1].strip()
                if re.search(r'(bank|finance|group|inc|ltd|llc|corp|company|pvt|gmbh|sa)', possible_company, re.IGNORECASE):
                    company = possible_company
    # 3. Clean up company name
    if company:
        company = re.sub(r'official website|careers|about us|linkedin|profile', '', company, flags=re.IGNORECASE).strip()
        company = re.sub(r'\b(llc|inc|ltd|corp|pvt|gmbh|sa)\b\.?', '', company, flags=re.IGNORECASE).strip()
        company = ' '.join(word.capitalize() for word in company.split())
        if len(company) < 3 or company.lower() in ['profile', 'official', 'website', 'careers']:
            company = ""
    if debug:
        st.write(f"Extracted company: {company}")
    return company

def parse_leads_from_results(results, debug_mode=True):
    leads = []
    if debug_mode:
        st.subheader("🔍 Parsing Individual Results:")
    for i, item in enumerate(results):
        title = item.get("title") or ""
        snippet = item.get("snippet") or ""
        link = item.get("link") or ""
        if debug_mode:
            with st.expander(f"Result {i+1}: {title[:50]}..."):
                st.write(f"**Title:** {title}")
                st.write(f"**Link:** {link}")
                st.write(f"**Snippet:** {snippet}")
                emails_in_snippet = extract_emails_from_text(snippet)
                valid_email = emails_in_snippet[0] if emails_in_snippet else ""
                if emails_in_snippet:
                    st.success(f"Found email in snippet: {valid_email}")
                else:
                    st.info("No email found in snippet")
                name = ""
                role = ""
                company = extract_company_from_snippet(title, snippet, link, debug=True)
                if "linkedin.com/in/" in link:
                    title_parts = re.split(r'[|\-–—]', title)
                    title_parts = [p.strip() for p in title_parts if p.strip() and 'linkedin' not in p.lower()]
                    if len(title_parts) >= 1:
                        name = title_parts[0].strip()
                    if len(title_parts) >= 2:
                        role_part = title_parts[1].strip()
                        role = re.sub(r'\s+at\s+.*', '', role_part, flags=re.IGNORECASE).strip()
                st.write(f"**Extracted Name:** {name}")
                st.write(f"**Extracted Role:** {role}")
                st.write(f"**Extracted Company:** {company}")
        else:
            emails_in_snippet = extract_emails_from_text(snippet)
            valid_email = emails_in_snippet[0] if emails_in_snippet else ""
            name = ""
            role = ""
            company = extract_company_from_snippet(title, snippet, link, debug=False)
            if "linkedin.com/in/" in link:
                title_parts = re.split(r'[|\-–—]', title)
                title_parts = [p.strip() for p in title_parts if p.strip() and 'linkedin' not in p.lower()]
                if len(title_parts) >= 1:
                    name = title_parts[0].strip()
                if len(title_parts) >= 2:
                    role_part = title_parts[1].strip()
                    role = re.sub(r'\s+at\s+.*', '', role_part, flags=re.IGNORECASE).strip()
        lead = {
            "Name": name,
            "Title": role,
            "Company": company,
            "Email": valid_email,
            "LinkedIn": link,
            "Snippet": snippet
        }
        leads.append(lead)
        # Insert into DB, skip duplicates
        insert_lead(lead)
    return leads

def fetch_company_website(company_name):
    query = f'"{company_name}" official website OR "{company_name}" contact'
    st.info(f"Searching for company website: `{query}`")
    results = serpapi_Google_Search(query, pages=1, show_debug=False)
    for res in results:
        link = res.get("link")
        if link:
            parsed_url = urllib.parse.urlparse(link)
            domain = parsed_url.netloc.lower()
            company_clean = company_name.lower().replace(" ", "").replace("-", "")
            domain_clean = domain.replace(".", "").replace("-", "")
            if company_clean in domain_clean and \
               not any(social in domain for social in ["linkedin", "facebook", "twitter", "youtube", "wikipedia", "glassdoor"]):
                return link
    return None

def generate_email_body(name: str, company: str, template: str) -> str:
    name_display = name.split(" ")[0] if name else "there"
    company_display = company if company else "your company"
    body = template.replace("{name}", name_display).replace("{company}", company_display)
    return body

def send_email(to_email: str, subject: str, body: str, smtp_details):
    msg = MIMEMultipart()
    msg["From"] = smtp_details["email"]
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP_SSL(smtp_details["server"], smtp_details["port"]) as server:
            server.login(smtp_details["email"], smtp_details["password"])
            server.send_message(msg)
        return True, None
    except smtplib.SMTPAuthenticationError:
        return False, "Authentication failed. Check your email and password, or use an App Password for Gmail."
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {e}"
    except Exception as e:
        return False, f"An unexpected error occurred: {e}"

def build_search_query(titles, region, company_type):
    titles_list = [t.strip() for t in titles.split(",") if t.strip()]
    parts = []
    if titles_list:
        if len(titles_list) == 1:
            parts.append(f'"{titles_list[0]}"')
        else:
            title_query = " OR ".join([f'"{t}"' for t in titles_list])
            parts.append(f"({title_query})")
    if region:
        parts.append(f'"{region}"')
    if company_type:
        parts.append(f'"{company_type}"')
    parts.append("site:linkedin.com/in")
    query = " ".join(parts)
    return query

# --- CRM Requirement Posts Search ---
def search_crm_requirement_posts(pages=1):
    query = '"need CRM" OR "require CRM" OR "looking for CRM" OR "CRM services required"'
    st.info(f"🔎 Searching for posts: {query}")
    results = serpapi_Google_Search(query, pages=pages, show_debug=False)
    posts = []
    for res in results:
        title = res.get("title", "")
        link = res.get("link", "")
        snippet = res.get("snippet", "")
        posts.append({
            "title": title,
            "link": link,
            "snippet": snippet
        })
    return posts

# --- Streamlit UI ---
st.sidebar.header("SMTP Configuration")
smtp_email = st.sidebar.text_input("📧 Your Email (SMTP)", value="your_email@example.com")
smtp_password = st.sidebar.text_input(" Email Password (or App Password)", type="password")
smtp_server = st.sidebar.text_input(" SMTP Server", value="smtp.gmail.com")
smtp_port = st.sidebar.number_input(" SMTP Port", value=465, step=1)

st.header("Lead Generation Criteria")
titles = st.text_input(" Titles (comma separated, e.g. CFO,CEO,CTO)", value="CFO,CEO")
region = st.text_input("Region (e.g. UAE, Pakistan)", value="UAE")
company_type = st.text_input(" Company Type (e.g. Bank, Tech, Finance)", value="Bank")
number_of_results = st.slider(" Number of Google pages to scrape", 1, 5, 2)

debug_mode = st.checkbox(" Enable Debug Mode", value=True)

st.header("Email Outreach Template")
user_prompt = st.text_area(
    "✍️ Email Template (use {name} for first name, {company} for company name)",
    placeholder="Subject: Partnership Opportunity\n\nHello {name} from {company},\n\nI wanted to introduce you to IFRS9...",
    value="Subject: Partnership Opportunity\n\nHello {name} from {company},\n\nI hope this message finds you well. I wanted to reach out to introduce our IFRS9 solutions.\n\nBest regards"
)

if st.button(" Scrape Leads"):
    if not all([smtp_email, smtp_password, smtp_server, smtp_port, user_prompt, titles]):
        st.error("❗ Please fill all required fields (SMTP details, Titles, Email Template).")
    else:
        st.session_state["smtp_details"] = {
            "email": smtp_email,
            "password": smtp_password,
            "server": smtp_server,
            "port": smtp_port
        }
        search_query = build_search_query(titles, region, company_type)
        st.info(f"🔎 Search Query: `{search_query}`")
        with st.spinner("Scraping LinkedIn leads from Google..."):
            raw_results = serpapi_Google_Search(search_query, number_of_results, show_debug=debug_mode)
            if not raw_results:
                st.error(" No results returned from SerpAPI. Check your API key and query.")
            else:
                leads = parse_leads_from_results(raw_results, debug_mode)
                if leads:
                    st.subheader("📋 All Leads Found:")
                    df_all = pd.DataFrame(leads)
                    st.dataframe(df_all)
                    leads_with_emails = [lead for lead in leads if lead["Email"]]
                    if leads_with_emails:
                        st.success(f"✅ Found {len(leads_with_emails)} leads with email addresses.")
                        st.session_state["leads"] = leads_with_emails
                    else:
                        st.warning(" No leads with emails found in snippets. Will try to find emails on company websites or Google...")
                        st.subheader(" Searching Company Websites and Google for Emails:")
                        progress_bar = st.progress(0)
                        scraped_websites = {}
                        for i, lead in enumerate(leads):
                            progress_bar.progress((i + 1) / len(leads))
                            if not lead["Email"] and lead["Company"]:
                                company_name = lead["Company"]
                                if company_name not in scraped_websites:
                                    company_website = fetch_company_website(company_name)
                                    if company_website:
                                        scraped_websites[company_name] = company_website
                                        st.info(f"🌐 Found website for {company_name}: {company_website}")
                                        emails_from_website = extract_emails_from_url(company_website)
                                        if emails_from_website:
                                            lead["Email"] = emails_from_website[0]
                                            st.success(f" Found email: {lead['Email']}")
                                        else:
                                            st.write(f"⚠️ No emails found on {company_website}")
                                    else:
                                        st.warning(f"⚠️ Could not find website for: {company_name}")
                                if not lead["Email"]:
                                    # Try Google search for company email
                                    email_from_google = search_company_email_via_serpapi(company_name)
                                    if email_from_google:
                                        lead["Email"] = email_from_google
                            time.sleep(random.uniform(0.5, 1.5))
                            # Insert updated lead into DB
                            insert_lead(lead)
                        final_leads = [lead for lead in leads if lead["Email"]]
                        st.session_state["leads"] = final_leads
                        if final_leads:
                            st.success(f"✅ Final count: {len(final_leads)} leads with email addresses.")
                            df_final = pd.DataFrame(final_leads)
                            st.dataframe(df_final)
                        else:
                            st.error(" No leads with valid email addresses found.")
                else:
                    st.error(" No leads could be parsed from the search results.")

if "leads" in st.session_state and st.session_state["leads"] and st.button("✍️ Generate Email Drafts"):
    email_drafts = []
    for lead in st.session_state["leads"]:
        if lead["Email"]:
            subject = user_prompt.split('\n')[0].replace("Subject:", "").strip() if user_prompt.startswith("Subject:") else "Quick Introduction"
            body_template_only = "\n".join(user_prompt.split('\n')[1:]).strip() if user_prompt.startswith("Subject:") else user_prompt.strip()
            body = generate_email_body(lead["Name"], lead["Company"], body_template_only)
            email_drafts.append({
                "name": lead["Name"],
                "company": lead["Company"],
                "email": lead["Email"],
                "subject": subject,
                "body": body
            })
    st.session_state["email_drafts"] = email_drafts
    st.success(f"Generated drafts for {len(email_drafts)} emails. Review them below.")
    for i, draft in enumerate(email_drafts):
        with st.expander(f"Draft for {draft['name']} at {draft['company']} ({draft['email']})"):
            st.write(f"**Subject:** {draft['subject']}")
            st.code(draft['body'], language='text')

if "email_drafts" in st.session_state and st.session_state["email_drafts"] and st.button("🚀 Send Emails"):
    smtp_details = st.session_state.get("smtp_details")
    if not smtp_details:
        st.error("❗ SMTP details not found. Please scrape leads again to set them.")
    else:
        st.info(f"Attempting to send {len(st.session_state['email_drafts'])} emails...")
        send_progress_bar = st.progress(0)
        sent_count = 0
        for i, draft in enumerate(st.session_state["email_drafts"]):
            success, error_msg = send_email(draft["email"], draft["subject"], draft["body"], smtp_details)
            if success:
                st.success(f"Email sent to {draft['email']}")
                sent_count += 1
            else:
                st.error(f"Failed to send email to {draft['email']}: {error_msg}")
            send_progress_bar.progress((i + 1) / len(st.session_state["email_drafts"]))
            time.sleep(random.uniform(2, 5))
        st.success(f"Finished sending. {sent_count} emails successfully sent.")
        del st.session_state["email_drafts"]
        del st.session_state["leads"]

# --- CRM Requirement Posts UI ---
st.header("🔗 CRM Requirement Posts Search")
if st.button("🔍 Find CRM Requirement Posts"):
    posts = search_crm_requirement_posts(pages=2)
    if posts:
        st.success(f"Found {len(posts)} posts about CRM requirements.")
        for post in posts:
            st.markdown(f"- [{post['title']}]({post['link']})")
            if post['snippet']:
                st.caption(post['snippet'])
    else:
        st.warning("No relevant posts found.")
