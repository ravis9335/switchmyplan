#!/usr/bin/env python3
import asyncio
import json
import csv
import os
import re

import agentql
from agentql.ext.playwright.async_api import Page
from playwright.async_api import async_playwright


# -------------------------------------------------
# 1) Virgin
# -------------------------------------------------
async def scrape_virgin(page: Page) -> list:
    url = "https://www.virginplus.ca/en/plans/postpaid.html#!/BYOP/research"
    print(f"Scraping Virgin BYOP from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(6000)

    query = """
    {
      plans[] {
        plan_name
        plan_price
        plan_data
        plan_features
      }
    }
    """
    response = await page.query_data(query)
    return response.get("plans", [])


# -------------------------------------------------
# 2) Koodo
# -------------------------------------------------
async def scrape_koodo(page: Page) -> list:
    url = "https://www.koodomobile.com/en/rate-plans?INTCMP=KMNew_NavMenu_Shop_Plans"
    print(f"Scraping Koodo BYOP from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(6000)

    query = """
    {
      plans[] {
        plan_name
        plan_price
        plan_data
       plan_features[]
      }
    }
    """
    response = await page.query_data(query)
    return response.get("plans", [])


# -------------------------------------------------
# 3) Fido
# -------------------------------------------------
async def scrape_fido(page: Page) -> list:
    url = "https://www.fido.ca/phones/bring-your-own-device?icid=F_WIR_CNV_GRM6LG&flowType=byod"
    print(f"Scraping Fido BYOD from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)

    all_plans = []
    query = """
    {
      plans[] {
        plan_name
        plan_price
        plan_data
        plan_features
      }
    }
    """
    # Default (Data, Talk & Text)
    response = await page.query_data(query)
    default_plans = response.get("plans", [])
    all_plans.extend(default_plans)

    # Talk & Text
    try:
        talk_text_button = await page.get_by_prompt("the Talk & Text option/tab")
        if talk_text_button:
            await talk_text_button.click()
            await page.wait_for_timeout(2000)
            resp_talk_text = await page.query_data(query)
            talk_text_plans = resp_talk_text.get("plans", [])
            all_plans.extend(talk_text_plans)
    except:
        print("Couldn't select 'Talk & Text' tab on Fido.")

    # Basic
    try:
        basic_button = await page.get_by_prompt("the Basic option/tab")
        if basic_button:
            await basic_button.click()
            await page.wait_for_timeout(2000)
            resp_basic = await page.query_data(query)
            basic_plans = resp_basic.get("plans", [])
            all_plans.extend(basic_plans)
    except:
        print("Couldn't select 'Basic' tab on Fido.")

    return all_plans


# -------------------------------------------------
# 4) Rogers
# -------------------------------------------------
async def scrape_rogers(page: Page) -> list:
    url = "https://www.rogers.com/phones/bring-your-own-device?icid=R_WIR_CMH_PL5IQK&flowType=byod"
    print(f"Scraping Rogers BYOD from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)

    all_plans = []
    query = """
    {
      plans[] {
        plan_name
        plan_price
        plan_data
        plan_features
      }
    }
    """
    # 5G Infinite
    response = await page.query_data(query)
    infinite_plans = response.get("plans", [])
    all_plans.extend(infinite_plans)

    # Talk & Text
    try:
        talk_text_button = await page.get_by_prompt("the Talk & Text plan option")
        if talk_text_button:
            await talk_text_button.click()
            await page.wait_for_timeout(2000)
            resp_talk_text = await page.query_data(query)
            talk_text_plans = resp_talk_text.get("plans", [])
            all_plans.extend(talk_text_plans)
    except:
        print("Couldn't select 'Talk & Text' tab on Rogers.")

    return all_plans


# -------------------------------------------------
# 5) Bell
# -------------------------------------------------
async def scrape_bell(page: Page) -> list:
    url = "https://www.bell.ca/Mobility/Bring-Your-Own-Phone"
    print(f"Scraping Bell from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(6000)

    # Click "Select a plan"
    try:
        select_plan_button = await page.get_by_prompt("Select a plan")
        if select_plan_button:
            await select_plan_button.click()
            await page.wait_for_timeout(3000)
    except Exception as e:
        print("Couldn't click 'Select a plan' on Bell.", e)

    # Wait for the pop-up and click "I'm new to Bell"
    try:
        new_to_bell_button = await page.get_by_prompt("I'm new to Bell")
        if new_to_bell_button:
            await new_to_bell_button.click()
            # Wait 8 seconds for the plans page to load after the pop-up
            await page.wait_for_timeout(18000)
    except Exception as e:
        print("Couldn't select 'I'm new to Bell' on the pop-up.", e)

    query = """
    {
      plans[] {
        plan_name
        plan_price
        plan_data
        plan_features
      }
    }
    """
    response = await page.query_data(query)
    return response.get("plans", [])


# -------------------------------------------------
# 6) Telus
# -------------------------------------------------
async def scrape_telus(page: Page) -> list:
    url = "https://www.telus.com/en/mobility/plans?linkname=Plans&linktype=ge-meganav"
    print(f"Scraping Telus from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)

    query = """
    {
      plans[] {
        plan_name
        plan_price
        plan_data
        plan_features
      }
    }
    """
    response = await page.query_data(query)
    return response.get("plans", [])


# -------------------------------------------------
# 7) Freedom
# -------------------------------------------------
async def scrape_freedom(page: Page) -> list:
    url = "https://shop.freedommobile.ca/en-CA/plans?isByopPlanFirstFlow=true"
    print(f"Scraping Freedom plans from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    query = """
    {
      plans[] {
        plan_name
        plan_price
        plan_data
        plan_features
      }
    }
    """
    response = await page.query_data(query)
    return response.get("plans", [])


# -------------------------------------------------
# 8) Chatr
# -------------------------------------------------
async def scrape_chatr(page: Page) -> list:
    url = "https://www.chatrwireless.com/plans"
    print(f"Scraping Chatr plans from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    query = """
    {
      plans[] {
        plan_name
        plan_price
        plan_data
        plan_features
      }
    }
    """
    response = await page.query_data(query)
    return response.get("plans", [])


# -------------------------------------------------
# 9) Public Mobile
# -------------------------------------------------
async def scrape_public_mobile(page: Page) -> list:
    url = "https://publicmobile.ca/en/plans?gclsrc=aw.ds&ds_rl=1268486&gad_source=1&gbraid=0AAAAADSQ_GpZ1RGGfMVRSIMt-u8bIrfWF&gclid=Cj0KCQjwy46_BhDOARIsAIvmcwMYcKBvjSne8obNP6aZTej_7XqDitCLzrxIK_-BCx7g2-E2_aVNf6kaAgFzEALw_wcB"
    print(f"Scraping Public Mobile plans from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    query = """
    {
      plans[] {
        plan_name
        plan_price
        plan_data
        plan_features
      }
    }
    """
    response = await page.query_data(query)
    return response.get("plans", [])


# -------------------------------------------------
# 10) Freedom Prepaid
# -------------------------------------------------
async def scrape_freedom_prepaid(page: Page) -> list:
    # Using a different URL for prepaid plans (assumed query parameter)
    url = "https://shop.freedommobile.ca/en-CA/prepaid-plans"
    print(f"Scraping Freedom prepaid plans from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    query = """
    {
      plans[] {
        plan_name
        plan_price
        plan_data
        plan_features
      }
    }
    """
    response = await page.query_data(query)
    return response.get("plans", [])


# -------------------------------------------------
# MAIN
# -------------------------------------------------
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)

        # 1) Virgin
        virgin_page = await agentql.wrap_async(browser.new_page())
        virgin_plans = await scrape_virgin(virgin_page)

        # 2) Koodo
        koodo_page = await agentql.wrap_async(browser.new_page())
        koodo_plans = await scrape_koodo(koodo_page)

        # 3) Fido
        fido_page = await agentql.wrap_async(browser.new_page())
        fido_plans = await scrape_fido(fido_page)

        # 4) Rogers
        rogers_page = await agentql.wrap_async(browser.new_page())
        rogers_plans = await scrape_rogers(rogers_page)

        # 5) Bell
        bell_page = await agentql.wrap_async(browser.new_page())
        bell_plans = await scrape_bell(bell_page)

        # 6) Telus
        telus_page = await agentql.wrap_async(browser.new_page())
        telus_plans = await scrape_telus(telus_page)

        # 7) Freedom
        freedom_page = await agentql.wrap_async(browser.new_page())
        freedom_plans = await scrape_freedom(freedom_page)

        # 8) Chatr
        chatr_page = await agentql.wrap_async(browser.new_page())
        chatr_plans = await scrape_chatr(chatr_page)

        # 9) Public Mobile
        public_mobile_page = await agentql.wrap_async(browser.new_page())
        public_mobile_plans = await scrape_public_mobile(public_mobile_page)

        # 10) Freedom Prepaid
        freedom_prepaid_page = await agentql.wrap_async(browser.new_page())
        freedom_prepaid_plans = await scrape_freedom_prepaid(freedom_prepaid_page)

        # Combine all data
        all_data = {
            "virgin": virgin_plans,
            "koodo": koodo_plans,
            "fido": fido_plans,
            "rogers": rogers_plans,
            "bell": bell_plans,
            "telus": telus_plans,
            "freedom": freedom_plans,
            "chatr": chatr_plans,
            "public_mobile": public_mobile_plans,
            "freedom_prepaid": freedom_prepaid_plans,
        }

        print("\n=== Combined JSON ===")
        print(json.dumps(all_data, indent=2))

        # Save to CSV with cleaned data
        csv_path = "byop_plans.csv"
        save_plans_to_csv(all_data, csv_path)
        print(f"Saved CSV to {csv_path}")

        await browser.close()


def save_plans_to_csv(all_data: dict, csv_filename: str):
    """
    all_data is a dict of {carrier: [ {plan_name, plan_price, plan_data, plan_features}, ...], ...}.
    We'll flatten it into rows with 'carrier', 'plan_type', 'plan_name', 'plan_price', 'plan_data', and 'plan_features'.
    The 'plan_data' field is converted to a numeric value (in GB) for analysis.
    For carriers other than Chatr and Koodo, plan_features will be formatted as bullet points.
    """

    def parse_plan_data(data_str: str) -> float:
        """
        Convert data string into a numeric GB value.
        - "xGB" returns float(x)
        - "xMB" returns float(x) / 1024
        - If no usable number is found, return 0.0
        """
        if not data_str or data_str.strip() == "":
            return 0.0  # no data available
        data_lower = data_str.lower().strip()
        match = re.search(r'([\d\.]+)\s*(gb|mb)', data_lower)
        if match:
            numeric_value = float(match.group(1))
            unit = match.group(2)
            if unit == "gb":
                return numeric_value
            elif unit == "mb":
                return numeric_value / 1024.0
        return 0.0

    rows = []
    # Define carriers with prepaid plans
    prepaid_carriers = ["chatr", "public_mobile", "freedom_prepaid"]

    for carrier, plans_list in all_data.items():
        # Determine the plan type based on the carrier
        plan_type = "prepaid" if carrier in prepaid_carriers else "postpaid"
        for plan in plans_list:
            plan_name = (plan.get("plan_name", "") or "").strip()
            plan_price = str(plan.get("plan_price", "")).strip()
            plan_data_str = str(plan.get("plan_data", "") or "").strip()
            numeric_data = parse_plan_data(plan_data_str)

            # Process plan_features based on the carrier
            raw_features = plan.get("plan_features", "")
            if carrier not in ["chatr", "koodo"]:
                # If features is a list, join them as bullet points
                if isinstance(raw_features, list):
                    formatted_features = "\n".join(f"• {feature}" for feature in raw_features)
                # If it's a string, split it on common delimiters and join as bullet points
                elif isinstance(raw_features, str):
                    features_list = re.split(r"[,;]", raw_features)
                    features_list = [feat.strip() for feat in features_list if feat.strip()]
                    formatted_features = "\n".join(f"• {feat}" for feat in features_list)
                else:
                    formatted_features = ""
            else:
                # For Chatr and Koodo, keep the features as they are (or join if it's a list)
                if isinstance(raw_features, list):
                    formatted_features = ", ".join(raw_features)
                else:
                    formatted_features = raw_features

            row = {
                "carrier": carrier,
                "plan_type": plan_type,
                "plan_name": plan_name,
                "plan_price": plan_price,
                "plan_data": numeric_data,
                "plan_features": formatted_features
            }
            rows.append(row)

    fieldnames = ["carrier", "plan_type", "plan_name", "plan_price", "plan_data", "plan_features"]
    with open(csv_filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    asyncio.run(main())

