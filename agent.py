#!/usr/bin/env python3
import asyncio
import agentql
from agentql.ext.playwright.async_api import Page
from playwright.async_api import async_playwright
import json


# -------------------------------------------------
# 1) Virgin: BYOP Plans
# -------------------------------------------------
async def scrape_virgin(page: Page) -> list:
    """Scrape Virgin's BYOP plans."""
    url = "https://www.virginplus.ca/en/plans/postpaid.html#!/BYOP/research"
    print(f"Scraping Virgin BYOP from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)  # Wait 3s if needed

    # (Optional) Dismiss cookie or region banners, if any
    # Example: if there's a known 'cookie-accept' button
    # try:
    #     cookie_button = await page.get_by_prompt("cookie accept button")
    #     if cookie_button:
    #         await cookie_button.click()
    # except:
    #     pass

    # AgentQL query
    query = """
    {
      plans[] {
        plan_name
        plan_price
        plan_data
      }
    }
    """

    response = await page.query_data(query)
    virgin_plans = response.get("plans", [])
    return virgin_plans


# -------------------------------------------------
# 2) Koodo: BYOP Plans
# -------------------------------------------------
async def scrape_koodo(page: Page) -> list:
    """Scrape Koodo's BYOP plans (all on one page)."""
    url = "https://www.koodomobile.com/en/rate-plans?INTCMP=KMNew_NavMenu_Shop_Plans"
    print(f"Scraping Koodo BYOP from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    # Possibly dismiss overlays or region settings
    # try:
    #     region_button = await page.get_by_prompt("region selection")
    #     if region_button:
    #         await region_button.click()
    # except:
    #     pass

    query = """
    {
      plans[] {
        plan_name
        plan_price
        plan_data
      }
    }
    """
    response = await page.query_data(query)
    koodo_plans = response.get("plans", [])
    return koodo_plans


# -------------------------------------------------
# 3) Fido: BYOD Plans
# -------------------------------------------------
async def scrape_fido(page: Page) -> list:
    """
    Scrape Fido's BYOD Plans.
    We'll collect from 'Data, Talk & Text',
    then click to load 'Talk & Text',
    then click 'Basic' etc.
    """

    url = "https://www.fido.ca/phones/bring-your-own-device?icid=F_WIR_CNV_GRM6LG&flowType=byod"
    print(f"Scraping Fido BYOD from {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    # (Optional) Dismiss overlays or cookie notices
    # try:
    #     cookie_button = await page.get_by_prompt("cookie accept button")
    #     if cookie_button:
    #         await cookie_button.click()
    # except:
    #     pass

    all_plans = []

    # 3A) Grab "Data, Talk & Text" (the default)
    query = """
    {
      plans[] {
        plan_name
        plan_price
        plan_data
      }
    }
    """
    response = await page.query_data(query)
    default_plans = response.get("plans", [])
    all_plans.extend(default_plans)

    # 3B) Now click on the "Talk & Text" option
    # The actual selector or text for that link/tab might differ.
    try:
        talk_text_button = await page.get_by_prompt("the Talk & Text option/tab")
        if talk_text_button:
            await talk_text_button.click()
            await page.wait_for_timeout(2000)
            # re-run the query for talk & text
            resp_talk_text = await page.query_data(query)
            talk_text_plans = resp_talk_text.get("plans", [])
            all_plans.extend(talk_text_plans)
    except:
        print("Couldn't select 'Talk & Text' tab.")

    # 3C) Same for "Basic"
    try:
        basic_button = await page.get_by_prompt("the Basic option/tab")
        if basic_button:
            await basic_button.click()
            await page.wait_for_timeout(2000)
            resp_basic = await page.query_data(query)
            basic_plans = resp_basic.get("plans", [])
            all_plans.extend(basic_plans)
    except:
        print("Couldn't select 'Basic' tab.")

    return all_plans


# -------------------------------------------------
# Main: Combine All Carriers
# -------------------------------------------------
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)

        # 1) Scrape Virgin
        virgin_page = await agentql.wrap_async(browser.new_page())
        virgin_plans = await scrape_virgin(virgin_page)
        print("Virgin Plans:", virgin_plans)

        # 2) Scrape Koodo
        koodo_page = await agentql.wrap_async(browser.new_page())
        koodo_plans = await scrape_koodo(koodo_page)
        print("Koodo Plans:", koodo_plans)

        # 3) Scrape Fido
        fido_page = await agentql.wrap_async(browser.new_page())
        fido_plans = await scrape_fido(fido_page)
        print("Fido Plans:", fido_plans)

        # Combine or post-process if needed
        all_data = {
            "virgin": virgin_plans,
            "koodo": koodo_plans,
            "fido": fido_plans
        }

        # 4) Print as JSON
        print("\n=== Combined JSON ===")
        print(json.dumps(all_data, indent=2))

        # Clean up
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())