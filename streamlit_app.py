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

init_db()

# --- Config ---
st.set_page_config(page_title="Email Outreach Tool", layout="centered")
st.markdown("<h3 style='text-align: left;'> FineIT's Automated Email Outreach for CRM by M.Ahmad </h3>", unsafe_allow_html=True)

GOOGLE_API_KEY = "AIzaSyBs5HgWW2jStcf7963KpYROxLut6WTYD-U"
CSE_ID = "c22b958e8780f493d"

EMAIL_REGEX = re.compile(r'''
    \b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b
''', re.VERBOSE)

BLOCKED_DOMAINS = {
    "ingest.sentry.io", "example.com", "test.com", "tempmail.com", "disposablemail.com",
    "protonmail.com", "gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
    "aol.com", "icloud.com", "live.com",
}

TITLE_KEYWORDS = [
    "CEO", "President", "CFO", "Chairman", "Executive Vice President", "Head", "Founder",
    "Senior Executive Vice President", "Group Head", "Board Member", "Director", "Manager",
    "Vice President", "Chief", "Officer", "Partner", "Owner"
]

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

def google_custom_search(query, pages=1, show_debug=True):
    all_results = []
    if show_debug:
        progress_bar = st.progress(0)
    for page in range(pages):
        if show_debug:
            progress_bar.progress((page) / pages)
        start = page * 10 + 1
        params = {
            "key": GOOGLE_API_KEY,
            "cx": CSE_ID,
            "q": query,
            "start": start,
            "num": 10,
            "hl": "en",
            "gl": "us"
        }
        if show_debug:
            st.write(f"**Page {page+1}:** Making request with params:")
            st.json(params)
        try:
            response = requests.get("https://www.googleapis.com/customsearch/v1", params=params, timeout=15)
            if show_debug:
                st.write(f"**Response Status:** {response.status_code}")
            if response.status_code == 403:
                st.error("❌ Forbidden: Check your API key and CSE ID")
                break
            elif response.status_code == 429:
                st.error("❌ Too many requests: Rate limit exceeded")
                break
            elif response.status_code != 200:
                st.error(f"❌ HTTP {response.status_code}: {response.text[:200]}")
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
            results = data.get("items", [])
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

def search_company_email_via_google(company_name):
    query = f'"{company_name}" email'
    st.info(f"🔎 Searching for emails with query: {query}")
    results = google_custom_search(query, pages=1, show_debug=False)
    for res in results:
        snippet = res.get("snippet", "")
        emails = extract_emails_from_text(snippet)
        if emails:
            st.success(f"📧 Found email for {company_name} via Google: {emails[0]}")
            return emails[0]
    st.warning(f" No emails found for {company_name} via Google search.")
    return None

def extract_company_and_title(title, snippet, link):
    # Improved extraction logic
    company = ""
    role = ""
    name = ""

    # Try to extract name from LinkedIn title
    if "linkedin.com/in/" in link:
        title_parts = re.split(r'[|\-–—]', title)
        title_parts = [p.strip() for p in title_parts if p.strip() and 'linkedin' not in p.lower()]
        if len(title_parts) >= 1:
            name = title_parts[0]
        # Try to extract role from title parts
        for part in title_parts:
            for keyword in TITLE_KEYWORDS:
                if keyword.lower() in part.lower():
                    role = part
                    break
            if role:
                break
        # Try to extract company from title parts
        for part in title_parts[::-1]:
            if not any(keyword.lower() in part.lower() for keyword in TITLE_KEYWORDS) and len(part.split()) > 1:
                company = part
                break
    else:
        # Fallback: Try to extract name from start of title
        name_match = re.match(r"^([A-Za-z .'-]+)", title)
        if name_match:
            name = name_match.group(1).strip()
        # Try to extract role from title
        for keyword in TITLE_KEYWORDS:
            role_match = re.search(rf"\b{keyword}\b", title, re.IGNORECASE)
            if role_match:
                role = role_match.group(0)
                break
        # Try to extract company from title or snippet
        company_match = re.search(r"at\s+([A-Za-z0-9&.\-\'\(\) ]+)", title)
        if not company_match:
            company_match = re.search(r"at\s+([A-Za-z0-9&.\-\'\(\) ]+)", snippet)
        if company_match:
            company = company_match.group(1).strip()
        else:
            # Try to extract company from snippet using common patterns
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

    # Clean company and role
    if company:
        company = re.sub(r'official website|careers|about us|linkedin|profile', '', company, flags=re.IGNORECASE).strip()
        company = re.sub(r'\b(llc|inc|ltd|corp|pvt|gmbh|sa)\b\.?', '', company, flags=re.IGNORECASE).strip()
        company = ' '.join(word.capitalize() for word in company.split())
        if len(company) < 3 or company.lower() in ['profile', 'official', 'website', 'careers']:
            company = ""
    if role:
        role = role.strip(" .,-:;")
    if name:
        name = name.strip(" .,-:;")
    return name, role, company

def parse_leads_from_results(results, debug_mode=True):
    leads = []
    if debug_mode:
        st.subheader("🔍 Parsing Individual Results:")
    for i, item in enumerate(results):
        title = item.get("title") or ""
        snippet = item.get("snippet") or ""
        link = item.get("link") or ""
        name, role, company = extract_company_and_title(title, snippet, link)
        emails_in_snippet = extract_emails_from_text(snippet)
        valid_email = emails_in_snippet[0] if emails_in_snippet else ""
        lead = {
            "Name": name,
            "Title": role,
            "Company": company,
            "Email": valid_email,
            "LinkedIn": link,
            "Snippet": snippet
        }
        leads.append(lead)
        insert_lead(lead)
        if debug_mode:
            with st.expander(f"Result {i+1}: {name} - {role} - {company}"):
                st.write(lead)
    return leads

def fetch_company_website(company_name):
    query = f'"{company_name}" official website OR "{company_name}" contact'
    st.info(f"Searching for company website: `{query}`")
    results = google_custom_search(query, pages=1, show_debug=False)
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
    company_types_list = [c.strip() for c in company_type.split(",") if c.strip()]
    parts = []
    if titles_list:
        if len(titles_list) == 1:
            parts.append(f'"{titles_list[0]}"')
        else:
            title_query = " OR ".join([f'"{t}"' for t in titles_list])
            parts.append(f"({title_query})")
    if region:
        parts.append(f'"{region}"')
    if company_types_list:
        if len(company_types_list) == 1:
            parts.append(f'"{company_types_list[0]}"')
        else:
            company_query = " OR ".join([f'"{c}"' for c in company_types_list])
            parts.append(f"({company_query})")
    parts.append("site:linkedin.com/in")
    query = " ".join(parts)
    return query

# --- Streamlit UI ---
st.sidebar.header("SMTP Configuration")
smtp_email = st.sidebar.text_input("📧 Your Email (SMTP)", value="your_email@example.com")
smtp_password = st.sidebar.text_input(" Email Password (or App Password)", type="password")
smtp_server = st.sidebar.text_input(" SMTP Server", value="smtp.gmail.com")
smtp_port = st.sidebar.number_input(" SMTP Port", value=465, step=1)

st.header("Lead Generation Criteria")
titles = st.text_input(" Titles (comma separated, e.g. CFO,CEO,CTO)", value="CFO,CEO")
region = st.text_input("Region (e.g. UAE, Pakistan)", value="UAE")
company_type = st.text_input(" Company Type (comma separated, e.g. Bank, Tech, Finance)", value="Bank")
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
            raw_results = google_custom_search(search_query, number_of_results, show_debug=debug_mode)
            if not raw_results:
                st.error(" No results returned from Google Custom Search. Check your API key, CSE ID, and query.")
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
                                    email_from_google = search_company_email_via_google(company_name)
                                    if email_from_google:
                                        lead["Email"] = email_from_google
                            time.sleep(random.uniform(0.5, 1.5))
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

# --- Dynamic Post Search ---
st.header("🔗 Dynamic Post Search")
post_query = st.text_input(
    "Enter any post/topic to search (e.g. 'IFRS9 services required', 'IFRS 17 services needed', etc.)",
    value="IFRS9 services required"
)
post_pages = st.slider("Number of Google pages to scrape for posts", 1, 5, 2)

if st.button("🔍 Scrape Posts"):
    if not post_query.strip():
        st.error("Please enter a search query for posts.")
    else:
        st.info(f"🔎 Searching for posts: {post_query}")
        post_results = google_custom_search(post_query, pages=post_pages, show_debug=debug_mode)
        if post_results:
            st.success(f"Found {len(post_results)} posts.")
            for post in post_results:
                st.markdown(f"- [{post['title']}]({post['link']})")
                if post['snippet']:
                    st.caption(post['snippet'])
        else:
            st.warning("No relevant posts found.")
