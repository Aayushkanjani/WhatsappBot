from fastapi import HTTPException
from dotenv import load_dotenv
import httpx
import os
import json
import asyncio

# Load environment variables
load_dotenv()

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
RECIPIENT_WAID = os.getenv("RECIPIENT_WAID")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERSION = os.getenv("VERSION", "v21.0")
TEMPLATE_NAME = os.getenv("TEMPLATE_NAME", "reengagement_message")  

async def send_message(message: str):
    """
    Sends a WhatsApp message. If more than 24 hours have passed since the last user response,
    it automatically switches to sending a template message.
    """
    
    url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    data = {
        "messaging_product": "whatsapp",
        "to": RECIPIENT_WAID,
        "type": "text",
        "text": {"body": message}
    }

    print(f"Sending WhatsApp message to {RECIPIENT_WAID}: {message}")  
    print(f"Request URL: {url}")
    print(f"Request Headers: {json.dumps(headers, indent=2)}")
    print(f"Request Payload: {json.dumps(data, indent=2)}")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=data)
            response_data = response.json()

            print(f"Response Status: {response.status_code}")
            print(f"Response Body: {json.dumps(response_data, indent=2)}")

            if response.status_code == 200:
                return response_data

            # Check if the failure is due to the 24-hour window restriction
            if "error" in response_data and response_data["error"].get("code") == 131047:
                print("Message failed due to 24-hour limit. Switching to template message.")

                # Switch to sending a template message
                return await send_template_message()

            raise HTTPException(status_code=response.status_code, detail=f"WhatsApp API Error: {response_data}")

        except httpx.RequestError as e:
            print(f"Request Error: {str(e)}")  
            raise HTTPException(status_code=500, detail="Failed to connect to WhatsApp API.")
        
        except Exception as e:
            print(f"Unexpected Error: {str(e)}")  
            raise HTTPException(status_code=500, detail="An unexpected error occurred.")

async def send_template_message():
    """
    Sends a WhatsApp message using a pre-approved template to bypass the 24-hour restriction.
    """
    url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    data = {
        "messaging_product": "whatsapp",
        "to": RECIPIENT_WAID,
        "type": "template",
        "template": {
            "name": TEMPLATE_NAME,
            "language": { "code": "en_US" },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        { "type": "text", "text": "Hey, please respond so I can continue sending messages!" }
                    ]
                }
            ]
        }
    }

    print(f"Sending WhatsApp template message to {RECIPIENT_WAID}.")
    print(f"Request Payload: {json.dumps(data, indent=2)}")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=data)
            response_data = response.json()

            print(f"Template Response Status: {response.status_code}")
            print(f"Template Response Body: {json.dumps(response_data, indent=2)}")

            if response.status_code == 200:
                return response_data

            raise HTTPException(status_code=response.status_code, detail=f"WhatsApp API Template Error: {response_data}")

        except httpx.RequestError as e:
            print(f"Request Error: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to connect to WhatsApp API.")
        
        except Exception as e:
            print(f"Unexpected Error: {str(e)}")
            raise HTTPException(status_code=500, detail="An unexpected error occurred.")

if __name__ == '__main__':
    asyncio.run(send_message("Check"))
