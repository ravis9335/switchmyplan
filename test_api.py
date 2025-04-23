"""
Simple test script to verify the API endpoints for the new frontend.
"""

import requests
import json
import sys

BASE_URL = "http://localhost:5000"

def test_featured_plans():
    """Test the /api/plans/featured endpoint"""
    print("Testing /api/plans/featured endpoint...")
    try:
        response = requests.get(f"{BASE_URL}/api/plans/featured", timeout=5)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Received {len(data)} featured plans")
            if data:
                print("First plan:")
                print(json.dumps(data[0], indent=2))
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Exception: {e}")

def test_prepaid_plans():
    """Test the /api/plans/prepaid endpoint"""
    print("\nTesting /api/plans/prepaid endpoint...")
    try:
        response = requests.get(f"{BASE_URL}/api/plans/prepaid", timeout=5)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Received {len(data)} prepaid plans")
            if data:
                print("First plan:")
                print(json.dumps(data[0], indent=2))
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Exception: {e}")

def test_select_plan():
    """Test the /select_plan endpoint"""
    print("\nTesting /select_plan endpoint...")
    try:
        test_payload = {
            "carrier": "Koodo",
            "price": 45,
            "data": 10,
            "plan_id": 0
        }
        response = requests.post(
            f"{BASE_URL}/select_plan", 
            json=test_payload,
            timeout=5
        )
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Response: {json.dumps(data, indent=2)}")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    # Allow overriding the port through command line argument
    if len(sys.argv) > 1:
        port = sys.argv[1]
        BASE_URL = f"http://localhost:{port}"
    
    print(f"Testing API endpoints on {BASE_URL}")
    test_featured_plans()
    test_prepaid_plans()
    test_select_plan() 