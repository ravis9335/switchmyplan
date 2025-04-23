import nest_asyncio
import asyncio
import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from flask import Flask, request, jsonify, redirect, Response, send_from_directory, render_template, session, url_for
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
from flask import Flask, jsonify, send_file, send_from_directory, request

import agentql
from playwright.async_api import async_playwright
import uuid
import re
import random
import pandas as pd
from pathlib import Path
import time
from playwright_stealth import stealth_async
import csv
from pymongo import MongoClient
import os
import time
import csv
from datetime import datetime
import sys
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
import ssl



# Plans cache setup
plans_cache = {
    'data': None,
    'last_refresh': 0
}

def load_plans_data():
    """
    Load and validate the plans data from CSV file.
    Returns a validated DataFrame containing only POSTPAID plans.
    """
    try:
        # Load the CSV file
        plans_df = pd.read_csv('byop_plans.csv')
        
        # Expected columns based on provided header example
        required_cols = ["carrier", "plan_type", "plan_name", "plan_price", "plan_data", "plan_features"]
        for col in required_cols:
            if col not in plans_df.columns:
                logging.error("CSV file is missing required column: '%s'", col)
                sys.exit(1)

        # Enforce numeric conversion for plan_price
        try:
            plans_df["plan_price"] = pd.to_numeric(plans_df["plan_price"], errors='raise')
        except Exception as e:
            logging.error("Error converting 'plan_price' column to numeric: %s", e)
            sys.exit(1)

        # Normalize plan_type for reliable filtering
        plans_df["plan_type"] = plans_df["plan_type"].astype(str).str.upper()
        # Filter to include only POSTPAID plans
        plans_df = plans_df[plans_df["plan_type"] == "POSTPAID"]

        if plans_df.empty:
            logging.error("No POSTPAID plans found in CSV file.")
            sys.exit(1)

        logging.debug("Loaded POSTPAID plans:\n%s", plans_df.head())
        return plans_df
                
    except Exception as e:
        logging.error("Error loading plans data: %s", e)
        sys.exit(1)

def get_cached_plans():
    """Get plans from cache or load from file if cache is expired"""
    current_time = time.time()
    if (plans_cache['data'] is None or 
        current_time - plans_cache['last_refresh'] > 300):  # 5 minutes cache
        plans_cache['data'] = load_plans_data()
        plans_cache['last_refresh'] = current_time
    return plans_cache['data']

# Load plans initially when server starts
initial_plans = get_cached_plans()
if initial_plans is None:
    print("Warning: Failed to load initial plans data")
else:
    print(f"Successfully loaded {len(initial_plans)} plans initially")

# -------------------------------------------------------------------------
#                          CONFIG / SETUP
# -------------------------------------------------------------------------
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-please-change'
    SESSION_TIMEOUT = 60  # minutes
    MAX_RECOMMENDATIONS = 10
    RPA_TIMEOUT = 300  # seconds  # for the flows


def ensure_directories():
    directories = ['logs']
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"Created directory: {directory}")
        else:
            print(f"Directory already exists: {directory}")


ensure_directories()


def setup_logging():
    ensure_directories()
    file_handler = RotatingFileHandler('logs/blue.log', maxBytes=1024000, backupCount=10)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    return file_handler


# Getting the current directory for static file serving
current_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, 
           static_url_path='', 
           static_folder=current_dir,
           template_folder=current_dir)
app.config.from_object(Config)

# Configure CORS
CORS(app, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

# Configure JSON responses
app.config['JSONIFY_MIMETYPE'] = 'application/json'
app.config['JSON_SORT_KEYS'] = False

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["1000 per day", "500 per hour"]
)
cache = Cache(app, config={'CACHE_TYPE': 'simple'})


# Security headers
@app.after_request
def add_security_headers(response):
    # For development, allow everything
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    
    # Log the response headers for debugging
    app.logger.info(f"Response headers: {dict(response.headers)}")
    return response


handler = setup_logging()
app.logger.addHandler(handler)
app.logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
console_handler.setLevel(logging.INFO)
app.logger.addHandler(console_handler)

app.logger.info('Blue startup - Logging initialized')

# Single global event loop
main_loop = asyncio.new_event_loop()
nest_asyncio.apply(main_loop)


# -------------------------------------------------------------------------
#                          GLOBAL STATE
# -------------------------------------------------------------------------
conversation_context = {
    "state": "greeting",
    "recommended_plans": [],
    "plan_info": {},
    "user_data": {}
}
active_rpa_sessions = {}  # If you want to keep the browser open


# -------------------------------------------------------------------------
#                          HELPER: Human-like clicks
# -------------------------------------------------------------------------
async def hover_and_click_element(page, locator, random_offset=5):
    box = await locator.bounding_box()
    if not box:
        app.logger.warning("Element bounding box not found (not visible?).")
        raise Exception("Element bounding box not found.")
    cx = box["x"] + box["width"] / 2 + random.randint(-random_offset, random_offset)
    cy = box["y"] + box["height"] / 2 + random.randint(-random_offset, random_offset)
    await page.mouse.move(cx, cy, steps=10)
    await page.mouse.down(button="left")
    await page.wait_for_timeout(100)
    await page.mouse.up(button="left")
    app.logger.info(f"Simulated human click at ({cx:.1f},{cy:.1f}).")




# -------------------------------------------------------------------------
#                          BELL FLOW (One Pass)
# -------------------------------------------------------------------------
async def bell_flow_full(session_id: str, user_data: dict, plan_info: dict):
    """
    Bell activation flow in one pass:
      1) Navigate to the Bell BYOP page.
      2) Click "Select a plan".
      3) From the popup, click "I'm new to Bell".
      4) Continue with further steps.
    """
    from datetime import datetime
    start_time = datetime.now()
    print("=== bell_flow_full CALLED === session:", session_id)
    print("User data:", user_data)
    print("Plan info:", plan_info)

    # Extract user data
    first_name      = user_data.get("first_name", "")
    last_name       = user_data.get("last_name", "")
    address         = user_data.get("address", "")
    city            = user_data.get("city", "")
    province        = user_data.get("province", "")
    postal_code     = user_data.get("postal_code", "")
    email           = user_data.get("email", "")
    phone           = user_data.get("phone", "")
    dob             = user_data.get("dob", "")
    card_number     = user_data.get("card_number", "")
    card_expiry     = user_data.get("card_expiry", "")
    cvv             = user_data.get("cvv", "")
    id_type         = user_data.get("id_type", "")
    id_number       = user_data.get("id_number", "")
    plan_name       = plan_info.get("plan_name", "UNKNOWN PLAN")
    number_preference = user_data.get("number_preference", "new")
    transfer_number = user_data.get("transfer_number", phone)

    browser_resources = {}

    try:
        from playwright.async_api import async_playwright
        # Launch browser using Chrome
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            channel="msedge", headless=False, slow_mo=100
        )
        context = await browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/114.0.0.0 Safari/537.36"),
            viewport={"width": 1280, "height": 800}
        )
        # Wrap the new page if necessary
        page = await agentql.wrap_async(await context.new_page())

                # 1) Navigate to the Bell BYOP page with fallback wait conditions
        bell_url = (
            "https://www.bell.ca/Mobility/Bring-Your-Own-Phone?"
            "EXT=MOB_PDL_Google_kwid=p80195691955&gad_source=1&"
            "gclid=Cj0KCQjwhr6_BhD4ARIsAH1YdjDS6-Le4xIQ0pIHkEarNd03p31sI00DKjSEf02q6TKygJSidmR_AI4aAvPtEALw_wcB&gclsrc=aw.ds"
        )
        try:
            # Try with a longer timeout and less strict wait condition
            await page.goto(bell_url, wait_until="domcontentloaded", timeout=120000)
            print("Navigated to Bell BYOP page using 'domcontentloaded'.")
        except Exception as e:
            print("Error navigating with 'domcontentloaded':", e)
            # If the page is closed, try reopening a new page and navigating again
            try:
                page = await context.new_page()
                await page.goto(bell_url, wait_until="domcontentloaded", timeout=120000)
                print("Reopened page and navigated to Bell BYOP page.")
            except Exception as e2:
                print("Failed to reopen page and navigate:", e2)
                raise e2

        # STEP 2) Click "Select a plan" (#btnActivateEsim)
        try:
            # Wait up to 30s for #btnActivateEsim
            await page.wait_for_selector("#btnActivateEsim", timeout=30000)
            select_plan_btn = page.locator("#btnActivateEsim")

            # Attempt normal click
            try:
                await select_plan_btn.click(force=True)
                print("Clicked 'Select a plan' (#btnActivateEsim) successfully.")
            except Exception as e:
                print(f"Normal click on 'Select a plan' failed: {e}. Trying evaluate-click fallback.")
                element_handle = await select_plan_btn.element_handle()
                if element_handle is not None:
                    await page.evaluate("(btn) => btn.click()", element_handle)
                    print("Clicked 'Select a plan' via evaluate-click fallback.")
                else:
                    print("Could not obtain element handle for 'Select a plan' fallback.")
        except Exception as ex:
            print(f"Error waiting for or clicking '#btnActivateEsim': {ex}")
        await page.wait_for_timeout(3000)
        
        # STEP 3) Click "I'm new to Bell" with multiple fallbacks
        try:
            im_new_btn = await page.get_by_prompt("new to Bell")
            if im_new_btn:
                await im_new_btn.click(force=True)
                print("Clicked 'I'm new to Bell' using substring match.")
        except Exception as e:
            print("Error clicking 'I'm new to Bell' using substring:", e)
        await page.wait_for_timeout(18000)
      

        # STEP 4) Wait, then locate & click the user's chosen plan (e.g. "Ultimate 100")
        try:
            await page.wait_for_timeout(5000)  # extra wait to let the plans load

            # Example approach: find any h3 with ID that starts with "radio-title-" AND has plan_name
            # e.g. h3#radio-title-c74f0f82-ee2-...:has-text("Ultimate 100")
            plan_selector = f"h3[id^='radio-title-']:has-text('{plan_name}')"
            plan_locator = page.locator(plan_selector)
            count = await plan_locator.count()
            if count == 0:
                print(f"No plan found matching {plan_selector}")
            else:
                # Click the first match
                await plan_locator.first.scroll_into_view_if_needed()
                await plan_locator.first.click(force=True)
                print(f"Clicked on the plan: {plan_name}")
        except Exception as e:
            print(f"Error selecting plan '{plan_name}': {e}")
        await page.wait_for_timeout(3000)

        # Possibly handle "Next Step"
        try:
            next_step1 = await page.get_by_prompt("Next Step")
            if next_step1:
                await next_step1.click(force=True)
                print("Clicked first 'Next Step'.")
        except Exception as e:
            print("Error clicking first 'Next Step':", e)
        await page.wait_for_timeout(5000)

        # Possibly handle "Order a SIM card"
        try:
            # Third attempt: use a generic text locator, case-insensitive (regex)
            await page.wait_for_selector("text=/SIM\\s*card/i", timeout=30000)
            sim_card_btn = page.locator("text=/SIM\\s*card/i").first
            await sim_card_btn.scroll_into_view_if_needed()
            await sim_card_btn.click(force=True)
            print("Clicked 'SIM card' using text=/SIM\\s*card/i.")
        except Exception as e3:
            print("Error clicking 'SIM card' using all locators: ", e3)

        # Possibly handle "Add to cart"
        try:
            add_to_cart = await page.get_by_prompt("Continue to cart")
            if add_to_cart:
                await add_to_cart.dblclick(force=True)
                print("Clicked 'Continue to cart'.")
        except Exception as e:
            print("Error clicking 'Continue to cart':", e)
        await page.wait_for_timeout(15000)

        try:
            proceed_checkout = await page.get_by_prompt("Proceed to checkout")
            if proceed_checkout:
                await proceed_checkout.dblclick(force=True)
                print("Clicked 'Proceed to checkout'.")
        except Exception as e:
            print("Error clicking 'Proceed to checkout':", e)
        await page.wait_for_timeout(15000)


        try:
            proceed_checkout = await page.get_by_prompt("Proceed to checkout")
            if proceed_checkout:
                try:
                    await proceed_checkout.dblclick(force=True)
                    print("Double-clicked 'Proceed to checkout' successfully.")
                except Exception as e:
                    print(f"Normal double-click failed: {e}. Trying evaluate dblclick fallback.")
                    element_handle = await proceed_checkout.element_handle()
                    if element_handle is not None:
                        await page.evaluate(
                            """(el) => {
                        el.dispatchEvent(new MouseEvent('dblclick', {
                            bubbles: true,
                            cancelable: true,
                            composed: true
                        }));
                    }""",
                    element_handle
                )
                        print("Double-clicked 'Proceed to checkout' via evaluate fallback.")
                    else:
                        print("Could not obtain element handle for 'Proceed to checkout' fallback.")
            else:
                print("'Proceed to checkout' prompt not found.")
        except Exception as e:
            print("Error double-clicking 'Proceed to checkout':", e)
        await page.wait_for_timeout(15000)






        # STEP 7) Fill personal info (similar to the Virgin flow)
        print("Filling personal info on Bell page...")
        await page.wait_for_timeout(2000)
        
        # Fill out first name
        try:
            fn_field = page.locator("input[name='firstName']")
            if await fn_field.count() > 0:
                await fn_field.first.fill(first_name)
                print("Filled first name.")
        except Exception as e:
            print("Error filling first name:", e)
        await page.wait_for_timeout(500)
        # Fill out remaining fields
        try:
            ln_field = page.locator("input[name='lastName']")
            if await ln_field.count() > 0:
                await ln_field.first.fill(last_name)
                print("Filled last name.")
        except Exception as e:
            print("Error filling last name:", e)
        await page.wait_for_timeout(500)
        # STEP X) Fill out Street address + city, select the first autocomplete hit
        full_address = f"{address} {city}".strip()

# Locate the combobox by its role and accessible name
        addr_field = page.get_by_role("combobox", name="Street address")
        await addr_field.click(force=True)

# Type rather than fill—this drives the shadow‐DOM contenteditable properly
        await addr_field.type(full_address, delay=50)
# give the suggestions a moment to appear
        await page.wait_for_timeout(1500)

# Arrow down to highlight the first suggestion, then enter to select
        #await page.keyboard.press("ArrowDown")
        await page.keyboard.press("Enter")
        print(f"✅ Street address entered and suggestion selected: {full_address}")
        await page.wait_for_timeout(1500)

        try:
            email_field = await page.get_by_prompt("Email address")
            if email_field:
                await email_field.fill(email)
        except:
            pass
        try:
            confirm_email_field = await page.get_by_prompt("Confirm email address")
            if confirm_email_field:
                await confirm_email_field.fill(email)
        except:
            pass
        try:
            phone_field = await page.get_by_prompt("Phone number")
            if phone_field:
                await phone_field.fill(phone)
        except:
            pass

        # Possibly "Continue"
        try:
            cont_btn = await page.get_by_prompt("Continue to Number setup")
            if cont_btn:
                await cont_btn.click(force=True)
        except:
            pass
        await page.wait_for_timeout(5000)

        # Possibly "Confirm"
        try:
            confirm_add_btn = await page.get_by_prompt("Confirm")
            if confirm_add_btn:
                await confirm_add_btn.dblclick(force=True)
                print("Clicked 'Confirm' on popup.")
        except:
            pass
        await page.wait_for_timeout(10000)

        # Possibly fill phone number preference (transfer vs new), etc.
        if number_preference == "transfer":
            try:
                transfer_option = await page.get_by_prompt("Transfer your current number to Virgin Plus")
                if transfer_option:
                    await transfer_option.click(force=True)
                await page.wait_for_timeout(5000)
            except:
                pass
            try:
                phone_transfer_field = await page.get_by_prompt("Phone number to transfer")
                if phone_transfer_field:
                    await phone_transfer_field.fill(transfer_number)
                await page.wait_for_timeout(3000)
            except:
                pass
            try:
                verify_btn = await page.get_by_prompt("Verify transferability")
                if verify_btn:
                    await verify_btn.click(force=True)
                await page.wait_for_timeout(5000)
            except:
                pass
            
            try:
                 # Locate by id or name – whichever you prefer
                terms_checkbox = page.locator("input#i-authorize")  # or "input[name='fieldsAuthorized']"

                    # Make sure it's visible
                await terms_checkbox.scroll_into_view_if_needed()
                         # Use .check() so Playwright handles the underlying click+aria firing
                await terms_checkbox.check(force=True)
                print("✅ Checked Bell's T&C box")
                await page.wait_for_timeout(1000)
            except Exception as e:
                print("❌ Error ticking T&C box:", e)

# STEP: Confirm the transfer
            try:
                confirm_btn = page.get_by_role("button", name="Confirm number transfer")
                await confirm_btn.click(force=True)
                print("✅ Clicked 'Confirm number transfer'")
                await page.wait_for_timeout(5000)
            except Exception as e:
                print("❌ Error clicking confirm-transfer button:", e)

            
        else:
            try:
                new_num_option = await page.get_by_prompt("Select a new number")
                if new_num_option:
                    await new_num_option.click(force=True)
                await page.wait_for_timeout(5000)
            except:
                pass
            try:
                cont_new_btn = await page.get_by_prompt("Continue")
                if cont_new_btn:
                    await cont_new_btn.dblclick(force=True)
                await page.wait_for_timeout(5000)
            except:
                pass
            try:
                cont_new_btn = await page.get_by_prompt("Continue")
                if cont_new_btn:
                    await cont_new_btn.dblclick(force=True)
                await page.wait_for_timeout(5000)
            except:
                pass


        try:
            cont_new_btn = await page.get_by_prompt("Continue")
            if cont_new_btn:
                await cont_new_btn.dblclick(force=True)
                await page.wait_for_timeout(5000)
        except:
            pass

        try:
            cont_new_btn = await page.get_by_prompt("Continue")
            if cont_new_btn:
                await cont_new_btn.dblclick(force=True)
                await page.wait_for_timeout(5000)
        except:
            pass

        # STEP: Click the "Continue" button on the Shipping step
        try:
            btn = page.locator("button[data-dtname='Continue button on Shipping step']")
    # 1) Make sure it's in the DOM
            await btn.wait_for(state="attached", timeout=15000)
    # 2) Force the click (Playwright will auto-scroll under the hood)
            await btn.click(force=True)
            print("✅ Clicked shipping 'Continue' via locator.force()")
        except Exception as e:
            print("❌ Error clicking shipping Continue (locator.force):", e)
        await page.wait_for_timeout(5000)

        # 4) Fill credit card expiry using select_option(), plus fallback if needed
        try:
            # Parse the month/year from card_expiry
            if "/" in card_expiry:
                month_digits, year_digits = card_expiry.split("/")
            else:
                month_digits, year_digits = ("04", "25")

            # Zero-pad month if needed
            month_digits = month_digits.zfill(2)

            # Convert 2-digit year into 4-digit
            if len(year_digits) == 2:
                year_full = f"20{year_digits}"
            else:
                year_full = year_digits

            # 1) Select the expiry month
            try:
                month_select = page.locator("select#CreditCard_ExpirationDataMM")
                # First attempt: match the <option value="04"> or similar
                await month_select.select_option(value=month_digits)
                print(f"Selected expiry month by value: {month_digits}")
            except Exception as e:
                print(f"Error selecting expiry month by value: {e}. Trying label fallback...")
                # If the site uses label instead of value, try label=month_digits
                try:
                    await month_select.select_option(label=month_digits)
                    print(f"Selected expiry month by label: {month_digits}")
                except Exception as e2:
                    print(f"Fallback label selection for month failed: {e2}")

            # 2) Select the expiry year
            try:
                year_select = page.locator("select#CreditCard_ExpirationDateYY")
                # Attempt matching <option value="2028"> or similar
                await year_select.select_option(value=year_full)
                print(f"Selected expiry year by value: {year_full}")
            except Exception as e:
                print(f"Error selecting expiry year by value: {e}. Trying label fallback...")
                try:
                    await year_select.select_option(label=year_full)
                    print(f"Selected expiry year by label: {year_full}")
                except Exception as e2:
                    print(f"Fallback label selection for year failed: {e2}")
        except Exception as e:
            print(f"Error filling credit card expiry: {e}")

        # Card number
        try:
            card_number_field = await page.get_by_prompt("Card number")
            if card_number_field:
                await card_number_field.fill(card_number)
                masked = "**** **** **** " + card_number[-4:] if len(card_number) >= 4 else "****"
                print(f"Filled card number with: {masked}")
            else:
                print("Card number field not found.")
        except Exception as e:
            print(f"Error filling card number: {str(e)}")

        # CVV
        try:
            cvv_field = await page.get_by_prompt("Card security code")
            if cvv_field:
                await cvv_field.fill(cvv)
                print("Filled card security code.")
            else:
                print("Card security code field not found.")
        except Exception as e:
            print(f"Error filling card security code: {str(e)}")

        # DOB
        try:
            dob_field = await page.get_by_prompt("Date of birth")
            if dob_field:
                await dob_field.fill(dob)
                print(f"Filled date of birth with: {dob}")
            else:
                print("Date of birth field not found.")
        except Exception as e:
            print(f"Error filling date of birth: {str(e)}")

        # final submit/continue
        try:
            final_btn = page.locator("button:has-text('Submit'), button:has-text('Continue')").first
            if await final_btn.count() > 0:
                await final_btn.click(force=True)
                print("Clicked final submit/continue on Virgin form.")
            else:
                print("Final submit/continue button not found on Virgin form.")
        except Exception as e:
            print(f"Error clicking final Virgin button: {str(e)}")

        print("Virgin flow done, in one pass, no pause.")
        browser_resources = {
            "playwright": playwright,
            "browser": browser,
            "context": context,
            "page": page
        }
        active_rpa_sessions[session_id] = browser_resources

    except Exception as e:
        print("Virgin flow error:", e)
        raise e
    finally:
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"Virgin flow completed after {elapsed:.1f}s")




# -------------------------------------------------------------------------
#                          FLASK ROUTES
# -------------------------------------------------------------------------

@app.route('/', methods=['GET'])
def index():
    """Serves the main planB.html page"""
    try:
        with open('planB.html', 'r') as f:
            content = f.read()
        return Response(content, content_type='text/html')
    except Exception as e:
        app.logger.error(f"Error serving planB.html: {e}")
        return jsonify({"error": "Could not load planB.html"}), 500

@app.route('/api/chat', methods=['POST'])
@limiter.exempt  # Exempt this route from rate limiting
def api_chat():
    """Handle chat API requests from the planB frontend"""
    data = request.json
    # This is a simplified mock response
    # You can integrate with your original chat logic if needed
    return jsonify({
        "response": "Thank you for your message. Our chat feature is currently being upgraded."
    })

@app.route('/select_plan', methods=['POST'])
def select_plan():
    global conversation_context
    data = request.json
    
    # Get all plan details from the request
    carrier = data.get('carrier', '')
    price = data.get('price', 0)
    data_amount = data.get('data', 0)
    plan_id = data.get('id', None)
    plan_name = data.get('plan_name', '')  # Get the exact plan name
    
    # Check if the selected plan is from Fido
    if carrier.lower() == 'fido':
        # Redirect to Fido's BYOP page
        return jsonify({
            "success": True,
            "redirect": True,
            "url": "https://www.fido.ca/phones/bring-your-own-device?icid=F_WIR_CNV_GRM6LG&flowType=byod"
        })
    
    # Check if the selected plan is from Rogers
    if carrier.lower() == 'rogers':
        # Redirect to Rogers' BYOP page
        return jsonify({
            "success": True,
            "redirect": True,
            "url": "https://www.rogers.com/phones/bring-your-own-device?icid=R_WIR_CMH_PL5IQK&flowType=byod"
        })
    
    # Check if the selected plan is from Koodo
    if carrier.lower() == 'koodo':
        # Redirect to Koodo's rate plans page
        return jsonify({
            "success": True,
            "redirect": True,
            "url": "https://www.koodomobile.com/en/rate-plans?cmp=bac_phb-gnl_koodo-ko-pf-performance-conversion-socdis-mobility-mobility-2025-fy-1et-ie-003&cid=32888299&sid=4685228&pid=411529233&aid=603360139&crid=227606228&dcid=AMsySZY-Xb4SB2ZF0BQcBs238nkL&utm_campaign=dsp_koodo-pf-mobility-mobility-performance-conversion-socdis-fy-2025&utm_id=32888299&utm_content=227606228&utm_source=phb-gnl&utm_medium=display&dclid=CO3kyYb4vowDFfqEpgQdtkYsnA&gad_source=7"
        })
    
    # Check if the selected plan is from Telus
    if carrier.lower() == 'telus':
        # Redirect to Telus' plans page
        return jsonify({
            "success": True,
            "redirect": True,
            "url": "https://www.telus.com/en/mobility/plans?linkname=Plans&linktype=ge-meganav"
        })
    
    # Check if the selected plan is from Freedom (handle both postpaid and prepaid)
    if carrier.lower() == 'freedom':
        # Redirect to Freedom's BYOP plans page
        return jsonify({
            "success": True,
            "redirect": True,
            "url": "https://shop.freedommobile.ca/en-CA/plans?isByopPlanFirstFlow=true"
        })
    elif carrier.lower() == 'freedom_prepaid':  # Updated to match exact carrier name
        # Redirect to Freedom's prepaid plans page
        return jsonify({
            "success": True,
            "redirect": True,
            "url": "https://shop.freedommobile.ca/en-CA/prepaid-plans"
        })
    
    # Check if the selected plan is from Chatr
    if carrier.lower() == 'chatr':
        # Redirect to Chatr's plans page
        return jsonify({
            "success": True,
            "redirect": True,
            "url": "https://www.chatrwireless.com/plans?ecid=PS_C0143_C_WIR_Jan_25_ALS_H5HS6V&gad_source=1&gclid=Cj0KCQjw782_BhDjARIsABTv_JCqFLsQFaulI-qeJlA-0E7VHYZruo2oyNTOGw7h2b_nY23In-4k2YQaAqbZEALw_wcB&gclsrc=aw.ds"
        })
    
    # Check if the selected plan is from Public Mobile (handle both formats)
    if carrier.lower() == 'public_mobile' or carrier.lower() == 'public mobile':
        # Redirect to Public Mobile's plans page
        return jsonify({
            "success": True,
            "redirect": True,
            "url": "https://publicmobile.ca/en/plans?ds_rl=1268486&gad_source=1&ds_rl=1268486&gclid=Cj0KCQjw782_BhDjARIsABTv_JA80rlKPKIjsyotNlffUCDzmtf8-x4uVFUezcg4FYTM8MV6xAmidw4aAmGZEALw_wcB&gclsrc=aw.ds"
        })
    
    # For all other carriers, proceed with normal flow
    # Store the selected plan in the context for use in checkout
    conversation_context["plan_info"] = {
        "carrier": carrier,
        "plan_name": plan_name,  # Store the exact plan name
        "plan_price": price,
        "plan_data": data_amount,
        "plan_id": plan_id
    }
    
    return jsonify({"success": True})


# -------------------------------------------------------------------------
#                 SINGLE CHECKOUT PAGE & SUBMISSION
# -------------------------------------------------------------------------
def get_carrier_logo_filename(carrier):
    """Get the correct logo filename for a carrier"""
    logo_map = {
        'virgin': 'Virgin_Plus_Web.png',
        'fido': 'Fido_Solutions_logo.svg.png',
        'koodo': 'Koodo_Mobile_-_Color.png',
        'freedom': 'Freedom_Mobile_logo.svg.png',
        'bell': 'images.png',  # Bell logo is actually named images.png
        'rogers': 'Rogers_logo.svg.png',
        'telus': 'Telus-Logo-1996.png',
        'chatr': 'png-clipart-chatr-mobile-phones-rogers-wireless-mobile-service-provider-company-lucky-mobile-chatr-purple-violet.png',
        'public_mobile': 'public-mobile-logo.png',
        'lucky': 'lucky-mobile-logo.png'
    }
    return logo_map.get(carrier.lower(), f"{carrier.lower()}_logo.png")

@app.route('/checkout', methods=['GET'])
def checkout():
    """Serve the checkout page with plan details"""
    global conversation_context
    # Get the selected plan info from the session context
    plan_info = conversation_context.get("plan_info", {})
    
    # If no plan is selected, redirect to the homepage
    if not plan_info:
        return redirect('/')
        
    carrier = plan_info.get("carrier", "").lower()
    plan_name = plan_info.get("plan_name", "")
    plan_price = float(plan_info.get("plan_price", 0))
    plan_data = plan_info.get("plan_data", "")
    plan_features = plan_info.get("plan_features", "")
    # Get plan features from the cached plans
    plans_df = get_cached_plans()
    
    if isinstance(plans_df, pd.DataFrame):
        # Find the matching plan
        matching_plan = plans_df[
            (plans_df['carrier'].str.lower() == carrier) & 
            (plans_df['plan_name'] == plan_name)
        ]
        if not matching_plan.empty:
            plan_features = matching_plan.iloc[0]['plan_features']
            if pd.isna(plan_features):
                plan_features = None
    
    # Calculate tax (13%)
    tax_amount = round(plan_price * 0.13, 2)
    total_monthly = plan_price + tax_amount

    # Fallback features if no plan features found
    if not plan_features:
        if carrier == 'virgin':
            plan_features = 'Unlimited Talk & Text,Unlimited calling to US, India, UK and other countries,Unlimited International Texting,Data Access'
        elif carrier == 'fido':
            plan_features = 'Unlimited Talk & Text,Unlimited calls & texts to US, India, Mexico and other countries,5 Extra hours of Data every month,Data Overage Protection'
        elif carrier == 'koodo':
            plan_features = 'Unlimited Talk & Text,1 free perk to choose from (Rollover Data, Unlimited Long Distance Pack, and other perks)'
        elif carrier == 'freedom':
            plan_features = 'CA/US/MEX,Unlimited Data, Talk & Text,1000 min International Long Distance for 14 countries'
        elif carrier in ['bell', 'rogers', 'telus']:
            plan_features = 'Unlimited Data, Talk & Text,Unlimited International Text,5G/5G+ Network Access'
        else:
            plan_features = 'Canada-wide Calling,Unlimited Texting,Data Access'
    
    # Get the correct logo filename
    logo_filename = get_carrier_logo_filename(carrier)
    app.logger.info(f"Using logo filename for {carrier}: {logo_filename}")

    return render_template('checkout.html', 
                         carrier=carrier,
                         plan_name=plan_name,
                         plan_price=plan_price,
                         plan_data=plan_data,
                         tax_amount=tax_amount,
                         total_monthly=total_monthly,
                         plan_features=plan_features,
                         logo_filename=logo_filename)

@app.route("/checkout_submit", methods=["POST"])
def checkout_submit():
    form_data = request.form
    session_data = session.get('checkout_data', {})
    plan_data = session_data.get('plan_data', {})
    
    # Extract first and last name if present or use combined name field
    first_name = form_data.get("first_name", "")
    last_name = form_data.get("last_name", "")
    
    # If we have first and last name separately, combine them
    if first_name and last_name:
        full_name = f"{first_name} {last_name}"
    else:
        # Otherwise use the name field or empty string
        full_name = form_data.get("name", "")
    
    # Collect all the data needed for activation
    data = {
        "name": full_name,
        "first_name": first_name,
        "last_name": last_name,
        "email": form_data.get("email"),
        "phone": form_data.get("phone"),
        "address": form_data.get("address"),
        "postal_code": form_data.get("postal_code"),
        "city": form_data.get("city"),
        "province": form_data.get("province"),
        "dob": form_data.get("dob"),
        "carrier": form_data.get("carrier"),
        "imei": form_data.get("imei", ""),
        "sim": form_data.get("sim", ""),
        "plan_name": plan_data.get("name", form_data.get("plan_name", "")),
        "plan_price": plan_data.get("price", form_data.get("plan_price", "")),
        "plan_data": plan_data.get("data", ""),
        "plan_talk": plan_data.get("talk", ""),
        "plan_text": plan_data.get("text", ""),
        "payment_method": form_data.get("payment_method", "Credit Card"),
        "card_number": form_data.get("card_number", ""),
        "card_exp": form_data.get("card_expiry", form_data.get("card_exp", "")),
        "card_cvv": form_data.get("cvv", form_data.get("card_cvv", "")),
        "carrier_username": form_data.get("carrier_username", ""),
        "carrier_password": form_data.get("carrier_password", ""),
        "number_preference": form_data.get("number_preference", "new"),
        "transfer_number": form_data.get("transfer_number", ""),
        "activation_type": form_data.get("activation_type", "esim")
    }
    
    # Check for required fields
    required_fields = ["email", "phone", "address", "postal_code", "city", "province", "dob", "carrier"]
    # Either need full name OR first and last name
    if not data["name"] and (not data["first_name"] or not data["last_name"]):
        required_fields.append("name or first_name/last_name")
    
    missing_fields = [field for field in required_fields if not data.get(field)]
    
    if missing_fields:
        # Return a JSON error response
        return jsonify({
            "status": "error", 
            "message": f"Missing required fields: {', '.join(missing_fields)}"
        }), 400
    
    # IMEI validation (only required for eSIM activation)
    if data["activation_type"] == "esim" and (not data["imei"] or len(data["imei"]) != 15 or not data["imei"].isdigit()):
        return jsonify({
            "status": "error",
            "message": "Invalid IMEI number. IMEI should be 15 digits."
        }), 400
    
    # SIM card validation (only if physical SIM selected)
    if data["activation_type"] == "physical" and data["sim"] and (len(data["sim"]) < 19 or not all(c.isdigit() or c == '-' for c in data["sim"])):
        return jsonify({
            "status": "error",
            "message": "Invalid SIM card number. SIM should be 19-20 digits."
        }), 400

    try:
        # Log the data being sent to RPA (excluding sensitive data)
        log_data = data.copy()
        # Remove sensitive information from logs
        for sensitive_field in ["card_number", "card_cvv", "card_exp"]:
            if sensitive_field in log_data:
                log_data[sensitive_field] = "****"
                
        app.logger.info(f"Starting RPA flow for {data['carrier']} with data: {log_data}")
        
        # Generate a unique session ID for this activation
        session_id = str(uuid.uuid4())
        
        # Prepare user data and plan info to match bell_flow_full expectations
        user_data = {
            "first_name": data["first_name"],
            "last_name": data["last_name"],
            "email": data["email"],
            "phone": data["phone"],
            "address": data["address"],
            "city": data["city"],
            "province": data["province"],
            "postal_code": data["postal_code"],
            "dob": data["dob"],
            "card_number": data["card_number"],
            "card_expiry": data["card_exp"],
            "cvv": data["card_cvv"],
            "number_preference": data["number_preference"],
            "transfer_number": data["transfer_number"]
        }
        
        plan_info = {
            "plan_name": data["plan_name"],
            "plan_price": data["plan_price"]
        }
        
        # Start the RPA flow based on carrier
        carrier_lower = data["carrier"].lower()
        rpa_started = False
        
        if carrier_lower == 'bell':
            # For Bell carrier, use the existing bell_flow_full function
            app.logger.info(f"Starting Bell RPA flow with session ID: {session_id}")
            
            # Create a thread to run the async bell_flow_full function
            def run_bell_flow():
                # Set up event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Run the async function
                try:
                    coro = bell_flow_full(session_id, user_data, plan_info)
                    loop.run_until_complete(coro)
                except Exception as e:
                    app.logger.error(f"Error in Bell RPA flow: {str(e)}")
                finally:
                    loop.close()
            
            # Start the Bell RPA flow in a thread
            bell_thread = threading.Thread(target=run_bell_flow)
            bell_thread.daemon = True
            bell_thread.start()
            
            rpa_started = True
            app.logger.info(f"Bell RPA thread started for session: {session_id}")
            
            # Store session info for later reference/cleanup
            active_rpa_sessions[session_id] = {
                "carrier": "Bell",
                "start_time": datetime.now(),
                "email": data["email"]
            }
        else:
            # For other carriers, just send email notifications for now
            carrier_name = data['carrier'].title()  # Capitalize first letter of each word
            app.logger.info(f"Sending email notification for {carrier_name} activation")
            
            # Send the initial processing email
            email_sent = send_email_notification(
                email=data["email"],
                name=data["name"],
                carrier=carrier_name,
                status="processing"
            )
            
            if email_sent:
                app.logger.info(f"Processing email sent for {carrier_name} activation")
                
                # For demo purposes, we'll also send a "complete" email after a delay
                def send_completion_email():
                    # Wait 30 seconds before sending the completion email
                    time.sleep(30)
                    app.logger.info(f"Sending completion email for {carrier_name} activation")
                    send_email_notification(
                        email=data["email"],
                        name=data["name"],
                        carrier=carrier_name,
                        status="complete"
                    )
                
                # Start a thread to send the completion email after a delay
                email_thread = threading.Thread(target=send_completion_email)
                email_thread.daemon = True
                email_thread.start()
                
                rpa_started = True
            else:
                app.logger.error(f"Failed to send processing email for {carrier_name} activation")
            
        if not rpa_started:
            app.logger.warning(f"No RPA flow implementation found for carrier: {data['carrier']}")
            
        # Return a JSON success response
        return jsonify({
            "status": "success",
            "message": "Activation process started successfully",
            "session_id": session_id
        })
    
    except Exception as e:
        app.logger.error(f"Error starting RPA flow: {str(e)}")
        # Return success anyway to not confuse the user - we'll handle failures internally
        return jsonify({
            "status": "success",
            "message": "Activation request received. We'll email you with updates."
        })


# Optional function to close browser
def cleanup_session(session_id):
    sess = active_rpa_sessions.pop(session_id, None)
    if sess and sess.get("browser"):
        # If you want to close it:
        # await sess["browser"].close()
        pass



@app.route('/test', methods=['GET'])
def test_route():
    """A simple test route to verify basic access"""
    return jsonify({"status": "ok", "message": "Server is accessible"})

@app.route('/test-page', methods=['GET'])
def test_page():
    """Serves the API test page"""
    try:
        with open('test_api.html', 'r') as f:
            content = f.read()
        return Response(content, content_type='text/html')
    except Exception as e:
        app.logger.error(f"Error serving test page: {e}")
        return jsonify({"error": "Could not load test page"}), 500

@app.route('/test-plans', methods=['GET'])
def test_plans_page():
    """Serve the test plans HTML page"""
    try:
        with open('test_plans.html', 'r') as f:
            content = f.read()
        app.logger.info("Serving test_plans.html")
        return Response(content, content_type='text/html')
    except Exception as e:
        app.logger.error(f"Error serving test plans page: {str(e)}")
        return "Error loading test page", 500
    
PLANS_CSV_PATH = 'byop_plans.csv'
CACHE_REFRESH_INTERVAL = 300  # 5 minutes

# Remove duplicate Flask app initialization and CORS setup
# app = Flask(__name__, static_url_path='', static_folder='.')
# CORS(app)

# Cache for storing plans data
plans_cache = {
    'data': None,
    'last_refresh': 0
}

@app.route('/')
def root():
    return send_file('planB.html')

@app.route('/all-plans')
def serve_all_plans():
    """Serves the all-plans.html page"""
    try:
        print("Serving all-plans.html page")
        return send_file('all-plans.html')
    except Exception as e:
        print(f"Error serving all-plans.html: {e}")
        return jsonify({"error": "Could not load all-plans page"}), 500

@app.route('/carrierlogos/<path:filename>')
@limiter.exempt  # Exempt this route from rate limiting
def serve_carrier_logo(filename):
    return send_from_directory('carrierlogos', filename)

def load_plans_data():
    try:
        print(f"Reading CSV file from: {os.path.abspath(PLANS_CSV_PATH)}")
        
        # Check if file exists
        if not os.path.exists(PLANS_CSV_PATH):
            print(f"Error: CSV file not found at {PLANS_CSV_PATH}")
            return None
            
        # Read CSV file with explicit encoding
        df = pd.read_csv(PLANS_CSV_PATH, encoding='utf-8')
        print(f"Found {len(df)} rows in CSV")
        print("CSV columns:", df.columns.tolist())
        
        processed_plans = []
        skipped_count = 0
        error_count = 0
        
        # Carrier name mapping
        carrier_mapping = {
            'virgin': 'Virgin',
            'koodo': 'Koodo',
            'fido': 'Fido',
            'rogers': 'Rogers',
            'bell': 'Bell',
            'telus': 'Telus',
            'freedom': 'Freedom',
            'chatr': 'Chatr',
            'public_mobile': 'Public Mobile',
            'freedom_prepaid': 'Freedom'
        }
        
        for index, row in df.iterrows():
            try:
                # Debug log for each row
                print(f"\nProcessing row {index}:")
                print(f"Raw row data: {row.to_dict()}")
                
                # Skip plans with no price or invalid price
                if pd.isna(row['plan_price']) or row['plan_price'] == 'None' or float(row['plan_price']) <= 0:
                    print(f"Skipping row {index}: Invalid price - {row['plan_price']}")
                    skipped_count += 1
                    continue
                
                # Process carrier name
                carrier = str(row['carrier']).strip().lower()
                carrier = carrier_mapping.get(carrier, carrier.title())
                
                # Format data amount - now handles plans with no data
                data_str = "0"  # Default value
                if pd.isna(row['plan_data']):
                    print(f"Row {index}: No data specified, setting to 0")
                    data_str = "0"
                elif row['plan_data'] == 'None':
                    print(f"Row {index}: Data is None, setting to 0")
                    data_str = "0"
                else:
                    try:
                        data_amount = float(row['plan_data'])
                        if data_amount < 1:
                            data_amount = data_amount * 1024  # Convert to MB
                            data_str = f"{data_amount:.0f}MB"
                        else:
                            data_str = f"{data_amount:.0f}"
                        print(f"Row {index}: Processed data amount: {data_str}")
                    except:
                        print(f"Row {index}: Error converting data amount, setting to 0")
                        data_str = "0"
                
                # Process plan name
                plan_name = str(row.get('plan_name', '')).strip()
                if not plan_name:
                    print(f"Row {index}: Warning - Empty plan name")

                # Process plan features
                plan_features = None
                if 'plan_features' in row and not pd.isna(row['plan_features']):
                    plan_features = str(row['plan_features']).strip()
                    if plan_features.lower() in ['none', 'nan']:
                        plan_features = ""
                    print(f"Row {index}: Found plan features: {plan_features}")
                
                processed_plan = {
                    'carrier': carrier,
                    'price': float(row['plan_price']),
                    'data': data_str,
                    'network_speed': '5G' if carrier not in ['Chatr', 'Lucky', 'Public Mobile'] else '4G LTE',
                    'plan_features': plan_features,  # Add plan_features to the processed plan
                    'terms': 'No term contract required. Prices may vary by region.',
                    'plan_type': str(row.get('plan_type', 'postpaid')).lower(),
                    'plan_name': plan_name,
                    'id': str(row.get('id', ''))
                }
                
                print(f"Row {index}: Successfully processed plan: {carrier} - {plan_name}")
                if plan_features:
                    print(f"Row {index}: Plan features included: {plan_features}")
                processed_plans.append(processed_plan)
                
            except Exception as e:
                print(f"Error processing row {index}: {row}")
                print(f"Error details: {str(e)}")
                error_count += 1
                continue
        
        print(f"\nProcessing summary:")
        print(f"Total rows in CSV: {len(df)}")
        print(f"Successfully processed: {len(processed_plans)} plans")
        print(f"Skipped plans: {skipped_count}")
        print(f"Errors encountered: {error_count}")
        
        if len(processed_plans) == 0:
            print("Warning: No plans were processed successfully!")
            return None
            
        return processed_plans
        
    except Exception as e:
        print(f"Critical error loading plans: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

def get_cached_plans():
    current_time = time.time()
    if (plans_cache['data'] is None or 
        current_time - plans_cache['last_refresh'] > CACHE_REFRESH_INTERVAL):
        plans_cache['data'] = load_plans_data()
        plans_cache['last_refresh'] = current_time
    return plans_cache['data']

@app.route('/api/plans/featured')
def get_featured_plans():
    try:
        plans = get_cached_plans()
        if plans is None:
            return jsonify({'error': 'Failed to load plans data'}), 500
        
        # Include all postpaid plans, regardless of data amount
        featured_plans = [p for p in plans if p['plan_type'] == 'postpaid']
        print(f"Returning {len(featured_plans)} featured plans")
        
        # Debug log the plans being returned
        for plan in featured_plans:
            print(f"Featured plan: {plan['carrier']} - {plan['plan_name']} - Data: {plan['data']} - Price: ${plan['price']}")
        
        return jsonify(featured_plans)
    except Exception as e:
        print(f"Error in get_featured_plans: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/plans/prepaid')
def get_prepaid_plans():
    try:
        plans = get_cached_plans()
        if plans is None:
            return jsonify({'error': 'Failed to load plans data'}), 500
        
        # Include all prepaid plans, regardless of data amount
        prepaid_plans = [p for p in plans if p['plan_type'] == 'prepaid']
        print(f"Returning {len(prepaid_plans)} prepaid plans")
        
        # Debug log the plans being returned
        for plan in prepaid_plans:
            print(f"Prepaid plan: {plan['carrier']} - {plan['plan_name']} - Data: {plan['data']} - Price: ${plan['price']}")
        
        return jsonify(prepaid_plans)
    except Exception as e:
        print(f"Error in get_prepaid_plans: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/plans/reload')
def reload_plans():
    plans_cache['data'] = None
    plans = get_cached_plans()
    if plans is None:
        return jsonify({'error': 'Failed to reload plans data'}), 500
    return jsonify({'message': 'Plans reloaded successfully'})

@app.route('/api/plans/all')
def get_all_plans():
    """Return all plans from the dataset without any filtering"""
    try:
        print("Starting get_all_plans request...")
        plans = get_cached_plans()
        
        if plans is None:
            print("Error: No plans data available")
            return jsonify({'error': 'Failed to load plans data'}), 500
        
        # Return all plans directly from the dataset
        print(f"Successfully retrieved {len(plans)} plans")
        
        # Debug log all plans being returned
        for plan in plans:
            print(f"Plan: {plan['carrier']} - {plan['plan_name']} - Data: {plan['data']} - Price: ${plan['price']} - Type: {plan['plan_type']}")
        
        # Force reload cache if no plans are found
        if len(plans) == 0:
            print("No plans found, forcing cache reload...")
            plans_cache['data'] = None
            plans = get_cached_plans()
            if plans is None or len(plans) == 0:
                print("Still no plans after cache reload")
                return jsonify({'error': 'No plans available'}), 500
        
        print(f"Returning {len(plans)} plans to client")
        return jsonify(plans)
        
    except Exception as e:
        print(f"Error in get_all_plans: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    

# -------------------- CONTACT & FEEDBACK --------------------
import os, csv
from datetime import datetime
from flask import send_file, request, jsonify

FEEDBACK_DIR = 'feedback'
FEEDBACK_CSV = os.path.join(FEEDBACK_DIR, 'feedback.csv')

def ensure_feedback_directory():
    if not os.path.exists(FEEDBACK_DIR):
        os.makedirs(FEEDBACK_DIR)
    if not os.path.exists(FEEDBACK_CSV):
        with open(FEEDBACK_CSV, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Name', 'Email', 'Feedback', 'Timestamp'])

# Serve the contact page
@app.route('/contact.html', methods=['GET'])
def serve_contact():
    try:
        return send_file('contact.html')
    except Exception as e:
        app.logger.error(f"Error serving contact.html: {e}")
        return "Error loading page", 500

# Accept feedback form posts (two URLs, same handler)
@app.route('/contact-feedback', methods=['POST'], strict_slashes=False)
@app.route('/feedback-submit',  methods=['POST'], strict_slashes=False)
def contact_feedback():
    name     = request.form.get('name')
    email    = request.form.get('email', '')
    feedback = request.form.get('feedback')

    if not name or not feedback:
        return jsonify({'error': 'Name and feedback are required'}), 400

    ensure_feedback_directory()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(FEEDBACK_CSV, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([name, email, feedback, timestamp])

    return jsonify({'message': 'Feedback submitted successfully'}), 200

# -------------------------------------------------------------------------

def ensure_dataframe(plans_data):
    """Ensure that the plans data is a pandas DataFrame."""
    if isinstance(plans_data, list):
        return pd.DataFrame(plans_data)
    return plans_data

def extract_plan_details(message: str) -> dict:
    """
    Extract plan details from the user message using regex and matching against known carriers.
    Uses get_cached_plans() to retrieve carrier names.
    """
    plans_data = ensure_dataframe(get_cached_plans())
    details = {}
    
    # Extract price and data using regex.
    price_match = re.search(r'(?:price|cost)\s*[:\-]?\s*\$?(\d+(\.\d+)?)', message, re.IGNORECASE)
    data_match = re.search(r'(?:data)\s*[:\-]?\s*(\d+(\.\d+)?)(?:\s*GB)?', message, re.IGNORECASE)
    
    # Get list of carriers.
    try:
        carriers = plans_data["carrier"].dropna().unique().tolist()
    except Exception as e:
        logging.error("Error accessing carrier data: %s", e)
        carriers = []
    
    carrier_match = None
    for carrier in carriers:
        if re.search(carrier, message, re.IGNORECASE):
            carrier_match = carrier
            break

    if price_match:
        details['plan_price'] = float(price_match.group(1))
    if data_match:
        details['plan_data'] = float(data_match.group(1))
    if carrier_match:
        details['carrier'] = carrier_match.strip()
    
    logging.debug("Extracted plan details: %s", details)
    return details

def convert_to_gb(data_str):
    """
    Converts the processed data string from the plans to a numeric value in gigabytes.
    If the string ends with 'MB', converts it to GB.
    Otherwise, assumes the value is in GB.
    """
    if isinstance(data_str, str) and data_str.strip().upper().endswith("MB"):
        try:
            # Remove 'MB' and convert to float, then divide by 1024.
            return float(data_str.upper().replace("MB", "").strip()) / 1024
        except:
            return 0.0
    try:
        return float(data_str)
    except:
        return 0.0

def recommend_plan(user_message: str, current_details: dict = None) -> pd.DataFrame:
    """
    Recommend up to 3 postpaid plans from the cached plans based on provided plan details or keywords,
    ensuring no duplicate carriers in the final recommendations.

    The logic prioritizes plans that:
      - Are postpaid only.
      - Offer at least as much data as the user's current plan (using the numeric 'data_gb' conversion).
      - Are cheaper or equal in price to what the customer is paying.
      - Are from a provider different than the customer's current provider.
      - Are from distinct carriers (no duplicates).

    If fewer than 3 plans meet those criteria, the price constraint is relaxed, and if no matches are found,
    the function defaults to returning the 3 cheapest postpaid plans from distinct carriers.
    """
    # Get the plans data and ensure it's a DataFrame.
    plans_data = ensure_dataframe(get_cached_plans())
    
    # Filter to include only postpaid plans.
    plans_data = plans_data[plans_data["plan_type"] == "postpaid"].copy()
    
    # Convert the 'data' field to a numeric value in GB.
    plans_data["data_gb"] = plans_data["data"].apply(convert_to_gb)
    
    lower_msg = user_message.lower()
    recommended = pd.DataFrame()

    def drop_duplicate_carriers(df: pd.DataFrame) -> pd.DataFrame:
        """
        Given a sorted DataFrame, keep only the cheapest plan for each carrier
        by dropping duplicates in the 'carrier' column. 
        """
        return df.drop_duplicates(subset=["carrier"], keep="first")

    try:
        if current_details:
            current_price = current_details.get('plan_price', 0.0)
            current_data = current_details.get('plan_data', 0.0)
            current_provider = current_details.get('carrier', '').strip().lower()
            logging.debug("Plan details provided: Price=%s, Data=%s, Carrier=%s",
                          current_price, current_data, current_provider)

            # Always exclude the current provider
            filtered_plans = plans_data[plans_data["carrier"].str.lower() != current_provider]

            if current_data:
                # 1) Filter for plans with at least as much data and cheaper or equal price.
                candidate = filtered_plans[
                    (filtered_plans["data_gb"] >= current_data) &
                    (filtered_plans["price"] <= current_price)
                ].copy()
                candidate.sort_values(by="price", ascending=True, inplace=True)

                # Keep only the cheapest plan per carrier
                candidate = drop_duplicate_carriers(candidate)

                # Grab up to 3
                recommended = candidate.head(3)
                
                # 2) If we don't have 3 matches, ignore the price constraint (still exclude same carrier).
                if len(recommended) < 3:
                    candidate2 = filtered_plans[filtered_plans["data_gb"] >= current_data].copy()
                    candidate2.sort_values(by="price", ascending=True, inplace=True)
                    candidate2 = drop_duplicate_carriers(candidate2)

                    merged = pd.concat([recommended, candidate2]).drop_duplicates()
                    # Sort the merged set again by price
                    merged.sort_values(by="price", ascending=True, inplace=True)
                    merged = drop_duplicate_carriers(merged)

                    recommended = merged.head(3)
                
                # 3) If still empty, fallback to the 3 cheapest postpaid plans from distinct carriers, excluding current provider.
                if recommended.empty:
                    fallback = drop_duplicate_carriers(filtered_plans.sort_values(by="price"))
                    recommended = fallback.head(3)
            else:
                # If no data usage found, fallback to the 3 cheapest distinct carriers from this provider filter.
                fallback = drop_duplicate_carriers(filtered_plans.sort_values(by="price"))
                recommended = fallback.head(3)
                logging.debug("No data usage in plan details; returning cheapest distinct carriers postpaid plans (excluding current provider).")
        else:
            # Fallback if no plan details: keyword-based logic, still ensuring distinct carriers.
            candidate = plans_data.copy()
            
            if "unlimited" in lower_msg or "stream" in lower_msg:
                mask = candidate["plan_features"].astype(str).str.lower().str.contains("unlimited", na=False)
                candidate = candidate[mask].copy()
                if candidate.empty:
                    logging.info("No unlimited plans found; using all postpaid plans.")
                    candidate = plans_data.copy()
            elif "cheap" in lower_msg or "budget" in lower_msg:
                # We'll just pick the cheapest at the end; no extra filter needed here
                pass
            elif "family" in lower_msg or "multiple lines" in lower_msg:
                mask = candidate["plan_name"].astype(str).str.lower().str.contains("family", na=False)
                candidate = candidate[mask].copy()
                if candidate.empty:
                    logging.info("No family plans found; defaulting to all postpaid plans.")
                    candidate = plans_data.copy()
            
            candidate.sort_values(by="price", ascending=True, inplace=True)
            candidate = drop_duplicate_carriers(candidate)
            recommended = candidate.head(3)

        return recommended
    except Exception as e:
        logging.error("Exception in recommend_plan: %s", e)
        raise


@app.route('/chat', methods=['POST'])
def chat():
    req_data = request.get_json(silent=True)
    if not req_data or "userMessage" not in req_data:
        return jsonify({'error': 'Bad Request: "userMessage" field is required.'}), 400

    user_message = req_data.get("userMessage", "").strip()
    app.logger.info("Received message: %s", user_message)

    # Use provided planDetails if available; otherwise, try extracting from the message.
    current_details = req_data.get("planDetails")
    if current_details:
        app.logger.info("Using provided planDetails: %s", current_details)
    else:
        current_details = extract_plan_details(user_message)
        app.logger.info("Extracted plan details from message: %s", current_details)

    # If no valid details are found, send a fallback message.
    if not current_details or not current_details.keys():
        fallback_message = (
            "I couldn't determine your current plan details from your input. "
            "If you're not sure, you can browse all our plans at "
            "<a href='all-plans.html'>all-plans.html</a> for a wider selection. "
            "Alternatively, please provide your plan price, data usage, and provider so I can give you a personalized recommendation."
        )
        return jsonify({
            "message": fallback_message,
            "currentPlanDetails": {},
            "recommendedPlans": []
        }), 200

    try:
        recommendation_df = recommend_plan(user_message, current_details)
    except Exception as e:
        app.logger.error("Error during plan recommendation: %s", e)
        return jsonify({'error': 'Internal Server Error. Please try again later.'}), 500

    recommended_plans = recommendation_df.to_dict(orient="records")
    response = {
        "message": "Based on your current plan details, here are my recommendations:",
        "currentPlanDetails": current_details,
        "recommendedPlans": recommended_plans
    }
    return jsonify(response), 200

# -------------------------------------------------------------------------
#                          RPA FLOWS
# -------------------------------------------------------------------------
# This section contains all carrier RPA flow implementations

def send_email_notification(email, name, carrier, status="processing"):
    """
    Send an email notification to the user about their activation status
    
    Args:
        email (str): User's email address
        name (str): User's name
        carrier (str): Carrier name
        status (str): Status of the activation (processing or complete)
        
    Returns:
        bool: True if email was sent (or would be sent in production), False otherwise
    """
    try:
        # Email credentials and setup would go here in production
        # This is a placeholder for demonstration purposes
        sender_email = "notifications@switchmyplan.ca"
        receiver_email = email
        
        # Create message
        msg = MIMEMultipart()
        msg['Subject'] = f"Your {carrier} activation status"
        msg['From'] = sender_email
        msg['To'] = receiver_email
        
        # Email body
        if status == "processing":
            body = f"""
            Hi {name},
            
            Thank you for choosing SwitchMyPlan.ca!
            
            Your {carrier} activation request is currently being processed. This process typically takes 24-48 hours to complete.
            
            We'll send you another email once your activation is complete with further instructions.
            
            If you have any questions, please reply to this email or contact our support team.
            
            Best regards,
            The SwitchMyPlan.ca Team
            """
        elif status == "complete":
            body = f"""
            Hi {name},
            
            Great news! Your {carrier} activation has been successfully completed.
            
            Your new service is now active. Please restart your device to ensure proper connectivity.
            
            If you have any questions or need further assistance, please reply to this email or contact our support team.
            
            Thank you for choosing SwitchMyPlan.ca!
            
            Best regards,
            The SwitchMyPlan.ca Team
            """
        
        # Attach the text to the email
        msg.attach(MIMEText(body, 'plain'))
        
        # In production, you would connect to an SMTP server and send the email
        # For demonstration, we'll just log the email content
        app.logger.info(f"Email would be sent to {receiver_email} with subject: {msg['Subject']}")
        app.logger.info(f"Email body: {body}")
        
        # In production, you would use code like this:
        """
        smtp_server = "smtp.example.com"
        port = 587  # For starttls
        smtp_username = "username"
        smtp_password = "password"
        
        # Create a secure SSL context
        context = ssl.create_default_context()
        
        with smtplib.SMTP(smtp_server, port) as server:
            server.ehlo()  # Can be omitted
            server.starttls(context=context)
            server.ehlo()  # Can be omitted
            server.login(smtp_username, smtp_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        """
        
        # For now, just simulate a delay
        time.sleep(1)
        return True
        
    except Exception as e:
        app.logger.error(f"Failed to send email notification: {str(e)}")
        return False



if __name__ == "__main__":
    import os
    port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    app.run(debug=True, port=port, host='0.0.0.0')