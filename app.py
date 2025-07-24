# app.py
import os
import time
import csv
from flask import Flask, request, render_template, redirect, url_for, flash, send_file
from serpapi import GoogleSearch
from scrapy_scraper import scrape_emails_google
from email_sender import send_personalized_email

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev_secret")

SERPAPI_KEY = os.getenv("SERPAPI_KEY")

leads = []

def extract_phone(snippet):
    import re
    pattern = r'(\+?\d[\d\s\-\(\)]{7,}\d)'
    matches = re.findall(pattern, snippet)
    return matches[0] if matches else "Not found"

@app.route("/", methods=["GET", "POST"])
def index():
    global leads
    leads = []

    if request.method == "POST":
        title_kw = request.form.get("title", "").strip()
        region_kw = request.form.get("region", "").strip()
        comp_type = request.form.get("company_type", "").strip()
        num_results = int(request.form.get("num_results", "10"))

        if not title_kw or not region_kw or not comp_type:
            flash("Please fill in all input fields.", "error")
            return render_template("index.html")

        job_titles = [f'"{t.strip()}"' for t in title_kw.split(",") if t.strip()]
        query = " ".join(job_titles + [region_kw, comp_type]) + " site:linkedin.com/in"

        params = {
            "engine": "google",
            "q": query,
            "api_key": SERPAPI_KEY,
            "num": 10,
            "gl": "us",
            "hl": "en",
        }

        collected = 0
        page = 0
        while collected < num_results and page < 5:
            params["start"] = page * 10
            try:
                res = GoogleSearch(params).get_dict()
                results = res.get("organic_results", [])
            except Exception as e:
                flash(f"Error during SerpAPI request: {e}", "error")
                break

            if not results:
                break

            for r in results:
                if collected >= num_results:
                    break

                link = r.get("link", "")
                if "linkedin.com/in" not in link:
                    continue

                title = r.get("title", "")
                snippet = r.get("snippet", "")

                name = title.split(" - ")[0].strip() if " - " in title else title.split("|")[0].strip()
                raw_title = (
                    title.split(" - ")[1].strip()
                    if " - " in title
                    else (title.split("|")[1].strip() if "|" in title else "Unknown")
                )
                company = extract_company_from_title(raw_title)

                email = scrape_emails_google(name, company)
                phone = extract_phone(snippet)

                lead = {
                    "name": name,
                    "title": raw_title,
                    "company": company,
                    "linkedin": link,
                    "email": email or "Not found",
                    "contact": phone,
                }
                leads.append(lead)
                collected += 1
                time.sleep(1.5)

            page += 1

        if leads:
            keys = leads[0].keys()
            with open("leads_output.csv", "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(leads)
            flash(f"Scraped {len(leads)} leads successfully!", "success")
        else:
            flash("No leads found. Try different search terms or increase results count.", "warning")

    return render_template("index.html", leads=leads)

def extract_company_from_title(title_str):
    if " at " in title_str:
        return title_str.split(" at ")[-1].strip()
    return title_str.strip()

@app.route("/download_csv")
def download_csv():
    if os.path.exists("leads_output.csv"):
        return send_file("leads_output.csv", as_attachment=True)
    flash("CSV file not found.", "error")
    return redirect(url_for("index"))

@app.route("/send_emails", methods=["GET", "POST"])
def send_emails():
    if request.method == "POST":
        subject = request.form.get("subject", "Hello!")
        msg = request.form.get("message", "")
        sent = 0

        sender_email = os.getenv("SENDER_EMAIL")
        sender_password = os.getenv("SENDER_PASSWORD")

        if not sender_email or not sender_password:
            flash("Sender email credentials not configured.", "error")
            return redirect(url_for("send_emails"))

        for lead in leads:
            email = lead.get("email", "")
            if email and email != "Not found":
                personalized_msg = msg \
                    .replace("{{name}}", lead["name"]) \
                    .replace("{{company}}", lead["company"]) \
                    .replace("{{linkedin}}", lead.get("linkedin", "")) \
                    .replace("{{contact}}", lead.get("contact", ""))

                ok = send_personalized_email(sender_email, sender_password, email, subject, personalized_msg)
                if ok:
                    sent += 1
                time.sleep(2)

        flash(f"Sent {sent} emails.", "success")
        return redirect(url_for("send_emails"))

    return render_template("send_emails.html", leads=leads)

if __name__ == "__main__":
    app.run(debug=True)
