from fastapi import APIRouter, HTTPException
import os
import httpx
import random
import string
import json
import logging
from datetime import datetime, timedelta

recovery_router = APIRouter()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
headers = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json"
}

OTP_STORE_FILE = "otp_store.json"
OTP_EXPIRY_MINUTES = 10

def generate_otp(length=6):
    return ''.join(random.choices(string.digits, k=length))

def store_otp(email, purpose, otp):
    # Store OTP with expiry in a local JSON file (for demo)
    now = datetime.utcnow()
    expiry = now + timedelta(minutes=OTP_EXPIRY_MINUTES)
    if os.path.exists(OTP_STORE_FILE):
        with open(OTP_STORE_FILE, "r") as f:
            data = json.load(f)
    else:
        data = {}
    data[email + ":" + purpose] = {"otp": otp, "expires_at": expiry.isoformat()}
    with open(OTP_STORE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def send_otp_email(email, subject, otp):
    # Simulate sending email by logging (replace with real email logic)
    logging.info(f"[EMAIL to {email}] {subject}: OTP is {otp}")
    # In production, integrate with an email service here

@recovery_router.post("/forgot-password")
async def forgot_password(email: str):
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{SUPABASE_URL}/rest/v1/users",
            headers=headers,
            params={"email": f"eq.{email}"}
        )
        if res.status_code != 200 or not res.json():
            raise HTTPException(status_code=404, detail="User not found")
        otp = generate_otp()
        store_otp(email, "password", otp)
        send_otp_email(email, "Password Reset", otp)
        return {"message": "OTP sent to your email for password reset."}

@recovery_router.post("/forgot-profile-pin")
async def forgot_profile_pin(email: str, profile_name: str):
    async with httpx.AsyncClient() as client:
        user_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/users",
            headers=headers,
            params={"email": f"eq.{email}"}
        )
        if user_res.status_code != 200 or not user_res.json():
            raise HTTPException(status_code=404, detail="User not found")
        user_id = user_res.json()[0]["user_id"]
        profile_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/profiles",
            headers=headers,
            params={"user_id": f"eq.{user_id}", "name": f"eq.{profile_name}"}
        )
        if profile_res.status_code != 200 or not profile_res.json():
            raise HTTPException(status_code=404, detail="Profile not found for this user")
        otp = generate_otp()
        store_otp(email, f"profile_pin:{profile_name}", otp)
        send_otp_email(email, f"Profile PIN Reset for '{profile_name}'", otp)
        return {"message": f"OTP sent to your email for profile PIN reset of '{profile_name}'."}

# Optionally, add a route to verify OTP (for both password and pin)
@recovery_router.post("/verify-otp")
async def verify_otp(email: str, purpose: str, otp: str):
    # purpose: 'password' or 'profile_pin:profilename'
    if os.path.exists(OTP_STORE_FILE):
        with open(OTP_STORE_FILE, "r") as f:
            data = json.load(f)
    else:
        raise HTTPException(status_code=400, detail="No OTPs found.")
    key = email + ":" + purpose
    entry = data.get(key)
    if not entry:
        raise HTTPException(status_code=400, detail="No OTP found for this purpose.")
    if entry["otp"] != otp:
        raise HTTPException(status_code=400, detail="Invalid OTP.")
    if datetime.utcnow() > datetime.fromisoformat(entry["expires_at"]):
        raise HTTPException(status_code=400, detail="OTP expired.")
    # Optionally, delete OTP after successful verification
    del data[key]
    with open(OTP_STORE_FILE, "w") as f:
        json.dump(data, f, indent=2)
    return {"message": "OTP verified. You may now reset your password or PIN."}

@recovery_router.post("/reset-password")
async def reset_password(email: str, new_password: str, otp: str):
    # 1. Verify OTP
    purpose = "password"
    # OTP verification logic (reuse from /verify-otp)
    if os.path.exists(OTP_STORE_FILE):
        with open(OTP_STORE_FILE, "r") as f:
            data = json.load(f)
    else:
        raise HTTPException(status_code=400, detail="No OTPs found.")
    key = email + ":" + purpose
    entry = data.get(key)
    if not entry:
        raise HTTPException(status_code=400, detail="No OTP found for this purpose.")
    if entry["otp"] != otp:
        raise HTTPException(status_code=400, detail="Invalid OTP.")
    if datetime.utcnow() > datetime.fromisoformat(entry["expires_at"]):
        raise HTTPException(status_code=400, detail="OTP expired.")
    # OTP is valid, delete it
    del data[key]
    with open(OTP_STORE_FILE, "w") as f:
        json.dump(data, f, indent=2)
    # 2. Update password in Supabase
    async with httpx.AsyncClient() as client:
        # Find user
        res = await client.get(
            f"{SUPABASE_URL}/rest/v1/users",
            headers=headers,
            params={"email": f"eq.{email}"}
        )
        if res.status_code != 200 or not res.json():
            raise HTTPException(status_code=404, detail="User not found")
        user_id = res.json()[0]["user_id"]
        # Update password (assuming 'password' field exists)
        update_res = await client.patch(
            f"{SUPABASE_URL}/rest/v1/users?user_id=eq.{user_id}",
            headers=headers,
            json={"password": new_password}
        )
        if update_res.status_code >= 300:
            raise HTTPException(status_code=500, detail="Failed to update password.")
    return {"message": "Password reset successful."}

@recovery_router.post("/reset-profile-pin")
async def reset_profile_pin(email: str, profile_name: str, new_pin: str, otp: str):
    # 1. Verify OTP
    purpose = f"profile_pin:{profile_name}"
    if os.path.exists(OTP_STORE_FILE):
        with open(OTP_STORE_FILE, "r") as f:
            data = json.load(f)
    else:
        raise HTTPException(status_code=400, detail="No OTPs found.")
    key = email + ":" + purpose
    entry = data.get(key)
    if not entry:
        raise HTTPException(status_code=400, detail="No OTP found for this purpose.")
    if entry["otp"] != otp:
        raise HTTPException(status_code=400, detail="Invalid OTP.")
    if datetime.utcnow() > datetime.fromisoformat(entry["expires_at"]):
        raise HTTPException(status_code=400, detail="OTP expired.")
    # OTP is valid, delete it
    del data[key]
    with open(OTP_STORE_FILE, "w") as f:
        json.dump(data, f, indent=2)
    # 2. Update profile PIN in Supabase
    async with httpx.AsyncClient() as client:
        # Find user
        user_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/users",
            headers=headers,
            params={"email": f"eq.{email}"}
        )
        if user_res.status_code != 200 or not user_res.json():
            raise HTTPException(status_code=404, detail="User not found")
        user_id = user_res.json()[0]["user_id"]
        # Find profile
        profile_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/profiles",
            headers=headers,
            params={"user_id": f"eq.{user_id}", "name": f"eq.{profile_name}"}
        )
        if profile_res.status_code != 200 or not profile_res.json():
            raise HTTPException(status_code=404, detail="Profile not found for this user")
        profile_id = profile_res.json()[0]["profile_id"]
        # Update PIN
        update_res = await client.patch(
            f"{SUPABASE_URL}/rest/v1/profiles?profile_id=eq.{profile_id}",
            headers=headers,
            json={"pin": new_pin}
        )
        if update_res.status_code >= 300:
            raise HTTPException(status_code=500, detail="Failed to update profile PIN.")
    return {"message": f"PIN reset successful for profile '{profile_name}'."} 