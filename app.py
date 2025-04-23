from flask import Flask, jsonify, send_file, send_from_directory
from flask_cors import CORS
import pandas as pd
import os
import time

PLANS_CSV_PATH = 'byop_plans.csv'
CACHE_REFRESH_INTERVAL = 300  # 5 minutes

app = Flask(__name__, static_url_path='', static_folder='.')
CORS(app)

# Cache for storing plans data
plans_cache = {
    'data': None,
    'last_refresh': 0
}

@app.route('/')
def root():
    return send_file('planB.html')

@app.route('/carrierlogos/<path:filename>')
def serve_carrier_logo(filename):
    return send_from_directory('carrierlogos', filename)

def load_plans_data():
    try:
        print(f"Reading CSV file from: {os.path.abspath(PLANS_CSV_PATH)}")
        df = pd.read_csv(PLANS_CSV_PATH)
        print(f"Found {len(df)} rows in CSV")
        
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
            'freedom_prepaid': 'Freedom'
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
                
                # Determine network speed based on carrier
                network_speed = '5G'
                if carrier in ['Chatr', 'Lucky', 'Public Mobile']:
                    network_speed = '4G LTE'
                
                # Process features
                features = []
                plan_name = str(row['plan_name']).lower()
                
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
                    'carrier': carrier,
                    'price': float(row['plan_price']),
                    'data': data_str,
                    'network_speed': network_speed,
                    'features': features,
                    'terms': 'No term contract required. Prices may vary by region.',
                    'plan_type': str(row['plan_type']).lower()
                }
                processed_plans.append(processed_plan)
                
            except Exception as e:
                print(f"Error processing row: {row}")
                print(f"Error details: {str(e)}")
                continue
        
        print(f"Successfully processed {len(processed_plans)} plans (skipped {skipped_count} invalid plans)")
        return processed_plans
        
    except Exception as e:
        print(f"Error loading plans: {str(e)}")
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
        
        featured_plans = [p for p in plans if p['plan_type'] == 'postpaid']
        print(f"Returning {len(featured_plans)} featured plans")
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
        
        prepaid_plans = [p for p in plans if p['plan_type'] == 'prepaid']
        print(f"Returning {len(prepaid_plans)} prepaid plans")
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

if __name__ == '__main__':
    # Load plans initially
    initial_plans = get_cached_plans()
    if initial_plans is None:
        print("Warning: Failed to load initial plans data")
    else:
        print(f"Successfully loaded {len(initial_plans)} plans initially")
    
    app.run(debug=True) 