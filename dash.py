#!/usr/bin/env python3
import asyncio
import json
import csv
import re

from playwright.async_api import async_playwright, Page


# -------------------
# Helper: Save to CSV
# -------------------
def save_plans_to_csv(all_data: dict, csv_filename: str):
    """
    Expects all_data to be a dict of:
        {
            "carrier_name": [
                { "plan_name": ..., "plan_price": ..., "plan_data": ..., "plan_features": ... },
                ...
            ],
            ...
        }
    Writes rows with columns:
        carrier, plan_type, plan_name, plan_price, plan_data, plan_features
    """

    def parse_plan_data(data_str: str) -> float:
        """
        Convert data string into a numeric GB value.
        - "xGB" returns float(x)
        - "xMB" returns float(x)/1024
        - If no usable number is found, return 0.0
        """
        if not data_str or data_str.strip() == "":
            return 0.0
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
    # Carriers with known “prepaid” type:
    prepaid_carriers = ["chatr", "public_mobile", "freedom_prepaid"]

    for carrier, plans_list in all_data.items():
        # Decide if the plan is “prepaid” or “postpaid”
        plan_type = "prepaid" if carrier in prepaid_carriers else "postpaid"
        for plan in plans_list:
            plan_name = (plan.get("plan_name") or "").strip()
            plan_price = (plan.get("plan_price") or "").strip()
            plan_data_str = (plan.get("plan_data") or "").strip()
            numeric_data = parse_plan_data(plan_data_str)

            raw_features = plan.get("plan_features", "")
            # We can keep the same approach for formatting plan features:
            if carrier not in ["chatr", "koodo"]:
                # If features is a list, join them as bullet points
                if isinstance(raw_features, list):
                    formatted_features = "\n".join(f"• {feat}" for feat in raw_features)
                elif isinstance(raw_features, str):
                    features_list = re.split(r"[,;]", raw_features)
                    features_list = [feat.strip() for feat in features_list if feat.strip()]
                    formatted_features = "\n".join(f"• {feat}" for feat in features_list)
                else:
                    formatted_features = ""
            else:
                # For Chatr and Koodo, keep the features as-is (or join if list)
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
                "plan_features": formatted_features,
            }
            rows.append(row)

    fieldnames = ["carrier", "plan_type", "plan_name", "plan_price", "plan_data", "plan_features"]
    with open(csv_filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# -----------------
# 1) Virgin Mobile
# -----------------
async def scrape_virgin(page: Page) -> list:
    """
    Scrapes the Virgin Plus BYOP page.
    This example uses a direct locator approach to gather plan elements.
    """
    url = "https://www.virginplus.ca/en/plans/postpaid.html#!/BYOP/research"
    print(f"Scraping Virgin BYOP from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(6000)

    # Example: We look for all plan cards on the page.
    # We'll guess a typical class name or data attribute.
    # You may need to update selectors to match current markup.
    plan_cards = page.locator(".planCard")

    results = []
    count = await plan_cards.count()
    for i in range(count):
        card = plan_cards.nth(i)
        plan_name = await card.locator(".plan-name").inner_text() if await card.locator(
            ".plan-name").count() > 0 else ""
        plan_price = await card.locator(".plan-price").inner_text() if await card.locator(
            ".plan-price").count() > 0 else ""
        plan_data = await card.locator(".plan-data").inner_text() if await card.locator(
            ".plan-data").count() > 0 else ""
        # Possibly gather multiple bullet points for features:
        feature_selectors = card.locator(".plan-features li")
        feature_count = await feature_selectors.count()
        plan_features_list = []
        for j in range(feature_count):
            feat_text = await feature_selectors.nth(j).inner_text()
            plan_features_list.append(feat_text)

        # Build dictionary
        results.append({
            "plan_name": plan_name,
            "plan_price": plan_price,
            "plan_data": plan_data,
            "plan_features": plan_features_list
        })

    return results


# -------------
# 2) Koodo
# -------------
async def scrape_koodo(page: Page) -> list:
    """
    Scrapes Koodo’s rate plan page without agentQL.
    This snippet is only an example of how you might parse the final DOM.
    """
    url = "https://www.koodomobile.com/en/rate-plans?INTCMP=KMNew_NavMenu_Shop_Plans"
    print(f"Scraping Koodo BYOP from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(6000)

    # For illustration, let's assume plans are listed under .plan-card,
    # with .plan-name, .plan-price, etc. Adjust as needed based on actual site structure.
    plan_cards = page.locator(".plan-card")

    results = []
    count = await plan_cards.count()
    for i in range(count):
        card = plan_cards.nth(i)
        plan_name = await card.locator(".plan-name").inner_text() if await card.locator(
            ".plan-name").count() > 0 else ""
        plan_price = await card.locator(".plan-price").inner_text() if await card.locator(
            ".plan-price").count() > 0 else ""
        plan_data = await card.locator(".plan-data").inner_text() if await card.locator(
            ".plan-data").count() > 0 else ""
        # Some carriers (like Koodo) might not list features in bullet form, so parse as needed
        features_text = ""
        if await card.locator(".plan-features").count() > 0:
            features_text = await card.locator(".plan-features").inner_text()

        results.append({
            "plan_name": plan_name,
            "plan_price": plan_price,
            "plan_data": plan_data,
            "plan_features": features_text
        })

    return results


# -----------
# 3) Fido
# -----------
async def scrape_fido(page: Page) -> list:
    """
    Scrapes Fido BYOD + toggles the plan type tabs.
    """
    url = "https://www.fido.ca/phones/bring-your-own-device?icid=F_WIR_CNV_GRM6LG&flowType=byod"
    print(f"Scraping Fido BYOD from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)

    all_plans = []

    # Function to parse the plan cards
    async def parse_fido_cards():
        results = []
        cards = page.locator(".planCard")
        count = await cards.count()
        for i in range(count):
            card = cards.nth(i)
            plan_name = await card.locator(".plan-name").inner_text() if await card.locator(
                ".plan-name").count() > 0 else ""
            plan_price = await card.locator(".plan-price").inner_text() if await card.locator(
                ".plan-price").count() > 0 else ""
            plan_data = await card.locator(".plan-data").inner_text() if await card.locator(
                ".plan-data").count() > 0 else ""
            feature_selectors = card.locator(".plan-features li")
            feature_count = await feature_selectors.count()
            plan_features_list = []
            for j in range(feature_count):
                feat_text = await feature_selectors.nth(j).inner_text()
                plan_features_list.append(feat_text)

            results.append({
                "plan_name": plan_name,
                "plan_price": plan_price,
                "plan_data": plan_data,
                "plan_features": plan_features_list
            })
        return results

    # Collect default (Data, Talk & Text)
    all_plans.extend(await parse_fido_cards())

    # For “Talk & Text” tab
    try:
        talk_text_tab = page.locator("text=Talk & Text")
        if await talk_text_tab.count() > 0:
            await talk_text_tab.click()
            await page.wait_for_timeout(2000)
            all_plans.extend(await parse_fido_cards())
    except:
        print("Couldn't select Talk & Text tab on Fido.")

    # For “Basic” tab
    try:
        basic_tab = page.locator("text=Basic")
        if await basic_tab.count() > 0:
            await basic_tab.click()
            await page.wait_for_timeout(2000)
            all_plans.extend(await parse_fido_cards())
    except:
        print("Couldn't select Basic tab on Fido.")

    return all_plans


# ------------
# 4) Rogers
# ------------
async def scrape_rogers(page: Page) -> list:
    url = "https://www.rogers.com/phones/bring-your-own-device?icid=R_WIR_CMH_PL5IQK&flowType=byod"
    print(f"Scraping Rogers BYOD from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)

    results = []

    async def parse_rogers_cards():
        out = []
        cards = page.locator(".plan-card")
        count = await cards.count()
        for i in range(count):
            card = cards.nth(i)
            plan_name = await card.locator(".plan-name").inner_text() if await card.locator(
                ".plan-name").count() > 0 else ""
            plan_price = await card.locator(".plan-price").inner_text() if await card.locator(
                ".plan-price").count() > 0 else ""
            plan_data = await card.locator(".plan-data").inner_text() if await card.locator(
                ".plan-data").count() > 0 else ""
            feature_selectors = card.locator(".plan-features li")
            feature_count = await feature_selectors.count()
            plan_features_list = []
            for j in range(feature_count):
                feat_text = await feature_selectors.nth(j).inner_text()
                plan_features_list.append(feat_text)

            out.append({
                "plan_name": plan_name,
                "plan_price": plan_price,
                "plan_data": plan_data,
                "plan_features": plan_features_list
            })
        return out

    # e.g. 5G Infinite
    results.extend(await parse_rogers_cards())

    # Try “Talk & Text” tab
    try:
        talk_text_button = page.locator("text=Talk & Text")
        if await talk_text_button.count() > 0:
            await talk_text_button.click()
            await page.wait_for_timeout(2000)
            results.extend(await parse_rogers_cards())
    except:
        print("Couldn't select 'Talk & Text' tab on Rogers.")

    return results


# -----------
# 5) Bell
# -----------
async def scrape_bell(page: Page) -> list:
    url = "https://www.bell.ca/Mobility/Bring-Your-Own-Phone"
    print(f"Scraping Bell from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(6000)

    # Example: We might need to click “Select a plan” or “I’m new to Bell”
    # to get the final listing. Adjust as needed.
    try:
        select_button = page.locator("text=Select a plan")
        if await select_button.count() > 0:
            await select_button.click()
            await page.wait_for_timeout(3000)
    except:
        print("Couldn't click 'Select a plan' on Bell.")

    try:
        new_to_bell_btn = page.locator("text=I’m new to Bell")
        if await new_to_bell_btn.count() > 0:
            await new_to_bell_btn.click()
            await page.wait_for_timeout(18000)
    except:
        print("Couldn't select 'I’m new to Bell' on the pop-up.")

    # Now parse the plan cards
    cards = page.locator(".plan-card")
    results = []
    count = await cards.count()
    for i in range(count):
        card = cards.nth(i)
        plan_name = await card.locator(".plan-name").inner_text() if await card.locator(
            ".plan-name").count() > 0 else ""
        plan_price = await card.locator(".plan-price").inner_text() if await card.locator(
            ".plan-price").count() > 0 else ""
        plan_data = await card.locator(".plan-data").inner_text() if await card.locator(
            ".plan-data").count() > 0 else ""
        # Features
        feats = card.locator(".plan-features li")
        f_count = await feats.count()
        plan_features_list = []
        for j in range(f_count):
            plan_features_list.append(await feats.nth(j).inner_text())

        results.append({
            "plan_name": plan_name,
            "plan_price": plan_price,
            "plan_data": plan_data,
            "plan_features": plan_features_list
        })

    return results


# ------------
# 6) Telus
# ------------
async def scrape_telus(page: Page) -> list:
    url = "https://www.telus.com/en/mobility/plans?linkname=Plans&linktype=ge-meganav"
    print(f"Scraping Telus from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)

    plan_cards = page.locator(".plan-card")
    results = []
    count = await plan_cards.count()
    for i in range(count):
        card = plan_cards.nth(i)
        plan_name = await card.locator(".plan-name").inner_text() if await card.locator(
            ".plan-name").count() > 0 else ""
        plan_price = await card.locator(".plan-price").inner_text() if await card.locator(
            ".plan-price").count() > 0 else ""
        plan_data = await card.locator(".plan-data").inner_text() if await card.locator(
            ".plan-data").count() > 0 else ""
        feat_li = card.locator(".plan-features li")
        feat_count = await feat_li.count()
        plan_features_list = []
        for j in range(feat_count):
            plan_features_list.append(await feat_li.nth(j).inner_text())

        results.append({
            "plan_name": plan_name,
            "plan_price": plan_price,
            "plan_data": plan_data,
            "plan_features": plan_features_list
        })
    return results


# ---------------
# 7) Freedom
# ---------------
async def scrape_freedom(page: Page) -> list:
    url = "https://shop.freedommobile.ca/en-CA/plans?isByopPlanFirstFlow=true"
    print(f"Scraping Freedom plans from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    # Adjust the selectors to match Freedom’s actual plan blocks.
    plan_cards = page.locator(".plan-card")
    results = []
    count = await plan_cards.count()
    for i in range(count):
        card = plan_cards.nth(i)
        plan_name = await card.locator(".plan-name").inner_text() if await card.locator(
            ".plan-name").count() > 0 else ""
        plan_price = await card.locator(".plan-price").inner_text() if await card.locator(
            ".plan-price").count() > 0 else ""
        plan_data = await card.locator(".plan-data").inner_text() if await card.locator(
            ".plan-data").count() > 0 else ""
        feat_items = card.locator(".plan-features li")
        feat_count = await feat_items.count()
        plan_features_list = []
        for j in range(feat_count):
            plan_features_list.append(await feat_items.nth(j).inner_text())

        results.append({
            "plan_name": plan_name,
            "plan_price": plan_price,
            "plan_data": plan_data,
            "plan_features": plan_features_list
        })
    return results


# ---------------
# 8) Chatr
# ---------------
async def scrape_chatr(page: Page) -> list:
    url = "https://www.chatrwireless.com/plans"
    print(f"Scraping Chatr plans from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    plan_cards = page.locator(".plan-card")
    results = []
    count = await plan_cards.count()
    for i in range(count):
        card = plan_cards.nth(i)
        plan_name = await card.locator(".plan-name").inner_text() if await card.locator(
            ".plan-name").count() > 0 else ""
        plan_price = await card.locator(".plan-price").inner_text() if await card.locator(
            ".plan-price").count() > 0 else ""
        plan_data = await card.locator(".plan-data").inner_text() if await card.locator(
            ".plan-data").count() > 0 else ""
        feats = card.locator(".plan-features li")
        f_count = await feats.count()
        plan_features_list = []
        for j in range(f_count):
            plan_features_list.append(await feats.nth(j).inner_text())

        results.append({
            "plan_name": plan_name,
            "plan_price": plan_price,
            "plan_data": plan_data,
            "plan_features": plan_features_list
        })
    return results


# ---------------------
# 9) Public Mobile
# ---------------------
async def scrape_public_mobile(page: Page) -> list:
    url = "https://publicmobile.ca/en/plans"
    print(f"Scraping Public Mobile plans from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    plan_cards = page.locator(".plan-card")
    results = []
    count = await plan_cards.count()
    for i in range(count):
        card = plan_cards.nth(i)
        plan_name = await card.locator(".plan-name").inner_text() if await card.locator(
            ".plan-name").count() > 0 else ""
        plan_price = await card.locator(".plan-price").inner_text() if await card.locator(
            ".plan-price").count() > 0 else ""
        plan_data = await card.locator(".plan-data").inner_text() if await card.locator(
            ".plan-data").count() > 0 else ""
        feats = card.locator(".plan-features li")
        f_count = await feats.count()
        plan_features_list = []
        for j in range(f_count):
            plan_features_list.append(await feats.nth(j).inner_text())

        results.append({
            "plan_name": plan_name,
            "plan_price": plan_price,
            "plan_data": plan_data,
            "plan_features": plan_features_list
        })
    return results


# ----------------------------
# 10) Freedom Prepaid Example
# ----------------------------
async def scrape_freedom_prepaid(page: Page) -> list:
    url = "https://shop.freedommobile.ca/en-CA/prepaid-plans"
    print(f"Scraping Freedom prepaid plans from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    plan_cards = page.locator(".plan-card")
    results = []
    count = await plan_cards.count()
    for i in range(count):
        card = plan_cards.nth(i)
        plan_name = await card.locator(".plan-name").inner_text() if await card.locator(
            ".plan-name").count() > 0 else ""
        plan_price = await card.locator(".plan-price").inner_text() if await card.locator(
            ".plan-price").count() > 0 else ""
        plan_data = await card.locator(".plan-data").inner_text() if await card.locator(
            ".plan-data").count() > 0 else ""
        feats = card.locator(".plan-features li")
        f_count = await feats.count()
        plan_features_list = []
        for j in range(f_count):
            plan_features_list.append(await feats.nth(j).inner_text())

        results.append({
            "plan_name": plan_name,
            "plan_price": plan_price,
            "plan_data": plan_data,
            "plan_features": plan_features_list
        })
    return results


# -------------
# Main Routine
# -------------
async def main():
    # Launch the Playwright browser
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # VIRGIN
        virgin_page = await browser.new_page()
        virgin_plans = await scrape_virgin(virgin_page)

        # KOODO
        koodo_page = await browser.new_page()
        koodo_plans = await scrape_koodo(koodo_page)

        # FIDO
        fido_page = await browser.new_page()
        fido_plans = await scrape_fido(fido_page)

        # ROGERS
        rogers_page = await browser.new_page()
        rogers_plans = await scrape_rogers(rogers_page)

        # BELL
        bell_page = await browser.new_page()
        bell_plans = await scrape_bell(bell_page)

        # TELUS
        telus_page = await browser.new_page()
        telus_plans = await scrape_telus(telus_page)

        # FREEDOM
        freedom_page = await browser.new_page()
        freedom_plans = await scrape_freedom(freedom_page)

        # CHATR
        chatr_page = await browser.new_page()
        chatr_plans = await scrape_chatr(chatr_page)

        # PUBLIC MOBILE
        public_mobile_page = await browser.new_page()
        public_mobile_plans = await scrape_public_mobile(public_mobile_page)

        # FREEDOM PREPAID
        freedom_prepaid_page = await browser.new_page()
        freedom_prepaid_plans = await scrape_freedom_prepaid(freedom_prepaid_page)

        # Combine data
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

        # Print combined JSON
        print("\n=== Combined JSON ===")
        print(json.dumps(all_data, indent=2))

        # Save to CSV
        csv_path = "byop_plans_alternative.csv"
        save_plans_to_csv(all_data, csv_path)
        print(f"Saved CSV to {csv_path}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())