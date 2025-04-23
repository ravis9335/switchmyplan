import asyncio
from new_backend import app, fido_flow_full

async def test_fido():
    """Test fido_flow_full function."""
    app.logger.info("Testing fido_flow_full function")
    
    session_id = "test-session"
    user_data = {
        "email": "test@example.com",
        "first_name": "Test",
        "last_name": "User",
        "phone": "9051234567",
        "address": "123 Test St",
        "city": "Toronto",
        "province": "ON",
        "postal_code": "M5V 2N4",
        "dob": "1990-01-01",
        "card_number": "4111111111111111",
        "card_expiry": "12/25",
        "cvv": "123",
        "id_type": "drivers_license",
        "id_number": "12345678",
    }
    
    plan_info = {
        "plan_name": "Fido 20 GB Plan",
        "plan_price": 55.00,
    }
    
    try:
        result = await fido_flow_full(session_id, user_data, plan_info)
        app.logger.info(f"Result: {result}")
        return result
    except Exception as e:
        app.logger.error(f"Error: {str(e)}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(test_fido())
    print("Test result:", result) 