import requests
import json
import threading
import time

# Import our new_backend app and functions
from new_backend import app, send_email_notification

def test_checkout_submit():
    # Start the app in a background thread
    def run_app():
        app.run(host='localhost', port=5000, debug=False)

    server_thread = threading.Thread(target=run_app)
    server_thread.daemon = True
    print('Starting Flask server...')
    server_thread.start()

    # Give the server a moment to start
    time.sleep(2)

    # Test multiple carriers
    carriers = ['Bell', 'Koodo', 'Virgin', 'Fido']
    
    for carrier in carriers:
        # Simulate a POST request to checkout_submit
        data = {
            'first_name': 'Test',
            'last_name': 'User',
            'email': 'test@example.com',
            'phone': '4165551234',
            'address': '123 Test Street',
            'city': 'Toronto',
            'province': 'ON',
            'postal_code': 'M5V 2K4',
            'dob': '01/01/1990',
            'carrier': carrier,
            'plan_name': '20GB Plan',
            'plan_price': '55',
            'activation_type': 'esim',
            'imei': '123456789012345',
            'card_number': '4111111111111111',
            'card_expiry': '12/25',
            'cvv': '123'
        }
    
        # Send the request
        try:
            print(f'\nTesting {carrier} activation:')
            print('Sending request to /checkout_submit...')
            response = requests.post('http://localhost:5000/checkout_submit', data=data)
            print(f'Response status code: {response.status_code}')
            print(f'Response content: {response.text}')
            
            # Wait for RPA process to start
            print('Waiting for activation to process...')
            time.sleep(5)  # Wait 5 seconds before testing next carrier
            
        except Exception as e:
            print(f'Error: {str(e)}')

    print("\nAll tests completed! Check the logs for full activation flow details.")
    
    # Keep the server running for a bit longer to see results
    time.sleep(10)

if __name__ == "__main__":
    test_checkout_submit() 