from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse, JSONResponse
from dotenv import load_dotenv
import os
import csv
import json
import re
import requests
from datetime import datetime, timedelta
from sendMessage import send_message

load_dotenv()

app = FastAPI()

# WhatsApp API Credentials
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")  
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
print(ACCESS_TOKEN)

# CSV File Path
CSV_FILE = "expenses.csv"

# Ensure CSV file exists with headers
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, mode="w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["user_id", "amount", "category", "description", "date"])

# Function to resolve relative dates
def resolve_relative_date(date_str):
    today = datetime.today()
    relative_dates = {
        "today": today,
        "yesterday": today - timedelta(days=1),
        "day before yesterday": today - timedelta(days=2),
        "tomorrow": today + timedelta(days=1),
        "day after tomorrow": today + timedelta(days=2),
    }
    
    if date_str.lower() in relative_dates:
        return relative_dates[date_str.lower()].strftime("%Y-%m-%d")
    
    match = re.search(r"(\d+)\s*days?\s*(back|ago)", date_str.lower())
    if match:
        days_ago = int(match.group(1))
        return (today - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    
    return date_str

# Classify request type
def classify_request(message):
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama3-8b-8192",
        "messages": [
            {"role": "system", "content": """Determine if user wants to 'add' an expense or 'query' past expenses. Respond with only 'add' or 'query'."""},
            {"role": "user", "content": message},
        ],
    }
    response = requests.post(GROQ_URL, json=payload, headers=headers)
    if response.status_code == 200:
        return response.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip().lower()
    return None

# Extract search term
def extract_query_term(message):
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama3-8b-8192",
        "messages": [
            {"role": "system", "content": "Extract expense category or item name from the user's query."},
            {"role": "user", "content": message},
        ],
    }
    response = requests.post(GROQ_URL, json=payload, headers=headers)
    if response.status_code == 200:
        return response.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip().lower()
    return None

# Extract expense details
def parse_expense(message):
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama3-8b-8192",
        "messages": [
            {"role": "system", "content": "Extract expense details: amount, category, description, and date."},
            {"role": "user", "content": message},
        ],
    }
    response = requests.post(GROQ_URL, json=payload, headers=headers)
    if response.status_code == 200:
        try:
            extracted_data = json.loads(response.json()["choices"][0]["message"]["content"].strip())
            extracted_data["date"] = resolve_relative_date(extracted_data.get("date", datetime.today().strftime("%Y-%m-%d")))
            return extracted_data
        except (KeyError, json.JSONDecodeError):
            return None
    return None

# Save expense
def save_expense(user_id, amount, category, description, date):
    with open(CSV_FILE, mode="a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([user_id, amount, category, description, date])

# Fetch expenses
def fetch_filtered_expenses(user_id, search_term):
    expenses = []
    with open(CSV_FILE, mode="r") as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row["user_id"] == user_id and (search_term in row["category"].lower() or search_term in row["description"].lower()):
                expenses.append(float(row["amount"]))
    return f"You have spent a total of {sum(expenses)} Rs on {search_term}." if expenses else f"No expenses found for {search_term}."

# Webhook verification
@app.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(hub_mode: str = Query(None, alias="hub.mode"), hub_challenge: str = Query(None, alias="hub.challenge"), hub_verify_token: str = Query(None, alias="hub.verify_token")):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return hub_challenge
    raise HTTPException(status_code=403, detail="Verification failed")

# Webhook message receiver
@app.post("/webhook")
async def receive_whatsapp_message(request: Request):
    data = await request.json()
    print(f"Incoming data: {json.dumps(data, indent=2)}")  # Log incoming webhook data

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                message_data = change.get("value", {}).get("messages", [{}])[0]
                user_phone = message_data.get("from")
                message_text = message_data.get("text", {}).get("body")
                
                print(f"Received message from {user_phone}: {message_text}") 
                
                if message_text:
                    request_type = classify_request(message_text)
                    print(f"Classified request as: {request_type}")  

                    if request_type == "add":
                        expense_data = parse_expense(message_text)
                        print(f"Parsed expense data: {expense_data}") 

                        if expense_data:
                            save_expense(user_phone, **expense_data)
                            response = await send_message("Expense added successfully ✅")
                            return JSONResponse(content={"message": "Expense added successfully.", "whatsapp_response": response})
                    
                    elif request_type == "query":
                        query_term = extract_query_term(message_text)
                        print(f"Extracted query term: {query_term}")  

                        if query_term:
                            final_msg = fetch_filtered_expenses(user_phone, query_term)
                            response = await send_message(final_msg)
                            return JSONResponse(content={"message": final_msg, "whatsapp_response": response})

                    return JSONResponse(content={"message": "Could not process request."})

        return JSONResponse(content={"status": "success"})
    
    except Exception as e:
        print(f"Error: {str(e)}")  
        return JSONResponse(content={"status": "error", "message": str(e)})

