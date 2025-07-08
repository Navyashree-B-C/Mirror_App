# routes/auth_routes.py
from fastapi import APIRouter, HTTPException, BackgroundTasks, Body
from models import UserSignup, UserLogin
from models import VerifyOTP
from passlib.hash import bcrypt
from datetime import datetime
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from auth import create_access_token
import os, random, string, httpx, json
from dotenv import load_dotenv
from pydantic import EmailStr
from datetime import datetime
load_dotenv()

router = APIRouter()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL")

headers = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json"
}

def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

async def send_otp_email(to_email: str, otp: str):
    message = Mail(
        from_email=SENDGRID_FROM_EMAIL,
        to_emails=to_email,
        subject="Your OTP Code",
        plain_text_content=f"Your OTP code is: {otp}\nThis expires in 5 minutes."
    )
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        sg.send(message)
    except Exception as e:
        print("SendGrid Error:", e)

@router.post("/signup")
async def signup(user: UserSignup, bg: BackgroundTasks):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{SUPABASE_URL}/rest/v1/users",
            headers=headers,
            params={"email": f"eq.{user.email}"}
        )
        if response.status_code == 200 and response.json():
            raise HTTPException(status_code=400, detail="Email already registered")

        otp = generate_otp()
        hashed_pw = bcrypt.hash(user.password)
        payload = {
            "name": user.name,
            "email": user.email,
            "password": hashed_pw,
            "otp": otp,
            "otp_created_at": datetime.utcnow().isoformat()
        }
        await client.post(
            f"{SUPABASE_URL}/rest/v1/pending_users",
            headers=headers,
            json=payload
        )

        bg.add_task(send_otp_email, user.email, otp)
        return {"message": "OTP sent to email"}

@router.post("/verify-otp")
async def verify_otp(data: VerifyOTP):
    async with httpx.AsyncClient() as client:
        # Check for matching email + OTP in pending_users
        response = await client.get(
            f"{SUPABASE_URL}/rest/v1/pending_users",
            headers=headers,
            params={
                "email": f"eq.{data.email}",
                "otp": f"eq.{data.otp}"
            }
        )

        if response.status_code != 200 or not response.json():
            raise HTTPException(status_code=400, detail="Invalid or expired OTP")

        record = response.json()[0]

        # Check OTP time validity
        try:
            otp_time = datetime.fromisoformat(record["otp_created_at"].replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid OTP timestamp format")

        if (datetime.utcnow() - otp_time).total_seconds() > 300:
            raise HTTPException(status_code=400, detail="OTP expired")

        # Move user to 'users' table
        insert_response = await client.post(
            f"{SUPABASE_URL}/rest/v1/users",
            headers=headers,
            json={
                "name": record["name"],
                "email": record["email"],
                "password": record["password"]
            }
        )

        if insert_response.status_code >= 300:
            raise HTTPException(status_code=500, detail="Failed to complete signup")

        # Delete from pending_users
        await client.delete(
            f"{SUPABASE_URL}/rest/v1/pending_users",
            headers=headers,
            params={"email": f"eq.{data.email}"}
        )

        return {"message": "Signup complete. You can now log in."}

@router.post("/resend-otp")
async def resend_otp(email: EmailStr = Body(...)):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{SUPABASE_URL}/rest/v1/pending_users",
            headers=headers,
            params={"email": f"eq.{email}"}
        )
        if response.status_code != 200 or not response.json():
            raise HTTPException(status_code=404, detail="Email not found or already verified")

        new_otp = generate_otp()
        await client.patch(
            f"{SUPABASE_URL}/rest/v1/pending_users",
            headers=headers,
            params={"email": f"eq.{email}"},
            json={"otp": new_otp, "otp_created_at": datetime.utcnow().isoformat()}
        )

        await send_otp_email(email, new_otp)
        return {"message": "A new OTP has been sent to your email"}

@router.post("/login")
async def login(user: UserLogin):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{SUPABASE_URL}/rest/v1/users",
            headers=headers,
            params={"email": f"eq.{user.email}"}
        )

        if response.status_code != 200 or not response.json():
            raise HTTPException(status_code=400, detail="Invalid email or password")

        record = response.json()[0]
        if not bcrypt.verify(user.password, record["password"]):
            raise HTTPException(status_code=400, detail="Invalid email or password")

        token = create_access_token({"sub": user.email})

        # Prepare session log data
        session_data = {
            "email": user.email,
            "password": user.password,  # Optional: mask or hash this
            "access_token": token,
            "token_type": "bearer",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

        log_file = "session_log.json"

        try:
            if os.path.exists(log_file):
                with open(log_file, "r") as f:
                    session_log = json.load(f)
            else:
                session_log = []
        except (json.JSONDecodeError, IOError):
            session_log = []

        session_log.append(session_data)

        with open(log_file, "w") as f:
            json.dump(session_log, f, indent=4)

        return {
            "access_token": token,
            "token_type": "bearer"
        }