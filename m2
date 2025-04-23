import openai
import pandas as pd
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# OpenAI API Setup
openai.api_key = "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"


# Load Plans Data
try:
    plans_data = pd.read_csv("updated_plans_data.csv")
except FileNotFoundError as e:
    print(f"File Load Error: {e}")
    exit()

# Conversation Context
conversation_context = {
    "state": "greeting",
    "selected_plan_code": None,
}


@app.route('/search', methods=['POST'])
def search():
    global conversation_context
    data = request.json
    user_query = data.get('query', '').strip().lower()

    # Use OpenAI to process greeting
    if conversation_context["state"] == "greeting":
        conversation_context["state"] = "awaiting_confirmation"
        openai_response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a friendly mobile plan advisor named Mark-2."},
                {"role": "user", "content": user_query}
            ]
        )
        response = openai_response['choices'][0]['message']['content']
        return jsonify({"response": response})

    # Confirmation State
    if conversation_context["state"] == "awaiting_confirmation":
        if "yes" in user_query:
            conversation_context["state"] = "awaiting_plan_details"
            return jsonify({
                "response": "Great! Please provide your plan details in the dialog box. Once submitted, I'll process them."
            })
        elif "no" in user_query:
            return jsonify({"response": "No problem! Let me know when you're ready to proceed."})
        else:
            return jsonify({"response": "Please answer with 'yes' or 'no'."})

    return jsonify({"response": "I encountered an issue. Please restart the conversation."})


@app.route('/submit_plan_details', methods=['POST'])
def submit_plan_details():
    global conversation_context
    data = request.json

    # Save details and transition to processing
    conversation_context.update({
        "budget": float(data.get("current_price", 0)),
        "data_usage": float(data.get("current_data_usage", 0)),
        "current_provider": data.get("current_provider", "").lower(),
        "open_to_switching": data.get("open_to_switching", "").lower() in ["y", "yes", "true"],
        "state": "processing",
        "us_roaming": data.get("us_roaming", "").lower() in ["y", "yes", "true"],
    })

    return jsonify({"response": "Details received! Let me find the best plan for you."})


@app.route('/recommend_plan', methods=['GET'])
def recommend_plan():
    global conversation_context

    # Extract context details
    budget = conversation_context.get("budget")
    data_usage = conversation_context.get("data_usage")
    open_to_switching = conversation_context.get("open_to_switching")
    us_roaming = conversation_context.get("us_roaming")

    # Filter plans based on dataset logic
    filtered_plans = plans_data[
        (plans_data["price in $"] <= budget) &
        (plans_data["data_amount in GB"] >= data_usage) &
        ((plans_data["US Roaming"] == "Y") if us_roaming else True)
    ]

    if not open_to_switching:
        filtered_plans = filtered_plans[filtered_plans["carrier"] == conversation_context.get("current_provider")]

    if filtered_plans.empty:
        openai_response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a mobile plan advisor."},
                {"role": "user", "content": "No plans were found for the user's criteria."}
            ]
        )
        return jsonify({"response": openai_response['choices'][0]['message']['content']})

    # Sort by best value (lowest price, highest data)
    filtered_plans = filtered_plans.sort_values(by=["price in $", "data_amount in GB"])

    # Generate OpenAI-assisted recommendation
    recommendations = filtered_plans.head(5).to_dict(orient="records")
    plans_list = "\n".join(
        f"{idx + 1}. Carrier: {plan['carrier']}, Plan Name: {plan['plan_name']}, Data: {plan['data_amount in GB']}GB, "
        f"Price: ${plan['price in $']}, US Roaming: {'Yes' if plan['US Roaming'] == 'Y' else 'No'}, Plan Code: {plan['plan_code']}"
        for idx, plan in enumerate(recommendations)
    )

    openai_response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a mobile plan advisor."},
            {"role": "user", "content": f"Based on the following dataset:\n{plans_list}"},
        ]
    )

    return jsonify({"response": openai_response['choices'][0]['message']['content']})


@app.route('/select_plan', methods=['POST'])
def select_plan():
    data = request.json
    plan_code = data.get('plan_code', '').strip()

    # Check if the plan code exists in the dataset
    selected_plan = plans_data[plans_data['plan_code'] == plan_code]

    if selected_plan.empty:
        return jsonify({"response": f"Sorry, I couldn't find a plan with the code '{plan_code}'. Could you double-check the plan code or select another plan?"})

    plan_details = selected_plan.iloc[0]
    response_message = (
        f"Great choice! You've selected the {plan_details['plan_name']} plan. Here are the details:\n"
        f"- Carrier: {plan_details['carrier']}\n"
        f"- Data Amount: {plan_details['data_amount in GB']}GB\n"
        f"- Price: ${plan_details['price in $']}\n"
        f"- US Roaming: {'Yes' if plan_details['US Roaming'] == 'Y' else 'No'}\n"
        f"- Plan Code: {plan_details['plan_code']}\n"
        "Would you like assistance with switching to this plan, or do you have other questions?"
    )

    return jsonify({"response": response_message})


if __name__ == "__main__":
    app.run(debug=True)