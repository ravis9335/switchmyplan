import os
import time
import pandas as pd
import logging
import json
import uuid
import asyncio
import nest_asyncio
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Any
from flask import Flask, jsonify, request, render_template, session, redirect, url_for, send_file, send_from_directory, make_response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
from playwright.async_api import async_playwright
try:
    import agentql
except ImportError:
    agentql = None
    print("Warning: agentql module not found. Some RPA features may be limited.")

try:
    from playwright_stealth import stealth_async
except ImportError:
    stealth_async = None
    print("Warning: playwright_stealth module not found. Some RPA features may be limited.")

import random
import threading
import sys
import subprocess
import platform

# Constants and configuration
PLANS_CSV_PATH = 'byop_plans.csv'
CACHE_REFRESH_INTERVAL = 300  # 5 minutes
LOGS_DIR = "logs"
SCREENSHOTS_DIR = "screenshots"

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-please-change'
    SESSION_TIMEOUT = 30  # minutes
    MAX_RECOMMENDATIONS = 5
    RPA_TIMEOUT = 300  # seconds  # for the flows
    SCREENSHOT_DIR = "rpa_screenshots"
    DEBUG = True

# Setup logging and directories
def ensure_directories():
    """Ensure required directories exist"""
    dirs = [LOGS_DIR, SCREENSHOTS_DIR]
    for d in dirs:
        if not os.path.exists(d):
            os.makedirs(d)

def setup_logging():
    """Configure logging"""
    ensure_directories()
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(LOGS_DIR, "backend.log")),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# Initialize Flask app
app = Flask(__name__, static_url_path='', static_folder='.')
app.config.from_object(Config)
CORS(app)

# Initialize rate limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Initialize cache
cache = Cache(app, config={'CACHE_TYPE': 'simple'})

# Cache for storing plans data
plans_cache = {
    'data': None,
    'last_refresh': 0
}

# Sessions storage # -------------------------------------------------------------------------
#                          GLOBAL STATE
# -------------------------------------------------------------------------
conversation_context = {
    "state": "greeting",
    "recommended_plans": [],
    "plan_info": {},
    "user_data": {}
}
active_rpa_sessions = {}  # If you want to keep the browser open
active_sessions = {}      # Sessions for tracking user progress through the f

# Create and set the main asyncio event loop
nest_asyncio.apply()
main_loop = asyncio.new_event_loop()
asyncio.set_event_loop(main_loop)

# -------------------------------------------------------------------------
#                      HELPERS: BROWSER ANTI-DETECTION
# -------------------------------------------------------------------------
async def setup_stealth_browser(use_proxy=False):
    """
    Creates a stealth browser configuration with anti-detection measures.
    Returns playwright, browser, and context objects configured to avoid bot detection.
    
    Args:
        use_proxy: Whether to use a proxy server
    """
    from playwright.async_api import async_playwright
    import random
    
    # Start playwright and launch browser with GUARANTEED visibility
    playwright = await async_playwright().start()
    
    # CRITICAL: Force visible Chrome with specific launch args
    browser = await playwright.chromium.launch(
        channel="chrome",      # Use system Chrome
        headless=False,        # NEVER use headless for RPA
        slow_mo=50,            # Slow down operations for reliability
        args=[
            "--window-position=50,50",
            "--window-size=1280,800",
            "--disable-infobars",
            "--start-maximized"
        ]
    )
    
    # Create context with desktop-like settings
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    
    return playwright, browser, context

async def virgin_flow_full(session_id: str, user_data: dict, plan_info: dict):
    """
    Virgin entire activation flow in one pass:
      1) Navigate to Virgin's BYOP
      2) Select plan
      3) Fill personal info
      4) Fill credit card info, DOB, ID
      5) Final submission
    """
    from datetime import datetime
    import os
    import subprocess
    import sys
    import platform
    
    # Track start time for performance monitoring
    start_time = datetime.now()
    print(f"=== virgin_flow_full STARTING for session: {session_id} ===")
    print(f"User data: {user_data}")
    print(f"Plan info: {plan_info}")
    
    # Create screenshots directory for this session
    screenshots_dir = os.path.join(Config.SCREENSHOT_DIR, f"{session_id}_virgin")
    os.makedirs(screenshots_dir, exist_ok=True)
    print(f"Screenshots will be saved to: {screenshots_dir}")
    
    # Determine OS for proper browser launch
    system = platform.system()
    
    try:
        # DIRECT BROWSER LAUNCH APPROACH
        print("Launching browser directly via system call...")
        
        virgin_url = "https://www.virginplus.ca/en/plans/postpaid.html#!/BYOP/research"
        
        if system == "Darwin":  # macOS
            # On Mac, we can use the 'open' command to launch Chrome
            cmd = [
                "open", 
                "-a", 
                "Google Chrome", 
                virgin_url
            ]
            print(f"Executing macOS command: {' '.join(cmd)}")
            process = subprocess.Popen(cmd)
            
        elif system == "Windows":
            # On Windows, we can directly launch Chrome
            import winreg
            try:
                # Try to find Chrome's installation path from registry
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as key:
                    chrome_path = winreg.QueryValue(key, None)
                    cmd = [chrome_path, virgin_url]
                    print(f"Executing Windows command: {' '.join(cmd)}")
                    process = subprocess.Popen(cmd)
            except:
                # Fallback to common locations
                cmd = [r"C:\Program Files\Google\Chrome\Application\chrome.exe", virgin_url]
                print(f"Executing Windows command (fallback): {' '.join(cmd)}")
                process = subprocess.Popen(cmd)
                
        elif system == "Linux":
            # On Linux, try common commands to launch Chrome
            cmd = ["google-chrome", virgin_url]
            print(f"Executing Linux command: {' '.join(cmd)}")
            
            try:
                process = subprocess.Popen(cmd)
            except:
                # Try with chromium
                cmd = ["chromium-browser", virgin_url]
                print(f"Executing Linux command (fallback): {' '.join(cmd)}")
                process = subprocess.Popen(cmd)
        
        # Store browser process in active_rpa_sessions
        active_rpa_sessions[session_id] = {
            "process": process,
            "screenshots_dir": screenshots_dir,
            "system": system
        }
        
        # Log for user to see
        print("\n=================================")
        print("BROWSER LAUNCH COMMAND EXECUTED!")
        print("A Chrome window should now be visible on your desktop.")
        print("If you don't see it, check your taskbar/dock.")
        print("=================================\n")
        
        # Since we're no longer using Playwright here, we'll finish early
        # A more complete solution would include the RPA logic using Playwright
        return {
            "status": "success",
            "message": "Virgin activation flow started with direct browser launch",
            "screenshots_dir": screenshots_dir
        }
        
    except Exception as e:
        print(f"Error in Virgin flow: {str(e)}")
        import traceback
        traceback.print_exc()
        raise e
    
    finally:
        # Log execution time
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"Virgin flow initiation took {elapsed:.2f} seconds")

#Fido Flow 
        
       

# Placeholder for Koodo flow
async def koodo_flow_full(session_id: str, user_data: dict, plan_info: dict, timeout_seconds=180):
    """
    RPA flow for Koodo plan activation in one pass:
    1) Navigate to Koodo BYOP plans
    2) Select a plan
    3) Fill in user information
    4) Complete checkout
    """
    from datetime import datetime
    start_time = datetime.now()
    print(f"=== koodo_flow_full CALLED === session: {session_id}")
    
    browser_resources = {}
    screenshots_dir = os.path.join(Config.SCREENSHOT_DIR, f"{session_id}_koodo")
    os.makedirs(screenshots_dir, exist_ok=True)
    
    async def take_screenshot(name):
        """Take a screenshot for debugging"""
        screenshot_path = os.path.join(screenshots_dir, f"{name}.png")
        await page.screenshot(path=screenshot_path)
        print(f"Screenshot saved: {screenshot_path}")
    
    try:
        # Use our anti-detection browser setup with proxy
        use_proxy = random.choice([True, False])  # Randomly decide whether to use proxy
        playwright, browser, context = await setup_stealth_browser(use_proxy=use_proxy)
        page = await context.new_page()
        
        # Add random initial browsing behavior
        await page.goto("https://www.duckduckgo.com", wait_until="networkidle")
        await move_mouse_randomly(page)
        await page.wait_for_timeout(random.randint(1000, 3000))
        
        # 1) Navigate to Koodo BYOP plans
        start_url = "https://www.koodomobile.com/plans"
        await page.goto(start_url, wait_until="networkidle", timeout=60000)
        print("Navigated to Koodo plans page")
        
        # Check for and handle any bot challenges or cookie notices
        if await handle_bot_challenges(page):
            print("Handled bot challenges/cookie notices on Koodo site")
        
        await page.wait_for_timeout(random.randint(2000, 5000))
        
        # Simulate human browsing behavior
        await move_mouse_randomly(page)
        
        # Scroll down slowly to mimic reading behavior
        for _ in range(random.randint(2, 4)):
            await page.mouse.wheel(0, random.randint(100, 300))
            await page.wait_for_timeout(random.randint(800, 1500))
        
        # Take screenshot for debugging
        await take_screenshot("koodo_plans_page")
        
        # Rest of implementation would go here
        # ...
        
        # Save browser state for future sessions
        await save_browser_state(context, session_id)
        
        # Store browser resources for potential reuse
        browser_resources = {
            "playwright": playwright,
            "browser": browser,
            "context": context,
            "page": page
        }
        active_rpa_sessions[session_id] = browser_resources
        
        # Clean up resources
        await context.close()
        await browser.close()
        await playwright.stop()
        
        elapsed_time = (datetime.now() - start_time).total_seconds()
        print(f"Koodo flow completed successfully after {elapsed_time:.1f}s")
        
    except Exception as e:
        print(f"Koodo flow error: {str(e)}")
        # Try to take an error screenshot if possible
        try:
            if 'page' in locals() and page:
                error_screenshot_path = os.path.join(screenshots_dir, "error.png")
                await page.screenshot(path=error_screenshot_path)
                print(f"Error screenshot saved: {error_screenshot_path}")
        except:
            pass
        
        # Clean up resources
        for resource in browser_resources.values():
            try:
                if resource:
                    await resource.close()
            except:
                pass
        
        elapsed_time = (datetime.now() - start_time).total_seconds()
        print(f"Koodo flow failed after {elapsed_time:.1f}s")
        raise

# Helper functions for RPA
async def click_with_stealth(page, selector, timeout=5000):
    """Click on an element with stealth behavior"""
    try:
        # Wait for selector to be available
        await page.wait_for_selector(selector, timeout=timeout)
        
        # Get element dimensions for natural clicking
        element = await page.query_selector(selector)
        if not element:
            return False
            
        # Use a slightly randomized click position
        box = await element.bounding_box()
        if not box:
            return False
            
        # Click with a small random offset for more human-like behavior
        x = box['x'] + box['width'] / 2 + (random.random() * 4 - 2)
        y = box['y'] + box['height'] / 2 + (random.random() * 4 - 2)
        
        # Move mouse first, pause briefly, then click
        await page.mouse.move(x, y)
        await asyncio.sleep(0.1 + random.random() * 0.2)  # Random small delay
        await page.mouse.click(x, y)
        return True
    except Exception as e:
        logger.error(f"Error in click_with_stealth: {str(e)}")
        return False

# Plan data management functions
def load_plans_data():
    """Load and process plans data from CSV file"""
    try:
        logger.info(f"Reading CSV file from: {os.path.abspath(PLANS_CSV_PATH)}")
        df = pd.read_csv(PLANS_CSV_PATH)
        logger.info(f"Found {len(df)} rows in CSV")
        
        processed_plans = []
        skipped_count = 0
        
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
            'freedom_prepaid': 'Freedom',
            'lucky': 'Lucky'
        }
        
        for _, row in df.iterrows():
            try:
                # Skip plans with no price or invalid price
                if pd.isna(row['plan_price']) or row['plan_price'] == 'None' or row['plan_price'] <= 0:
                    skipped_count += 1
                    continue
                
                # Process carrier name
                carrier = str(row['carrier']).strip().lower()
                carrier = carrier_mapping.get(carrier, carrier.title())
                
                # Format data amount
                data_amount = float(row['plan_data'])
                if data_amount < 1:
                    data_amount = data_amount * 1024  # Convert to MB
                    data_str = f"{data_amount:.0f}MB"
                else:
                    data_str = f"{data_amount:.0f}"
                
                # Add plan ID for selection
                plan_id = str(row.get('id', hash(f"{carrier}_{data_str}_{row['plan_price']}")))
                
                # Process features
                features = []
                plan_name = str(row.get('plan_name', '')).lower()
                
                # Add standard features
                features.append({
                    'text': 'Canada-wide Calling',
                    'included': True
                })
                features.append({
                    'text': 'Unlimited Texting',
                    'included': True
                })
                
                # Add data-specific features
                if data_amount > 0:
                    features.append({
                        'text': 'Data Access',
                        'included': True
                    })
                
                # Add carrier-specific features
                if carrier in ['Virgin', 'Koodo']:
                    features.append({
                        'text': 'Data Rollover',
                        'included': True
                    })
                
                # Add plan-specific features
                if 'unlimited' in plan_name:
                    features.append({
                        'text': 'Unlimited Data',
                        'included': True
                    })
                if 'u.s.' in plan_name or 'us' in plan_name:
                    features.append({
                        'text': 'US Roaming',
                        'included': True
                    })
                if 'mex' in plan_name:
                    features.append({
                        'text': 'Mexico Roaming',
                        'included': True
                    })
                
                processed_plan = {
                    'id': plan_id,
                    'carrier': carrier,
                    'price': float(row['plan_price']),
                    'data': data_str,
                    'features': features,
                    'terms': 'No term contract required. Prices may vary by region.',
                    'plan_type': str(row.get('plan_type', 'postpaid')).lower()
                }
                processed_plans.append(processed_plan)
                
            except Exception as e:
                logger.error(f"Error processing row: {row}")
                logger.error(f"Error details: {str(e)}")
                continue
        
        logger.info(f"Successfully processed {len(processed_plans)} plans (skipped {skipped_count} invalid plans)")
        return processed_plans
        
    except Exception as e:
        logger.error(f"Error loading plans: {str(e)}")
        return None

def get_cached_plans():
    """Get plans data from cache or reload if needed"""
    current_time = time.time()
    if (plans_cache['data'] is None or 
        current_time - plans_cache['last_refresh'] > CACHE_REFRESH_INTERVAL):
        plans_cache['data'] = load_plans_data()
        plans_cache['last_refresh'] = current_time
    return plans_cache['data']

# Route handlers
@app.route('/')
def root():
    """Serve the main page"""
    try:
        logger.info("Serving planB.html from root route")
        # Read the file content 
        with open('planB.html', 'r') as file:
            html_content = file.read()
        
        # Return the HTML content directly with appropriate content type
        return html_content, 200, {'Content-Type': 'text/html'}
    except Exception as e:
        logger.error(f"Error serving planB.html: {str(e)}")
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Error</title>
        </head>
        <body>
            <h1>Error loading page</h1>
            <p>Could not load planB.html. Error: {str(e)}</p>
            <p>Current directory: {os.getcwd()}</p>
            <p>Files in directory: {', '.join(os.listdir('.'))}</p>
        </body>
        </html>
        """, 500, {'Content-Type': 'text/html'}

@app.route('/carrierlogos/<path:filename>')
def serve_carrier_logo(filename):
    """Serve carrier logo images"""
    return send_from_directory('carrierlogos', filename)

@app.route('/api/plans/featured')
def get_featured_plans():
    """API endpoint for featured plans"""
    try:
        plans = get_cached_plans()
        if plans is None:
            return jsonify({'error': 'Failed to load plans data'}), 500
        
        featured_plans = [p for p in plans if p.get('plan_type') == 'postpaid']
        logger.info(f"Returning {len(featured_plans)} featured plans")
        return jsonify(featured_plans)
    except Exception as e:
        logger.error(f"Error in get_featured_plans: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/plans/prepaid')
def get_prepaid_plans():
    """API endpoint for prepaid plans"""
    try:
        plans = get_cached_plans()
        if plans is None:
            return jsonify({'error': 'Failed to load plans data'}), 500
        
        prepaid_plans = [p for p in plans if p.get('plan_type') == 'prepaid']
        logger.info(f"Returning {len(prepaid_plans)} prepaid plans")
        return jsonify(prepaid_plans)
    except Exception as e:
        logger.error(f"Error in get_prepaid_plans: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/plans/reload')
def reload_plans():
    """Force reload of plans data"""
    plans_cache['data'] = None
    plans = get_cached_plans()
    if plans is None:
        return jsonify({'error': 'Failed to reload plans data'}), 500
    return jsonify({'message': 'Plans reloaded successfully'})

@app.route('/select_plan', methods=['POST'])
def select_plan():
    """Handle plan selection and initiate RPA flow"""
    try:
        data = request.json
        if not data:
            logger.error("No data provided in select_plan request")
            return jsonify({"success": False, "error": "No data provided"}), 400
            
        # Create session ID first so we can log issues with it
        session_id = str(uuid.uuid4())
        logger.info(f"New plan selection request: session_id={session_id}, data={data}")
        
        # Check for required fields with more detailed error reporting
        required_fields = ['carrier']
        missing_fields = [field for field in required_fields if field not in data or not data[field]]
        
        if missing_fields:
            error_msg = f"Missing required fields: {', '.join(missing_fields)}"
            logger.error(f"Session {session_id}: {error_msg}")
            return jsonify({"success": False, "error": error_msg}), 400
        
        # Generate plan_id if not provided
        if 'plan_id' not in data or not data['plan_id']:
            # Create a hash-based ID if none provided
            carrier = data.get('carrier', '')
            price = data.get('price', 0)
            data_amount = data.get('data', '0')
            data['plan_id'] = str(hash(f"{carrier}_{data_amount}_{price}"))
            logger.info(f"Session {session_id}: Generated plan_id {data['plan_id']}")
        
        # Look up the plan details from the cached plans to get plan_name
        plans = get_cached_plans()
        carrier = data.get('carrier', '').lower()
        price = float(data.get('price', 0))
        data_amount = data.get('data', '0')
        
        # Find the matching plan from our plans data
        plan_name = None
        for plan in plans:
            if (plan.get('carrier', '').lower() == carrier.lower() and
                abs(float(plan.get('price', 0)) - price) < 0.01 and
                plan.get('data', '') == data_amount):
                # This is likely our plan - get the plan_name from the plan record
                plan_name = plan.get('plan_name', f"{data_amount} GB data, talk & text")
                break
        
        # If we couldn't find a perfect match, try matching just carrier and price
        if not plan_name:
            for plan in plans:
                if (plan.get('carrier', '').lower() == carrier.lower() and
                    abs(float(plan.get('price', 0)) - price) < 0.01):
                    plan_name = plan.get('plan_name', f"{data_amount} GB data, talk & text")
                    break
        
        # If we still don't have a plan name, construct a default one
        if not plan_name:
            plan_name = f"{data_amount} GB data, talk & text"
        
        # Add plan_name to the data
        data['plan_name'] = plan_name
        logger.info(f"Associated plan name for session {session_id}: {plan_name}")
        
        # Store plan selection in session
        active_sessions[session_id] = {
            'created_at': datetime.now(),
            'plan_info': data,
            'status': 'selected',
            'user_data': {}
        }
        
        # Set cookie with session ID
        response = jsonify({"success": True, "session_id": session_id})
        response.set_cookie('session_id', session_id, max_age=Config.SESSION_TIMEOUT * 60)
        
        logger.info(f"Plan selected for session {session_id}: {data}")
        return response
        
    except Exception as e:
        logger.error(f"Unexpected error in select_plan: {str(e)}")
        return jsonify({"success": False, "error": "An unexpected error occurred. Please try again."}), 500

@app.route('/checkout', methods=['GET'])
def checkout():
    """Show checkout page after plan selection"""
    session_id = request.cookies.get('session_id')
    
    if not session_id or session_id not in active_sessions:
        return redirect('/')
    
    session_data = active_sessions[session_id]
    carrier = session_data['plan_info'].get('carrier', '').lower()
    
    # Find the plan details from the cached plans
    plans = get_cached_plans()
    plan_id = session_data['plan_info'].get('plan_id')
    
    plan_details = None
    for plan in plans:
        if plan.get('id') == plan_id:
            plan_details = plan
            break
    
    if not plan_details:
        return jsonify({"error": "Plan not found"}), 404
    
    # Prepare variables to avoid f-string issues
    carrier_display = carrier.capitalize()
    plan_data = plan_details.get('data', '')
    plan_price = plan_details.get('price', 0)
    
    # Create HTML header
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Checkout - {carrier_display} Plan</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{ background-color: #f5f5f7; font-family: system-ui, sans-serif; color: #333; }}
        .container {{ max-width: 1100px; margin: 0 auto; padding: 0 20px; }}
        .checkout-layout {{ display: flex; flex-wrap: wrap; gap: 30px; }}
        .checkout-form {{ flex: 1; min-width: 300px; background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); padding: 30px; }}
        .checkout-summary {{ width: 320px; background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); padding: 30px; }}
        .section {{ margin-bottom: 30px; padding-bottom: 20px; border-bottom: 1px solid #e1e1e1; }}
        .field-row {{ margin-bottom: 15px; }}
        .field-group {{ display: flex; gap: 15px; margin-bottom: 15px; }}
        .field {{ flex: 1; }}
        h1 {{ font-size: 24px; font-weight: 600; margin-bottom: 30px; }}
        h2 {{ font-size: 18px; font-weight: 600; margin-bottom: 20px; }}
        label {{ display: block; font-size: 14px; font-weight: 500; margin-bottom: 5px; color: #555; }}
        input, select {{ width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 15px; }}
        button {{ background-color: #0066cc; color: white; border: none; padding: 14px 20px; border-radius: 4px; font-size: 16px; font-weight: 500; width: 100%; cursor: pointer; }}
        .hidden {{ display: none; }}
        .summary-item {{ display: flex; justify-content: space-between; margin-bottom: 12px; }}
        .summary-total {{ display: flex; justify-content: space-between; margin-top: 20px; padding-top: 20px; border-top: 1px solid #e1e1e1; font-weight: 600; }}
        @media (max-width: 768px) {{ 
            .checkout-layout {{ flex-direction: column; }}
            .checkout-summary {{ width: 100%; }}
            .field-group {{ flex-direction: column; }}
        }}
    </style>
</head>
<body>
    <header style="background-color: white; padding: 15px 0; border-bottom: 1px solid #e1e1e1;">
        <div class="container">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div style="font-size: 18px; font-weight: 600; color: #0066cc;">SwitchMyPlan</div>
            </div>
        </div>
    </header>

    <main style="padding: 40px 0;">
        <div class="container">
            <h1>Complete Your Activation</h1>

            <div class="checkout-layout">
                <div class="checkout-form">
                    <form id="checkout-form" method="POST" action="/checkout_submit">
                        <input type="hidden" name="session_id" value="{session_id}">
"""

    # Add Personal Information Section
    html += """
                        <!-- Personal Information Section -->
                        <div class="section">
                            <h2>Personal Information</h2>

                            <div class="field-group">
                                <div class="field">
                                    <label for="first_name">First Name</label>
                                    <input type="text" id="first_name" name="first_name" required>
                                </div>
                                <div class="field">
                                    <label for="last_name">Last Name</label>
                                    <input type="text" id="last_name" name="last_name" required>
                                </div>
                            </div>

                            <div class="field-row">
                                <label for="email">Email Address</label>
                                <input type="email" id="email" name="email" required>
                            </div>

                            <div class="field-row">
                                <label for="phone">Phone Number</label>
                                <input type="tel" id="phone" name="phone" required>
                            </div>
                        </div>

                        <!-- Address Section -->
                        <div class="section">
                            <h2>Address</h2>

                            <div class="field-row">
                                <label for="address_line1">Street Address</label>
                                <input type="text" id="address_line1" name="address_line1" required>
                            </div>

                            <div class="field-row">
                                <label for="address_line2">Address Line 2 (Optional)</label>
                                <input type="text" id="address_line2" name="address_line2">
                            </div>

                            <div class="field-group">
                                <div class="field">
                                    <label for="city">City</label>
                                    <input type="text" id="city" name="city" required>
                                </div>
                                <div class="field">
                                    <label for="province">Province</label>
                                    <select id="province" name="province" required>
                                        <option value="">Select Province</option>
                                        <option value="AB">Alberta</option>
                                        <option value="BC">British Columbia</option>
                                        <option value="MB">Manitoba</option>
                                        <option value="NB">New Brunswick</option>
                                        <option value="NL">Newfoundland and Labrador</option>
                                        <option value="NS">Nova Scotia</option>
                                        <option value="NT">Northwest Territories</option>
                                        <option value="NU">Nunavut</option>
                                        <option value="ON">Ontario</option>
                                        <option value="PE">Prince Edward Island</option>
                                        <option value="QC">Quebec</option>
                                        <option value="SK">Saskatchewan</option>
                                        <option value="YT">Yukon</option>
                                    </select>
                                </div>
                            </div>

                            <div class="field-row">
                                <label for="postal_code">Postal Code</label>
                                <input type="text" id="postal_code" name="postal_code" required>
                            </div>
                        </div>

                        <!-- Phone Number Preference -->
                        <div class="section">
                            <h2>Phone Number Preference</h2>

                            <div class="field-row">
                                <label for="number_type">Number Preference</label>
                                <select id="number_type" name="number_type" required>
                                    <option value="">Select Preference</option>
                                    <option value="new">Get a New Number</option>
                                    <option value="port">Transfer My Existing Number</option>
                                </select>
                            </div>

                            <div id="transfer_number_field" class="field-row hidden">
                                <label for="current_number">Number to Transfer</label>
                                <input type="tel" id="current_number" name="current_number" placeholder="Enter the number you want to transfer">
                            </div>
                            
                            <div id="current_provider_field" class="field-row hidden">
                                <label for="current_provider">Current Provider</label>
                                <select id="current_provider" name="current_provider">
                                    <option value="">Select Current Provider</option>
                                    <option value="Bell">Bell</option>
                                    <option value="Rogers">Rogers</option>
                                    <option value="Telus">Telus</option>
                                    <option value="Fido">Fido</option>
                                    <option value="Koodo">Koodo</option>
                                    <option value="Freedom">Freedom</option>
                                    <option value="Chatr">Chatr</option>
                                    <option value="Public Mobile">Public Mobile</option>
                                </select>
                            </div>
                        </div>

                        <!-- Credit Check Information -->
                        <div class="section">
                            <h2>Credit Check Information</h2>

                            <div class="field-row">
                                <label for="dob">Date of Birth (YYYY-MM-DD)</label>
                                <input type="text" id="dob" name="dob" placeholder="YYYY-MM-DD" required>
                            </div>
"""
    
    # Add ID Information section only for non-Virgin carriers
    if carrier != 'virgin':
        html += """
                            <!-- ID Information -->
                            <div class="field-row">
                                <label for="id_type">ID Type</label>
                                <select id="id_type" name="id_type" required>
                                    <option value="">Select ID Type</option>
                                    <option value="drivers_license">Driver's License</option>
                                    <option value="sin">Social Insurance Number (SIN)</option>
                                </select>
                            </div>

                            <div class="field-row">
                                <label for="id_number">ID Number</label>
                                <input type="text" id="id_number" name="id_number" required>
                            </div>
"""
    
    # Continue with the rest of the form
    html += """
                        </div>

                        <!-- Payment Information -->
                        <div class="section">
                            <h2>Payment Information</h2>

                            <div class="field-row">
                                <label for="card_number">Card Number</label>
                                <input type="text" id="card_number" name="card_number" placeholder="1234 5678 9012 3456" required>
                            </div>

                            <div class="field-group">
                                <div class="field">
                                    <label for="expiry_month">Expiry Month</label>
                                    <select id="expiry_month" name="expiry_month" required>
                                        <option value="">MM</option>
                                        <option value="01">01</option>
                                        <option value="02">02</option>
                                        <option value="03">03</option>
                                        <option value="04">04</option>
                                        <option value="05">05</option>
                                        <option value="06">06</option>
                                        <option value="07">07</option>
                                        <option value="08">08</option>
                                        <option value="09">09</option>
                                        <option value="10">10</option>
                                        <option value="11">11</option>
                                        <option value="12">12</option>
                                    </select>
                                </div>
                                <div class="field">
                                    <label for="expiry_year">Expiry Year</label>
                                    <select id="expiry_year" name="expiry_year" required>
                                        <option value="">YY</option>
                                        <option value="2024">2024</option>
                                        <option value="2025">2025</option>
                                        <option value="2026">2026</option>
                                        <option value="2027">2027</option>
                                        <option value="2028">2028</option>
                                        <option value="2029">2029</option>
                                        <option value="2030">2030</option>
                                    </select>
                                </div>
                                <div class="field">
                                    <label for="cvv">Security Code (CVV)</label>
                                    <input type="text" id="cvv" name="cvv" placeholder="123" required>
                                </div>
                            </div>
                        </div>

                        <button type="submit">Complete Activation</button>
                    </form>
                </div>
"""
    
    # Add order summary section
    html += f"""
                <div class="checkout-summary">
                    <h2>Order Summary</h2>
                    
                    <div style="padding: 15px 0; margin-bottom: 15px; border-bottom: 1px solid #e1e1e1;">
                        <div style="font-weight: 600; margin-bottom: 5px;">{carrier_display} {plan_data} Plan</div>
                        <div style="font-size: 14px; color: #666;">{plan_data} Data Plan</div>
                        <div>${plan_price}/mo</div>
                    </div>
                    
                    <div class="summary-item">
                        <span>Monthly fee</span>
                        <span>${plan_price}</span>
                    </div>
                    
                    <div class="summary-item">
                        <span>Activation fee</span>
                        <span>$0.00</span>
                    </div>
                    
                    <div class="summary-item">
                        <span>Estimated tax</span>
                        <span>$8.00</span>
                    </div>
                    
                    <div class="summary-total">
                        <span>Total</span>
                        <span>${plan_price}/mo</span>
                    </div>
                    
                    <div style="display: flex; align-items: center; gap: 10px; padding: 15px; margin-top: 20px; background-color: #f5f5f7; border-radius: 4px; font-size: 14px; color: #666;">
                        <span style="color: #0066cc; font-size: 18px;">🔒</span>
                        <span>Your payment information is securely encrypted</span>
                    </div>
                </div>
            </div>
        </div>
    </main>
"""

    # Add JavaScript
    html += """
    <script>
        // Toggle transfer number field visibility
        document.getElementById('number_type').addEventListener('change', function() {
            const transferField = document.getElementById('transfer_number_field');
            if (this.value === 'port') {
                transferField.classList.remove('hidden');
                document.getElementById('current_number').required = true;
                document.getElementById('current_provider_field').classList.remove('hidden');
            } else {
                transferField.classList.add('hidden');
                document.getElementById('current_number').required = false;
                document.getElementById('current_provider_field').classList.add('hidden');
            }
        });
        
        // Submit form via AJAX
        document.getElementById('checkout-form').addEventListener('submit', function(e) {
            e.preventDefault();
            
            // Show loading state
            const submitBtn = this.querySelector('button[type="submit"]');
            const originalText = submitBtn.textContent;
            submitBtn.disabled = true;
            submitBtn.textContent = 'Processing...';
            
            // Collect form data
            const formData = new FormData(this);
            const data = {};
            formData.forEach((value, key) => {
                data[key] = value;
            });
            
            // Send request
            fetch('/checkout_submit', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            })
            .then(response => response.json())
            .then(result => {
                if (result.success || result.status === 'success') {
                    window.location.href = '/confirmation';
                } else {
                    alert('Error: ' + (result.message || result.error || 'Unknown error'));
                    submitBtn.disabled = false;
                    submitBtn.textContent = originalText;
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('An error occurred. Please try again.');
                submitBtn.disabled = false;
                submitBtn.textContent = originalText;
            });
        });
    </script>
</body>
</html>"""
    
    return html

@app.route('/checkout_submit', methods=['POST'])
def checkout_submit():
    """
    Handle the checkout form submission.
    Start RPA flow for the carrier activation.
    """
    print("Received checkout_submit request")
    
    try:
        # Get the form data - handle both form data and JSON data
        if request.is_json:
            form_data = request.get_json()
            print(f"Received JSON data: {form_data}")
        else:
            form_data = request.form.to_dict()
            print(f"Received form data: {form_data}")
        
        # Get the session ID (create a new one if needed)
        session_id = request.cookies.get('session_id')
        if not session_id:
            session_id = str(uuid.uuid4())
            print(f"Created new session ID: {session_id}")
        
        print(f"Using session ID: {session_id}")
        
        # Ensure session exists
        if session_id not in active_sessions:
            active_sessions[session_id] = {'status': 'new'}
            print(f"Created new session entry for {session_id}")
        
        # Get plan info from session
        plan_info = active_sessions.get(session_id, {}).get('plan_info', {})
        if not plan_info:
            # Try to get from the form data
            plan_info = form_data.get('plan_info', {})
            
        # Get carrier from plan info
        carrier = plan_info.get('carrier', '').lower() if plan_info else ''
        
        # Get or create user data
        user_data = active_sessions.get(session_id, {}).get('user_data', {})
        if not user_data:
            # Try to get from the form data or create new
            user_data = form_data.get('user_data', {})
            if not user_data:
                # Extract user data from form fields
                user_data = {
                    'first_name': form_data.get('first_name', ''),
                    'last_name': form_data.get('last_name', ''),
                    'email': form_data.get('email', ''),
                    'phone': form_data.get('phone', ''),
                    'address': form_data.get('address', ''),
                    'city': form_data.get('city', ''),
                    'province': form_data.get('province', ''),
                    'postal_code': form_data.get('postal_code', ''),
                    'payment': {
                        'card_number': form_data.get('card_number', '').replace(' ', ''),
                        'expiry_month': form_data.get('expiry_month', ''),
                        'expiry_year': form_data.get('expiry_year', ''),
                        'cvv': form_data.get('cvv', '')
                    }
                }
        
        print(f"Processing checkout for carrier: {carrier} with session: {session_id}")
        print(f"Plan info: {plan_info}")
        print(f"User data: {user_data}")
        
        # Update session with latest data
        active_sessions[session_id] = {
            'user_data': user_data,
            'plan_info': plan_info,
            'carrier': carrier,
            'start_time': datetime.now(),
            'status': 'pending'
        }
        
        # Implement carrier-specific flows
        if carrier == 'virgin':
            print(f"Starting Virgin flow for session {session_id}")
            
            # Define the flow function
            def run_virgin_flow():
                try:
                    print(f"Inside run_virgin_flow for session {session_id}")
                    print(f"User data: {user_data}")
                    print(f"Plan info: {plan_info}")
                    
                    # Create a task for the Virgin flow using run_coroutine_threadsafe
                    future = asyncio.run_coroutine_threadsafe(
                        virgin_flow_full(
                            session_id=session_id,
                            user_data=user_data,
                            plan_info=plan_info
                        ),
                        main_loop
                    )
                    
                    # Store the future for status tracking
                    active_sessions[session_id]['future'] = future
                    active_sessions[session_id]['status'] = 'flow_started'
                    active_sessions[session_id]['progress'] = 0
                    
                    # Create a new thread to process flow results when done
                    threading.Thread(
                        target=process_rpa_flow,
                        args=(session_id, future, 'virgin'),
                        daemon=True
                    ).start()
                    
                    print(f"Virgin flow successfully initiated for session {session_id}")
                    
                except Exception as e:
                    print(f"Error starting Virgin flow: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    active_sessions[session_id]['status'] = 'flow_error'
                    active_sessions[session_id]['error'] = str(e)
            
            # Start the flow in a separate thread
            flow_thread = threading.Thread(target=run_virgin_flow)
            flow_thread.daemon = True
            flow_thread.start()
            
            # Return success response with session cookie
            resp = jsonify({
                'status': 'flow_started',
                'session_id': session_id,
                'message': 'Virgin activation flow has been initiated - check for a visible browser window!'
            })
            
            resp.set_cookie(
                'session_id', 
                session_id, 
                max_age=60*60*2,  # 2 hours
                httponly=True,
                samesite='Lax'
            )
            
            return resp
            
        elif carrier == 'fido':
            # Similar implementation for Fido
            return jsonify({
                'status': 'not_implemented',
                'message': 'Fido activation flow is not implemented yet'
            }), 501
            
        elif carrier == 'koodo':
            # Similar implementation for Koodo
            return jsonify({
                'status': 'not_implemented',
                'message': 'Koodo activation flow is not implemented yet'
            }), 501
            
        else:
            return jsonify({
                'status': 'error',
                'message': f'Unsupported carrier: {carrier}'
            }), 400
            
    except Exception as e:
        print(f"Error in checkout_submit: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'status': 'error',
            'message': f'Failed to start activation flow: {str(e)}'
        }), 500

def process_rpa_flow(session_id, future, carrier_name):
    """Process RPA flow in background"""
    try:
        # Wait for the flow to complete with timeout
        timeout = Config.RPA_TIMEOUT
        result = future.result(timeout=timeout)
        
        # Update session with result
        if session_id in active_sessions:
            active_sessions[session_id]['status'] = 'flow_completed'
            active_sessions[session_id]['flow_result'] = result
            active_sessions[session_id]['completion_time'] = datetime.now().isoformat()
            logger.info(f"{carrier_name.capitalize()} flow completed successfully for session {session_id}")
        else:
            logger.warning(f"Session {session_id} no longer exists after flow completion")
            
    except asyncio.TimeoutError:
        logger.error(f"RPA flow for {carrier_name} timed out after {timeout} seconds")
        if session_id in active_sessions:
            active_sessions[session_id]['status'] = 'flow_timeout'
            active_sessions[session_id]['error'] = f"RPA flow timed out after {timeout} seconds"
            
    except Exception as e:
        logger.error(f"Error in {carrier_name} RPA flow: {str(e)}")
        if session_id in active_sessions:
            active_sessions[session_id]['status'] = 'flow_error'
            active_sessions[session_id]['error'] = str(e)

@app.route('/confirmation', methods=['GET'])
def confirmation():
    """Show confirmation page after successful checkout"""
    session_id = request.cookies.get('session_id')
    
    if not session_id or session_id not in active_sessions:
        return redirect('/')
    
    session_data = active_sessions[session_id]
    carrier = session_data['plan_info'].get('carrier', '').capitalize()
    plan_info = session_data['plan_info']
    status = session_data.get('status', 'unknown')
    
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Order Confirmation - SwitchMyPlan</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            * {{
                box-sizing: border-box;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', sans-serif;
            }}
            body {{
                margin: 0;
                padding: 0;
                background-color: #f5f5f7;
                color: #333;
                line-height: 1.5;
            }}
            .container {{
                max-width: 700px;
                margin: 0 auto;
                padding: 0 20px;
            }}
            header {{
                background-color: white;
                padding: 15px 0;
                border-bottom: 1px solid #e1e1e1;
            }}
            .header-content {{
                display: flex;
                justify-content: space-between;
                align-items: center;
            }}
            .logo {{
                font-size: 18px;
                font-weight: 600;
                color: #0066cc;
            }}
            main {{
                padding: 40px 0;
            }}
            .confirmation-card {{
                background: white;
                border-radius: 8px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                padding: 30px;
                text-align: center;
            }}
            .success-icon {{
                font-size: 48px;
                color: #4CAF50;
                margin-bottom: 20px;
            }}
            .error-icon {{
                font-size: 48px;
                color: #f44336;
                margin-bottom: 20px;
            }}
            .pending-icon {{
                font-size: 48px;
                color: #ff9800;
                margin-bottom: 20px;
            }}
            h1 {{
                font-size: 24px;
                font-weight: 600;
                margin: 0 0 20px 0;
                color: #333;
            }}
            .confirmation-message {{
                font-size: 16px;
                margin-bottom: 30px;
            }}
            .order-details {{
                background-color: #f9f9f9;
                border-radius: 6px;
                padding: 20px;
                margin-bottom: 30px;
                text-align: left;
            }}
            .order-detail-row {{
                display: flex;
                justify-content: space-between;
                margin-bottom: 12px;
                font-size: 15px;
            }}
            .order-detail-row:last-child {{
                margin-bottom: 0;
            }}
            .order-detail-label {{
                font-weight: 500;
                color: #666;
            }}
            .next-steps {{
                margin-top: 30px;
                padding-top: 30px;
                border-top: 1px solid #e1e1e1;
            }}
            .next-steps h2 {{
                font-size: 18px;
                font-weight: 600;
                margin-bottom: 15px;
            }}
            .steps-list {{
                text-align: left;
                padding-left: 20px;
            }}
            .steps-list li {{
                margin-bottom: 10px;
            }}
            .home-button {{
                background-color: #0066cc;
                color: white;
                border: none;
                padding: 12px 20px;
                border-radius: 4px;
                font-size: 16px;
                font-weight: 500;
                cursor: pointer;
                display: inline-block;
                text-decoration: none;
                margin-top: 20px;
                transition: background-color 0.2s;
            }}
            .home-button:hover {{
                background-color: #0055aa;
            }}
            .status-message {{
                padding: 12px;
                border-radius: 4px;
                margin-bottom: 20px;
                font-weight: 600;
            }}
            .status-success {{
                background-color: #e8f5e9;
                color: #2e7d32;
            }}
            .status-error {{
                background-color: #ffebee;
                color: #c62828;
            }}
            .status-pending {{
                background-color: #fff8e1;
                color: #f57f17;
            }}
            #refresh-button {{
                background-color: #f5f5f7;
                color: #0066cc;
                border: 1px solid #0066cc;
                padding: 8px 16px;
                border-radius: 4px;
                font-size: 14px;
                font-weight: 500;
                cursor: pointer;
                display: inline-block;
                margin-top: 10px;
            }}
            #refresh-button:hover {{
                background-color: #e6f0ff;
            }}
            .loading {{
                display: inline-block;
                width: 20px;
                height: 20px;
                border: 2px solid rgba(0, 102, 204, 0.3);
                border-radius: 50%;
                border-top-color: #0066cc;
                animation: spin 1s ease-in-out infinite;
                margin-right: 8px;
                vertical-align: middle;
            }}
            @keyframes spin {{
                to {{ transform: rotate(360deg); }}
            }}
        </style>
    </head>
    <body>
        <header>
            <div class="container">
                <div class="header-content">
                    <div class="logo">SwitchMyPlan</div>
                </div>
            </div>
        </header>

        <main>
            <div class="container">
                <div class="confirmation-card">
    """
    
    # Show different content based on status
    if status == 'flow_completed':
        html += f"""
                    <div class="success-icon">✓</div>
                    <h1>Order Confirmed!</h1>
                    <div class="status-message status-success">
                        Your plan has been successfully activated!
                    </div>
                    <p class="confirmation-message">
                        Thank you for choosing {carrier}. Your plan activation has been processed successfully.
                    </p>
        """
    elif status == 'flow_error':
        error_message = session_data.get('error', 'An unknown error occurred')
        html += f"""
                    <div class="error-icon">✗</div>
                    <h1>Activation Error</h1>
                    <div class="status-message status-error">
                        There was a problem with your activation: {error_message}
                    </div>
                    <p class="confirmation-message">
                        Please contact our support team for assistance with your {carrier} plan activation.
                    </p>
        """
    elif status == 'flow_timeout':
        html += f"""
                    <div class="error-icon">⏱</div>
                    <h1>Activation Timeout</h1>
                    <div class="status-message status-error">
                        Your activation process took too long to complete.
                    </div>
                    <p class="confirmation-message">
                        Please contact our support team for assistance with your {carrier} plan activation.
                    </p>
        """
    else:
        # For pending or other states
        html += f"""
                    <div class="pending-icon">⟳</div>
                    <h1>Activation in Progress</h1>
                    <div class="status-message status-pending">
                        <span id="status-text">Your {carrier} plan activation is being processed...</span>
                        <div id="progress-indicator"></div>
                    </div>
                    <p class="confirmation-message">
                        Please wait while we process your activation. This page will automatically update.
                    </p>
                    <button id="refresh-button"><span class="loading"></span> Checking status...</button>
        """
    
    # Order details section (always show)
    html += f"""
                    <div class="order-details">
                        <div class="order-detail-row">
                            <span class="order-detail-label">Carrier:</span>
                            <span>{carrier}</span>
                        </div>
                        <div class="order-detail-row">
                            <span class="order-detail-label">Plan:</span>
                            <span>{plan_info.get('data', '')} Data Plan</span>
                        </div>
                        <div class="order-detail-row">
                            <span class="order-detail-label">Monthly Price:</span>
                            <span>${plan_info.get('price', '0')}/month</span>
                        </div>
                        <div class="order-detail-row">
                            <span class="order-detail-label">Order Reference:</span>
                            <span>SMP-{session_id[:8].upper()}</span>
                        </div>
                    </div>
    """
    
    # Next steps section (show different content based on status)
    if status in ['flow_completed', 'flow_started', 'checkout_complete']:
        html += """
                    <div class="next-steps">
                        <h2>What Happens Next</h2>
                        <ol class="steps-list">
                            <li>You'll receive a confirmation email within the next 10 minutes.</li>
                            <li>Your SIM card will be shipped to your address within 3-5 business days.</li>
                            <li>After receiving your SIM card, follow the enclosed instructions to activate your service.</li>
                        </ol>
                    </div>
        """
    else:
        html += """
                    <div class="next-steps">
                        <h2>Next Steps</h2>
                        <ol class="steps-list">
                            <li>Please contact our customer support at 1-800-123-4567 for assistance.</li>
                            <li>Have your order reference number ready when you call.</li>
                            <li>Our team will help you resolve any issues with your activation.</li>
                        </ol>
                    </div>
        """
    
    # Add home button and close div tags
    html += """
                    <a href="/" class="home-button">Return to Home</a>
                </div>
            </div>
        </main>
    """
    
    # Add JavaScript for auto-refresh if status is pending
    if status not in ['flow_completed', 'flow_error', 'flow_timeout']:
        html += f"""
        <script>
            let checkCount = 0;
            const maxChecks = 60;  // 5 minutes total (5 second intervals)
            
            function checkStatus() {{
                if (checkCount >= maxChecks) {{
                    document.getElementById('status-text').textContent = 'Activation taking longer than expected. Please check back later.';
                    document.getElementById('refresh-button').style.display = 'none';
                    return;
                }}
                
                fetch('/api/flow_status')
                    .then(response => response.json())
                    .then(data => {{
                        checkCount++;
                        
                        if (data.status === 'flow_completed') {{
                            window.location.reload();
                        }} else if (data.status === 'flow_error' || data.status === 'flow_timeout') {{
                            window.location.reload();
                        }} else {{
                            // Update progress indicator
                            const elapsed = data.elapsed_seconds || 0;
                            const percent = Math.min(Math.round((elapsed / {Config.RPA_TIMEOUT}) * 100), 95);
                            document.getElementById('progress-indicator').innerHTML = `<div style="height: 8px; width: 100%; background-color: #e1e1e1; border-radius: 4px; margin-top: 10px;"><div style="height: 8px; width: ${{percent}}%; background-color: #0066cc; border-radius: 4px;"></div></div>`;
                            
                            // Schedule next check
                            setTimeout(checkStatus, 5000);
                        }}
                    }})
                    .catch(error => {{
                        console.error('Error checking status:', error);
                        setTimeout(checkStatus, 10000);  // Try again after 10 seconds on error
                    }});
            }}
            
            // Start checking status
            setTimeout(checkStatus, 2000);
            
            // Manual refresh
            document.getElementById('refresh-button').addEventListener('click', function() {{
                this.disabled = true;
                this.innerHTML = '<span class="loading"></span> Checking status...';
                checkStatus();
                setTimeout(() => {{
                    this.disabled = false;
                }}, 2000);
            }});
        </script>
        """
    
    html += """
    </body>
    </html>
    """
    
    return html

@app.route('/api/chat', methods=['POST'])
def chat_with_blue():
    """Endpoint for Blue chatbot interactions with more sophisticated conversation handling"""
    global conversation_context
    try:
        data = request.json
        if not data or 'message' not in data:
            return jsonify({"error": "No message provided"}), 400
            
        user_message = data['message'].lower().strip()
        response = ""
        
        # STATE MACHINE FOR CONVERSATION FLOW
        if conversation_context["state"] == "greeting":
            conversation_context["state"] = "awaiting_confirmation"
            response = "Hello! I'm Blue, your personal plan advisor. Could you tell me about your current mobile plan or what you're looking for in a new plan? How much data do you typically use per month?"
        
        elif conversation_context["state"] == "awaiting_confirmation":
            # Extract data usage and budget hints from the message
            data_match = re.search(r'(\d+)\s*(gb|g|gig)', user_message)
            price_match = re.search(r'\$?(\d+)', user_message)
            
            # Update the context with what we can extract
            if data_match:
                data_amount = float(data_match.group(1))
                conversation_context["data_usage"] = data_amount
            
            if price_match:
                budget = float(price_match.group(1))
                conversation_context["budget"] = budget
            
            # Extract carrier mentions if any
            carriers = ["virgin", "fido", "koodo", "bell", "rogers", "telus", "freedom", "chatr"]
            for carrier in carriers:
                if carrier in user_message:
                    conversation_context["current_provider"] = carrier
                    break
            
            # Move to the recommendation stage
            conversation_context["state"] = "awaiting_plan_details"
            
            # Build a personalized response
            response_parts = ["Thanks for that information!"]
            
            if "data_usage" in conversation_context:
                response_parts.append(f"Based on your {conversation_context['data_usage']}GB data needs")
            else:
                response_parts.append("Based on what you've told me")
                
            if "budget" in conversation_context:
                response_parts.append(f"and your budget of around ${conversation_context['budget']}")
                
            response_parts.append("I can recommend some plans that might work for you. Would you like me to show you the best options?")
            
            response = " ".join(response_parts)
        
        elif conversation_context["state"] == "awaiting_plan_details":
            if "yes" in user_message or "sure" in user_message or "show" in user_message:
                # Generate recommendations
                plans = get_cached_plans()
                if plans is None:
                    return jsonify({"error": "Failed to load plans data"}), 500
                
                data_usage = conversation_context.get("data_usage", 5) # Default to 5GB if not specified
                budget = conversation_context.get("budget", 70) # Default to $70 if not specified
                current_provider = conversation_context.get("current_provider", "")
                
                # Filter plans based on criteria
                filtered_plans = []
                for plan in plans:
                    plan_data = plan.get('data', '0')
                    # Extract numeric value from data string (e.g., "20GB" -> 20)
                    try:
                        if 'MB' in plan_data:
                            plan_data_amount = float(plan_data.replace('MB', '')) / 1024  # Convert MB to GB
                        else:
                            plan_data_amount = float(plan_data.replace('GB', ''))
                        
                        if plan_data_amount >= data_usage and plan['price'] <= budget * 1.2:  # Allow 20% over budget
                            filtered_plans.append(plan)
                    except:
                        continue
                
                # Sort by price
                filtered_plans.sort(key=lambda x: x['price'])
                
                # Take top 3 recommendations
                recommendations = filtered_plans[:3]
                conversation_context["recommended_plans"] = recommendations
                conversation_context["state"] = "recommendations_provided"
                
                if recommendations:
                    response = "Based on your needs, here are my top recommendations:\n\n"
                    for i, plan in enumerate(recommendations):
                        response += f"{i+1}. {plan['carrier']} - {plan['data']} data for ${plan['price']}/month\n"
                    response += "\nWould you like to select one of these plans? Just say the number."
                else:
                    response = "I couldn't find plans matching your criteria exactly. Let me broaden the search a bit."
                    conversation_context["state"] = "awaiting_confirmation"
            else:
                response = "I'm here to help you find the best plan. Could you tell me more about your data usage and budget?"
        
        elif conversation_context["state"] == "recommendations_provided":
            # Check if user is selecting a plan by number
            number_match = re.search(r'^[1-3]$', user_message)
            if number_match:
                selected_index = int(number_match.group(0)) - 1
                if selected_index < len(conversation_context["recommended_plans"]):
                    selected_plan = conversation_context["recommended_plans"][selected_index]
                    conversation_context["selected_plan"] = selected_plan
                    conversation_context["state"] = "plan_selected"
                    
                    response = f"Great choice! You've selected the {selected_plan['carrier']} plan with {selected_plan['data']} data for ${selected_plan['price']}/month. Would you like to proceed with this plan? I can help you activate it."
                else:
                    response = "I don't have that many recommendations. Please select from the available options."
            elif "yes" in user_message or "activate" in user_message:
                if "selected_plan" in conversation_context:
                    response = "Perfect! You can activate this plan by clicking the 'Select Plan' button on the card for your chosen plan. Then you'll be guided through the activation process."
                else:
                    response = "Please select one of the recommended plans first by saying the number (1, 2, or 3)."
            else:
                response = "If you're not interested in these options, I can help you find different plans. What would you like to change about your search criteria?"
                conversation_context["state"] = "awaiting_confirmation"
        
        elif conversation_context["state"] == "plan_selected":
            if "activate" in user_message or "sign up" in user_message or "yes" in user_message:
                response = "Great! You can click the 'Select Plan' button on the card for your chosen plan to start the activation process. I'll guide you through each step."
            elif "no" in user_message or "change" in user_message:
                response = "No problem! Let's start over. What are you looking for in a mobile plan? How much data do you need?"
                conversation_context["state"] = "awaiting_confirmation"
            else:
                response = "Is there anything specific you'd like to know about this plan before activating it?"
        
        else:
            # Default response if state is unknown
            response = "I'm here to help you find the perfect mobile plan. What are you looking for?"
            conversation_context["state"] = "greeting"
        
        return jsonify({
            "response": response,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error in chat_with_blue: {str(e)}")
        return jsonify({"error": str(e), "response": "I'm having trouble processing your request right now. Please try again in a moment."}), 500

def cleanup_session(session_id):
    """Clean up session data"""
    if session_id in active_sessions:
        del active_sessions[session_id]
        logger.info(f"Cleaned up session {session_id}")

# Periodic cleanup of expired sessions
def cleanup_expired_sessions():
    """Remove expired sessions"""
    now = datetime.now()
    expired_threshold = now - timedelta(minutes=Config.SESSION_TIMEOUT)
    
    expired_sessions = []
    for session_id, session_data in active_sessions.items():
        if session_data['created_at'] < expired_threshold:
            expired_sessions.append(session_id)
    
    for session_id in expired_sessions:
        cleanup_session(session_id)
    
    if expired_sessions:
        logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")

# Scheduled task for cleanup
def run_scheduled_tasks():
    """Run periodic maintenance tasks"""
    while True:
        time.sleep(300)  # Run every 5 minutes
        cleanup_expired_sessions()

# Apply nest_asyncio to allow running async code from Flask
nest_asyncio.apply()

@app.route('/api/flow_status', methods=['GET'])
def check_flow_status():
    """Check the status of an RPA flow for a session"""
    try:
        session_id = request.cookies.get('session_id')
        
        if not session_id or session_id not in active_sessions:
            return jsonify({
                'success': False,
                'message': 'Invalid or expired session',
                'status': 'invalid_session'
            }), 400
        
        session_data = active_sessions[session_id]
        status = session_data.get('status', 'unknown')
        
        response = {
            'success': True,
            'status': status,
            'session_id': session_id
        }
        
        # Add additional info based on status
        if status == 'flow_error':
            response['error'] = session_data.get('error', 'Unknown error')
        
        elif status == 'flow_timeout':
            response['error'] = 'Activation process timed out'
        
        elif status == 'flow_completed':
            response['result'] = session_data.get('result', 'Activation completed successfully')
            
            if 'flow_start_time' in session_data and 'flow_end_time' in session_data:
                elapsed = session_data['flow_end_time'] - session_data['flow_start_time']
                response['elapsed_seconds'] = round(elapsed)
        
        elif status == 'flow_started':
            # Calculate elapsed time
            if 'flow_start_time' in session_data:
                elapsed = time.time() - session_data['flow_start_time']
                response['elapsed_seconds'] = round(elapsed)
                
                # Calculate estimated progress
                completion_percentage = min(round((elapsed / Config.RPA_TIMEOUT) * 100), 95)
                response['progress_percentage'] = completion_percentage
        
        return jsonify(response)
    
    except Exception as e:
        logger.error(f"Error checking flow status: {str(e)}")
        return jsonify({
            'success': False,
            'message': f"Error checking status: {str(e)}",
            'status': 'error'
        }), 500

# -------------------------------------------------------------------------
#                      HELPERS: HANDLE BOT CHALLENGES
# -------------------------------------------------------------------------
async def handle_bot_challenges(page, timeout=30000):
    """
    Detects and attempts to bypass common bot detection challenges 
    and cookie consent popups that may appear during navigation.
    
    Args:
        page: The Playwright page object
        timeout: Maximum time to wait for challenges in milliseconds
    
    Returns:
        Boolean indicating if any challenges were detected and handled
    """
    challenge_detected = False
    start_time = time.time()
    
    # Common challenge selectors and text patterns to look for
    challenge_selectors = [
        # reCAPTCHA
        "iframe[src*='recaptcha']",
        "div.g-recaptcha",
        "div[class*='recaptcha']",
        
        # hCaptcha
        "iframe[src*='hcaptcha']",
        
        # Cloudflare
        "iframe[src*='challenges.cloudflare.com']",
        "#challenge-running",
        "#cf-challenge-running",
        
        # Cookie notices/consent (common implementations)
        "[id*='cookie'][id*='banner']",
        "[class*='cookie'][class*='banner']",
        "[class*='cookie'][class*='consent']",
        "[class*='cookie'][class*='notice']",
        "[id*='cookie'][id*='consent']",
        "[id*='cookie'][id*='notice']",
        "[id*='gdpr']",
        "[class*='gdpr']",
        
        # Common cookie accept button patterns
        "button:has-text('Accept')",
        "button:has-text('Accept All')",
        "button:has-text('I Accept')",
        "button:has-text('Agree')",
        "button:has-text('OK')",
        "button:has-text('Continue')",
        "button:has-text('Got it')",
        "button:has-text('Allow')",
        "a:has-text('Accept')",
        "a:has-text('Accept All')"
    ]
    
    # Common challenge text indicators
    challenge_texts = [
        "checking if the site connection is secure",
        "checking your browser",
        "please wait while we verify",
        "please enable JavaScript",
        "please enable cookies",
        "validate your browser",
        "waiting for verification",
        "performing security checks",
        "human verification",
        "browser check",
        "security verification",
        "cookie policy",
        "cookie consent",
        "we use cookies",
        "this site uses cookies"
    ]
    
    app.logger.info("Checking for bot challenges and cookie notices...")
    
    while (time.time() - start_time) * 1000 < timeout:
        # Check for challenge selectors
        for selector in challenge_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    app.logger.info(f"Detected potential challenge element: {selector}")
                    
                    # If it's a cookie banner, try to accept
                    if "cookie" in selector.lower() or "accept" in selector.lower() or "gdpr" in selector.lower():
                        try:
                            # Try clicking the Accept button
                            for accept_btn in ["button:has-text('Accept')", "button:has-text('Accept All')", 
                                            "button:has-text('I Agree')", "button:has-text('OK')",
                                            "a:has-text('Accept')", "a:has-text('I Agree')"]:
                                if await page.query_selector(accept_btn):
                                    app.logger.info(f"Clicking cookie accept button: {accept_btn}")
                                    await page.click(accept_btn)
                                    challenge_detected = True
                                    # Wait for cookie banner to disappear
                                    await page.wait_for_timeout(2000)
                                    break
                        except Exception as e:
                            app.logger.warning(f"Error handling cookie notice: {str(e)}")
                    # If it's reCAPTCHA, we need to wait it out or try to solve it
                    elif "recaptcha" in selector.lower() or "hcaptcha" in selector.lower():
                        app.logger.warning("CAPTCHA detected. Waiting for timeout...")
                        # Wait longer to allow manual intervention if needed
                        await page.wait_for_timeout(5000)
                        challenge_detected = True
                    # Cloudflare or similar challenge
                    elif "challenge" in selector.lower() or "cf-" in selector.lower():
                        app.logger.warning("Security challenge detected. Waiting for resolution...")
                        # Cloudflare typically needs longer to resolve
                        await page.wait_for_timeout(10000)
                        challenge_detected = True
            except Exception as e:
                app.logger.warning(f"Error checking for challenge selector {selector}: {str(e)}")
        
        # Check for challenge text in page content
        page_content = await page.content()
        for text in challenge_texts:
            if text.lower() in page_content.lower():
                app.logger.info(f"Detected challenge text: '{text}'")
                # Wait a bit longer for automatic challenge resolution
                await page.wait_for_timeout(5000)
                challenge_detected = True
                break
        
        # If we found and handled a challenge, check again after a short wait
        if challenge_detected:
            await page.wait_for_timeout(2000)
            continue
        
        # No challenges detected, we can proceed
        break
    
    # Return whether any challenges were detected and handled
    return challenge_detected

async def save_browser_state(context, session_id):
    """
    Saves browser cookies and storage state to be reused in future sessions.
    This helps establish a browsing history that looks more human.
    
    Args:
        context: The browser context to save state from
        session_id: Unique session identifier
    """
    try:
        # Create a directory for storing browser states if it doesn't exist
        states_dir = os.path.join(os.getcwd(), "browser_states")
        os.makedirs(states_dir, exist_ok=True)
        
        # Save the storage state (cookies, localStorage, etc.)
        state_path = os.path.join(states_dir, f"storage_state_{session_id}.json")
        await context.storage_state(path=state_path)
        
        # Also save to the default location for general reuse
        await context.storage_state(path="storage_state.json")
        
        app.logger.info(f"Saved browser state for session {session_id}")
        return True
    except Exception as e:
        app.logger.error(f"Error saving browser state: {str(e)}")
        return False

async def detect_and_handle_bot_blocks(page, context, session_id):
    """
    Detects if we're being blocked or challenged due to bot detection
    and takes measures like rotating IP or clearing cookies.
    
    Args:
        page: The playwright page object
        context: The browser context
        session_id: The unique session ID
        
    Returns:
        Boolean indicating if block was detected and handled
    """
    # Common block indicators in page content
    block_indicators = [
        "access denied",
        "blocked",
        "captcha",
        "challenge",
        "suspicious activity",
        "unusual traffic",
        "automated requests",
        "verify you are human",
        "security check",
        "your IP address has been blocked",
        "too many requests",
        "rate limited",
        "temporary ban",
        "429", # HTTP code for too many requests
        "403", # HTTP code for forbidden
    ]
    
    try:
        # Check page content for block indicators
        page_content = await page.content()
        page_content = page_content.lower()
        
        for indicator in block_indicators:
            if indicator in page_content:
                app.logger.warning(f"Bot block detected: '{indicator}'")
                
                # Take screenshot of block
                screenshots_dir = os.path.join(Config.SCREENSHOT_DIR, f"{session_id}_blocks")
                os.makedirs(screenshots_dir, exist_ok=True)
                screenshot_path = os.path.join(screenshots_dir, f"block_{int(time.time())}.png")
                await page.screenshot(path=screenshot_path)
                
                # Handling strategies:
                
                # 1. Try clearing cookies and local storage
                app.logger.info("Clearing cookies and storage to bypass block")
                await context.clear_cookies()
                
                # 2. Clear browser cache
                session_storage_keys = await page.evaluate("""() => {
                    const keys = [];
                    for (let i = 0; i < sessionStorage.length; i++) {
                        keys.push(sessionStorage.key(i));
                    }
                    return keys;
                }""")
                for key in session_storage_keys:
                    await page.evaluate(f"sessionStorage.removeItem('{key}')")
                
                # 3. Clear localStorage
                local_storage_keys = await page.evaluate("""() => {
                    const keys = [];
                    for (let i = 0; i < localStorage.length; i++) {
                        keys.push(localStorage.key(i));
                    }
                    return keys;
                }""")
                for key in local_storage_keys:
                    await page.evaluate(f"localStorage.removeItem('{key}')")
                
                # 4. Rotate User-Agent
                new_user_agent = random.choice([
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.5938.132 Safari/537.36",
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36 Edg/116.0.1938.69"
                ])
                await context.set_extra_http_headers({"User-Agent": new_user_agent})
                
                # 5. Set Do Not Track flag differently
                await context.set_extra_http_headers({"DNT": random.choice(["0", "1"])})
                
                # 6. Wait a random amount of time to reduce request rate
                wait_time = random.randint(30, 60)
                app.logger.info(f"Waiting {wait_time} seconds before retrying...")
                await page.wait_for_timeout(wait_time * 1000)
                
                return True
        
        # No block detected
        return False
    
    except Exception as e:
        app.logger.error(f"Error in detect_and_handle_bot_blocks: {str(e)}")
        return False


# Update the navigation functions to use this in both flows at key points:

# In virgin_flow_full, add after navigation attempt:
        # Check if we're being blocked
        if await detect_and_handle_bot_blocks(page, context, session_id):
            # If we were blocked, try navigating again
            await page.goto(start_url, wait_until="networkidle", timeout=60000)
            print("Attempted to bypass block and navigate to Virgin BYOP offers page again")

if __name__ == '__main__':
    # Load plans initially
    initial_plans = get_cached_plans()
    if initial_plans is None:
        logger.warning("Failed to load initial plans data")
    else:
        logger.info(f"Successfully loaded {len(initial_plans)} plans initially")
    
    # Start background task for session cleanup
    cleanup_thread = threading.Thread(target=run_scheduled_tasks, daemon=True)
    cleanup_thread.start()
    
    # Start the Flask app on port 5001 to avoid conflicts
    app.run(debug=True, port=5001) 