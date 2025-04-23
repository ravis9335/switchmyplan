# SwitchMyPlan - Mobile Plan Comparison Website

A comprehensive platform for comparing and purchasing mobile plans from various Canadian carriers.

## Features

- Display and compare plans from major Canadian carriers
- Featured postpaid and prepaid plan sections
- Interactive plan selection and checkout flow
- "Blue" AI chatbot assistant for plan recommendations
- RPA (Robotic Process Automation) integration for carrier sign-up processes

## Getting Started

### Prerequisites

- Python 3.7+
- pip (Python package manager)
- virtualenv (recommended)

### Installation

1. Clone the repository or unzip the project files

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install the required dependencies:
```bash
pip install -r requirements.txt
```

### Running the Application

1. Start the server:
```bash
python new_backend.py
```

2. Open your browser and navigate to:
```
http://127.0.0.1:5000
```

## Usage

### Browsing Plans
- Browse featured plans and prepaid plans in the respective sections
- Use the carousel navigation buttons to view more plans

### Selecting a Plan
- Click the "Select [Carrier] Plan" button on any plan card
- Follow the checkout process
- Enter your personal information to complete the order

### Chatting with Blue
- Navigate to the "Meet Blue" section
- Ask questions about plans and carriers
- Get personalized recommendations based on your needs

## File Structure

- `planB.html` - Main frontend file
- `new_backend.py` - Backend server with API endpoints and RPA integration
- `byop_plans.csv` - CSV file containing plan data
- `carrierlogos/` - Directory containing carrier logo images

## RPA Support

The current implementation includes RPA support for the following carriers:
- Virgin
- Fido
- Koodo

## Technical Details

- Frontend: HTML, CSS (Tailwind CSS), JavaScript
- Backend: Python, Flask
- RPA: Pyppeteer

## License

This project is proprietary and confidential.

## Contact

For support or inquiries, please contact the development team. 