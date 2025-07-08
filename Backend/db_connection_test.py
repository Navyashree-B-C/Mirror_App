import os
from dotenv import load_dotenv
import httpx
import asyncio

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

headers = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"
}

async def test_supabase_rest_connection():
    try:
        async with httpx.AsyncClient() as client:
            # Just hit the root to check authentication — no table needed
            response = await client.get(
                f"{SUPABASE_URL}/rest/v1/", 
                headers=headers
            )
            if response.status_code == 200 or response.status_code == 404:
                print("✅ Connected to Supabase REST API (authentication succeeded)")
            else:
                print("⚠️ Got unexpected response:")
                print(response.status_code, response.text)
    except Exception as e:
        print("❌ Failed to connect to Supabase REST API.")
        print("Error:", e)

if __name__ == "__main__":
    asyncio.run(test_supabase_rest_connection())
