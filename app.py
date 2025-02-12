from flask import Flask, request, jsonify
from flask_cors import CORS
import csv
import os
import requests
import json
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from twilio.rest import Client

app = Flask(__name__)
CORS(app)

load_dotenv() 

# Groq API Configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
account_sid =  os.getenv("account_sid")
auth_token =  os.getenv("auth_token")

# CSV File Path
CSV_FILE = "expenses.csv"
recipient = os.getenv("recipient") 


# Initialize Twilio client (Make sure to set your credentials)
client = Client(account_sid, auth_token) 

# Ensure CSV file exists with headers
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, mode="w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["user_id", "amount", "category", "description", "date"])

def send_whatsapp_message(to, message):
    response = client.messages.create(
        body=message,
        from_="whatsapp:+14155238886",  # Twilio sandbox number
        to=f"whatsapp:{to}"  # Pass recipient dynamically
    )
    return response.sid

# Function to resolve relative dates
def resolve_relative_date(date_str):
    today = datetime.today()

    # Predefined mappings for relative dates
    relative_dates = {
        "today": today,
        "yesterday": today - timedelta(days=1),
        "day before yesterday": today - timedelta(days=2),
        "tomorrow": today + timedelta(days=1),
        "day after tomorrow": today + timedelta(days=2),
    }

    # Directly mapped relative date
    if date_str.lower() in relative_dates:
        return relative_dates[date_str.lower()].strftime("%Y-%m-%d")

    # Handling "X days back" or "X days ago"
    match = re.search(r"(\d+)\s*days?\s*(back|ago)", date_str.lower())
    if match:
        days_ago = int(match.group(1))
        resolved_date = today - timedelta(days=days_ago)
        return resolved_date.strftime("%Y-%m-%d")

    # If format is unknown, return original string
    return date_str


# Classify request as Add or Query
def classify_request_with_llama(message):
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama3-8b-8192",
        "messages": [
            {"role": "system", "content": """You are an assistant that determines if the user wants to *add* an expense or *query* past expenses.  

            - If the user is reporting a new expense (e.g., "I spent 100 on lunch", "Bought groceries for 500"), classify it as *'add'*.  
            - If the user is asking about past expenses (e.g., "How much did I spend on food?", "Show my transactions"), classify it as *'query'*.
            - if the user is not asking query and not reporting a new expense , classify it as *'none'*.
            - Respond with ONLY one word: *'add'* or *'query'* or *'none'*. Do not explain.  
            """},
            {"role": "user", "content": message}
        ]
    }
    response = requests.post(GROQ_URL, json=payload, headers=headers)

    if response.status_code == 200:
        try:
            parsed_response = response.json()
            classification = parsed_response["choices"][0]["message"]["content"].strip().lower()
            return classification if classification in ["add", "query"] else None
        except KeyError:
            return None
    return None

# Extract search term (category OR item) from user query using Llama-3
def extract_query_term_with_llama(message):
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama3-8b-8192",
        "messages": [
            {
                "role": "system",
                "content": """Extract the *expense category or item name* from the user's query.  
                
                - If the user asks *"How much did I spend on food?"*, return "food".  
                - If they ask *"How much for a dustbin?"*, return "dustbin".  
                - If no category/item is found, return "unknown".  
                
                Respond with *ONLY the extracted term* (no explanations)."""
            },
            {"role": "user", "content": message}
        ]
    }
    response = requests.post(GROQ_URL, json=payload, headers=headers)

    if response.status_code == 200:
        try:
            extracted_term = response.json()["choices"][0]["message"]["content"].strip().lower()
            return extracted_term if extracted_term != "unknown" else None
        except KeyError:
            return None
    return None

#  Fetch filtered expenses (Checks Category + Description)
def fetch_filtered_expenses(user_id, search_term):
    expenses = []
    transactions = []
    search_term = search_term.replace('"', '').strip().lower()  

    print(f"🔍 Searching for: '{search_term}'")  # Debugging log

    with open(CSV_FILE, mode="r") as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row["user_id"] == user_id:
                category = row["category"].strip().lower()
                description = row["description"].strip().lower()
                date = row["date"].strip().lower()
                print(f"📂 Checking row - Category: '{category}', Description: '{description}', Date: '{date}'")  # Debugging log

                # Match in either Category OR Description
                if search_term in category or search_term in description or search_term in date:
                    amount = float(row["amount"])
                    expenses.append(amount)
                    transactions.append({
                        "amount": amount,
                        "category": row["category"],
                        "description": row["description"],
                        "date": row["date"]
                    })
                    print(f"✅ Match found! Amount: {amount}")  # Debugging log

    total_spent = sum(expenses)

    if total_spent > 0:
        response = f"You have spent a total of {total_spent} Rs on {search_term}.\nHere are your transactions:\n"
        for txn in transactions:
            response += f"- {txn['date']}: {txn['amount']} Rs ({txn['description']})\n"
    else:
        response = f"No expenses found for {search_term}."

    print(f"📢 Response: {response}")  # Debugging log
    return response



# Extract expense details
def parse_expense_with_llama(message):
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama3-8b-8192",
        "messages": [
            {"role": "system", "content": "Extract expense details from user input and return in JSON format with keys: amount, category, description, date."},
            {"role": "user", "content": message}
        ]
    }
    response = requests.post(GROQ_URL, json=payload, headers=headers)

    if response.status_code == 200:
        try:
            parsed_response = response.json()
            extracted_text = parsed_response["choices"][0]["message"]["content"].strip()

            # Extract JSON using regex
            json_match = re.search(r"{[\s\S]*}", extracted_text)
            if json_match:
                extracted_data = json.loads(json_match.group(0))

                # Resolve relative dates
                if "date" in extracted_data and extracted_data["date"]:
                    extracted_data["date"] = resolve_relative_date(extracted_data["date"])
                else:
                    extracted_data["date"] = datetime.today().strftime("%Y-%m-%d")

                return extracted_data
        except (KeyError, json.JSONDecodeError):
            return None
        return None



# Save expense to CSV
def save_expense_to_csv(user_id, amount, category, description, date):
    with open(CSV_FILE, mode="a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([user_id, amount, category, description, date])

# Webhook to process WhatsApp messages
from flask import request, jsonify

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        print(f"Headers: {request.headers}")
        print(f"Raw Data: {request.data}")

        # Handle Twilio's form-urlencoded data
        if request.content_type == "application/x-www-form-urlencoded":
            data = request.form.to_dict()
        else:
            data = request.get_json()

        print(f"Parsed Data: {data}")

        message_text = data.get("Body", "")
        user_id = data.get("From", "")

        print(f"Received Message: {message_text} from {user_id}")

        request_type = classify_request_with_llama(message_text)
        print(f"Request Type: {request_type}")

        if request_type == "add":
            parsed_expense = parse_expense_with_llama(message_text)
            print(f"Parsed Expense: {parsed_expense}")

            if parsed_expense:
                amount = parsed_expense.get("amount", 0)
                category = parsed_expense.get("category", "Unknown")
                description = parsed_expense.get("description", "")
                date = parsed_expense.get("date", str(datetime.now().date()))

                print(f"Amount: {amount}, Category: {category}, Description: {description}, Date: {date}")

                try:
                    save_expense_to_csv(user_id, amount, category, description, date)
                    print("Expense saved successfully")
                except Exception as e:
                    print(f"Error saving expense: {e}")
                    return jsonify({"error": "Failed to save expense"}), 500

                try:
                    send_whatsapp_message(recipient,"Expense added successfully ✅")
                    print("WhatsApp message sent")
                except Exception as e:
                    print(f"Error sending WhatsApp message: {e}")
                    return jsonify({"error": "Failed to send WhatsApp message"}), 500

                return jsonify({"message": "Expense added"}), 200

            else:
                print("Failed to parse expense")
                return jsonify({"message": "Could not extract expense details"}), 400

        elif request_type == "query":
            query_term = extract_query_term_with_llama(message_text)
            print(f"Extracted Query Term: {query_term}")
            
            if query_term:
                response_message = fetch_filtered_expenses(user_id, query_term)

                try:
                    send_whatsapp_message(recipient,response_message)
                    print("Query response sent")
                except Exception as e:
                    print(f"Error sending WhatsApp message: {e}")
                    return jsonify({"error": "Failed to send WhatsApp message"}), 500

                return jsonify({"message": response_message}), 200

            else:
                return jsonify({"message": "Could not identify query term"}), 400

        else:
            send_whatsapp_message(recipient,"I am here to help you manage your expenses!\nPlease enter or query valid expense😊")
            print("Could not classify request")
            return jsonify({"message": "Could not classify request"}), 400

    except Exception as e:
        print(f"Unexpected Error: {e}")
        return jsonify({"error": str(e)}), 500



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080,debug=True)
