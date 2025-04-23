#!/usr/bin/env python3
import asyncio
import logging
import os
import sqlite3
import csv
import json

import pdfplumber

from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError

# Import AgentQL and its query_data function from the AgentQL SDK.
try:
    from agentql import Agent, configure
except ImportError:
    logging.error("AgentQL package not installed. Please install it via pip (pip install agentql).")
    raise

# ------------------------------
# Configuration & Logging Setup
# ------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scrappy.log")
    ]
)

DB_NAME = "byod_plans.db"
CSV_NAME = "byod_plans.csv"

# Configure AgentQL with your API key.
AGENTQL_API_KEY = os.getenv("WXbJUk1ILcVB0sXdwzyO_aVhkMMSjnB2xK0vAm9FDzVQP9_avwUGZQ")
if not AGENTQL_API_KEY:
    logging.error("AGENTQL_API_KEY not set in environment.")
    raise Exception("AGENTQL_API_KEY not set")
configure({"apiKey": AGENTQL_API_KEY})


# ------------------------------
# Database Functions
# ------------------------------
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            carrier TEXT,
            plan_name TEXT,
            data_gb TEXT,
            price TEXT,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    logging.info("Database initialized.")


def store_plans(plans):
    if not plans:
        logging.warning("No plans to store in the database.")
        return
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    for plan in plans:
        c.execute("""
            INSERT INTO plans (carrier, plan_name, data_gb, price)
            VALUES (?, ?, ?, ?)
        """, (plan.get("carrier"), plan.get("plan_name"), plan.get("data_gb"), plan.get("price")))
    conn.commit()
    conn.close()
    logging.info(f"Stored {len(plans)} plan(s) in the database.")


def save_csv(plans, filename=CSV_NAME):
    if not plans:
        logging.warning("No plans to save in CSV.")
        return
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["carrier", "plan_name", "data_gb", "price"])
        writer.writeheader()
        for plan in plans:
            writer.writerow(plan)
    logging.info(f"Saved {len(plans)} plan(s) in CSV file: {filename}")


# ------------------------------
# PDF Text Extraction
# ------------------------------
def extract_text_from_pdf(pdf_path):
    """Extract text from the PDF using pdfplumber (no OCR fallback)."""
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"
    except Exception as e:
        logging.error(f"Error extracting text from {pdf_path}: {e}")
    return text


# ------------------------------
# AgentQL Extraction Function
# ------------------------------
def extract_plans_with_agentql(pdf_text, carrier):
    """
    Use AgentQL’s query_data function to extract plan details from the provided text.
    The query instructs AgentQL to extract a JSON array of objects with keys:
      - plan_name
      - data_gb
      - price
    We add the carrier key to each result.
    """
    query = """
Extract all mobile BYOD plan details from the following text.
Each plan should have the keys "plan_name", "data_gb", and "price".
Return only a JSON array.
Text:
{{text}}
"""
    try:
        result = query_data(query, {"text": pdf_text})
        data = json.loads(result)
        for item in data:
            item["carrier"] = carrier
        return data
    except Exception as e:
        logging.error(f"AgentQL extraction failed for {carrier}: {e}")
        return []


# ------------------------------
# PDF Generation with Playwright
# ------------------------------
async def generate_pdf(page, pdf_path):
    """Scroll the page to load all content and generate a one‑page PDF."""
    for _ in range(5):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1)
    width_pixels = await page.evaluate("document.body.scrollWidth")
    height_pixels = await page.evaluate("document.body.scrollHeight")
    paper_width = width_pixels / 96.0
    paper_height = height_pixels / 96.0 + 0.5
    logging.info(f"Generating PDF with dimensions: {paper_width:.2f}in x {paper_height:.2f}in")
    try:
        await page.pdf(
            path=pdf_path,
            width=f"{paper_width}in",
            height=f"{paper_height}in",
            print_background=True
        )
    except Exception as e:
        logging.error(f"PDF generation error for {pdf_path}: {e}")


# ------------------------------
# Carrier Processing Function
# ------------------------------
async def process_carrier(playwright, carrier_config):
    """
    For the given carrier, navigate to its URL (and perform extra actions if needed),
    generate a one‑page PDF, extract text from the PDF, and use AgentQL to extract
    structured plan details.
    """
    carrier = carrier_config["carrier"]
    url = carrier_config["url"]
    pdf_path = carrier_config.get("pdf_path", f"{carrier.lower()}.pdf")
    extra_actions = carrier_config.get("extra_actions", [])

    logging.info(f"{carrier}: Processing URL: {url}")
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context()
    page = await context.new_page()

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        logging.error(f"{carrier}: Error loading URL {url}: {e}")
        await browser.close()
        return []

    # Perform extra actions if specified (e.g., click region selectors)
    for action in extra_actions:
        try:
            selector = action["selector"]
            await page.click(selector, timeout=5000)
            await asyncio.sleep(action.get("sleep", 2))
        except Exception as e:
            logging.warning(f"{carrier}: Extra action failed: {e}")

    await asyncio.sleep(3)
    await generate_pdf(page, pdf_path)
    await browser.close()
    logging.info(f"{carrier}: PDF saved as {pdf_path}")

    pdf_text = extract_text_from_pdf(pdf_path)
    logging.info(f"{carrier}: Extracted text length: {len(pdf_text)} characters")

    plans = extract_plans_with_agentql(pdf_text, carrier)
    if plans:
        logging.info(f"{carrier}: Extracted {len(plans)} plan(s) via AgentQL.")
    else:
        logging.warning(f"{carrier}: No plan details extracted by AgentQL.")
    return plans


# ------------------------------
# Main Pipeline
# ------------------------------
async def main():
    init_db()
    # Process only Rogers, Fido, Virgin, and Chatr.
    carrier_configs = [
        {
            "carrier": "Rogers",
            "url": "https://www.rogers.com/phones/bring-your-own-device?icid=R_WIR_CMH_PL5IQK&flowType=byod",
            "pdf_path": "rogers.pdf"
        },
        {
            "carrier": "Fido",
            "url": "https://www.fido.ca/phones/bring-your-own-device?flowType=byod",
            "pdf_path": "fido.pdf"
        },
        {
            "carrier": "Virgin",
            "url": "https://www.virginplus.ca/en/plans/postpaid.html#!/BYOP/research",
            "pdf_path": "virgin.pdf",
            "extra_actions": [
                {"action": "click", "selector": "button:has-text('Ontario')", "sleep": 2}
            ]
        },
        {
            "carrier": "Chatr",
            "url": "https://www.chatrwireless.com/plans?ecid=PS_C0143_C_WIR_Jan_25_ALS_H5HS6V&gclsrc=aw.ds&gad_source=1&gbraid=0AAAAADPUjHKX-jEJrXYzGkjjXwQ0gan58&gclid=CjwKCAiAwaG9BhAREiwAdhv6Y-4Pqj980gTNAq-uuMwO2ea2JijBq-X5Beu41WJT29aWlZF_OGn_uRoCucQQAvD_BwE",
            "pdf_path": "chatr.pdf"
        }
    ]

    all_plans = []
    async with async_playwright() as playwright:
        for config in carrier_configs:
            try:
                plans = await process_carrier(playwright, config)
                logging.info(f"{config['carrier']}: Total plans extracted: {len(plans)}")
                all_plans.extend(plans)
            except Exception as e:
                logging.error(f"Error processing {config.get('carrier')}: {e}")

    if all_plans:
        store_plans(all_plans)
        save_csv(all_plans)
        logging.info(f"Scraping completed. Total plans scraped: {len(all_plans)}")
    else:
        logging.error("No plans were scraped. Please review the logs for details.")


if __name__ == "__main__":
    asyncio.run(main())