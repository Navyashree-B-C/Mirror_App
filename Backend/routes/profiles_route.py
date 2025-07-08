from fastapi import APIRouter, Depends, HTTPException
from uuid import uuid4
from datetime import datetime
import httpx
import os
from auth import verify_token  # JWT validation function
from pydantic import BaseModel, Field
from models import ProfileCreate
from models import ProfileLogin
from models import ProfileDetails,ProfileEdit,ProfileDelete
from auth import create_access_token
import json
import aiofiles


# === Router initialization ===
profiles_router = APIRouter()

# === Supabase credentials ===
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")      

headers = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json"
}

# === Route to create a profile ===
@profiles_router.post("/create-profile")
async def create_profile(profile: ProfileCreate, user: dict = Depends(verify_token)):
    user_email = user["sub"]

    async with httpx.AsyncClient() as client:
        # 1. Get user_id
        user_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/users",
            headers=headers,
            params={"email": f"eq.{user_email}"}
        )
        if user_res.status_code != 200 or not user_res.json():
            raise HTTPException(status_code=404, detail="User not found")

        user_id = user_res.json()[0]["user_id"]

        # 2. Count current profiles for the user
        count_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/profiles?select=profile_id&user_id=eq.{user_id}",
            headers=headers
        )
        if count_res.status_code != 200:
            raise HTTPException(status_code=500, detail="Could not check profile count")

        profile_count = len(count_res.json())
        if profile_count >= 8:
            raise HTTPException(status_code=403, detail="Maximum 8 profiles allowed per user")

        # 3. Check for duplicate profile name
        check_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/profiles",
            headers=headers,
            params={
                "user_id": f"eq.{user_id}",
                "name": f"eq.{profile.name}"
            }
        )
        if check_res.status_code == 200 and check_res.json():
            raise HTTPException(status_code=409, detail="Profile name already exists")

        # 4. Create the profile
        profile_id = str(uuid4())
        now = datetime.utcnow().isoformat()

        create_res = await client.post(
            f"{SUPABASE_URL}/rest/v1/profiles",
            headers=headers,
            json={
                "profile_id": profile_id,
                "user_id": user_id,
                "name": profile.name,
                "pin": profile.pin,
                "created_at": now
            }
        )
        if create_res.status_code >= 300:
            raise HTTPException(status_code=500, detail="Could not create profile")

        return {
            "message": "Profile created successfully",
            "profile_id": profile_id,
            "name": profile.name
        }


@profiles_router.post("/profile_login")
async def profile_login(data: ProfileLogin, user: dict = Depends(verify_token)):
    user_email = user["sub"]

    async with httpx.AsyncClient() as client:
        # Step 1: Get user_id
        user_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/users",
            headers=headers,
            params={"email": f"eq.{user_email}"}
        )
        if user_res.status_code != 200 or not user_res.json():
            raise HTTPException(status_code=404, detail="User not found")

        user_id = user_res.json()[0]["user_id"]

        # Step 2: Match profile name + PIN + user_id
        profile_res = await client.get(
        f"{SUPABASE_URL}/rest/v1/profiles",
        headers=headers,
        params={
            "user_id": f"eq.{user_id}",
            "name": f"eq.{data.name}",
            "pin": f"eq.{data.pin}"
        }
    )


        if profile_res.status_code != 200 or not profile_res.json():
            raise HTTPException(status_code=401, detail="Invalid name or PIN")

        profile = profile_res.json()[0]

        # Step 3: Generate token with profile_id
        new_token = create_access_token({
            "sub": user_email,
            "user_id": user_id,
            "profile_id": profile["profile_id"]
        })

        # Step 4: Store session locally
        session_entry = {
            "email": user_email,
            "profile_name": profile["name"],
            "profile_id": profile["profile_id"],
            "access_token": new_token,
            "login_time": datetime.utcnow().isoformat() + "Z"
        }

        log_file = "profile_sessions.json"
        if os.path.exists(log_file):
            with open(log_file, "r") as f:
                sessions = json.load(f)
        else:
            sessions = []

        sessions.append(session_entry)

        with open(log_file, "w") as f:
            json.dump(sessions, f, indent=4)

        return {
            "message": "Profile authenticated successfully",
            "profile_id": profile["profile_id"],
            "name": profile["name"],
            "access_token": new_token,
            "token_type": "bearer"
        }
    


@profiles_router.get("/get-current-profile")
async def get_current_profile(user: dict = Depends(verify_token)):
    user_email = user["sub"]
    profile_id = user.get("profile_id")

    if not profile_id:
        raise HTTPException(status_code=400, detail="No profile selected.")

    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{SUPABASE_URL}/rest/v1/profiles",
            headers=headers,
            params={f"profile_id": f"eq.{profile_id}"}
        )

        if res.status_code != 200 or not res.json():
            raise HTTPException(status_code=404, detail="Profile not found")

        return res.json()[0]

@profiles_router.put("/edit-profile-details")
async def edit_profile_details(details: ProfileEdit, user: dict = Depends(verify_token)):
    user_email = user["sub"]
    profile_id = user.get("profile_id")

    if not profile_id:
        raise HTTPException(status_code=400, detail="No profile selected")

    async with httpx.AsyncClient() as client:
        # Get user_id from email
        user_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/users",
            headers=headers,
            params={"email": f"eq.{user_email}"}
        )
        if user_res.status_code != 200 or not user_res.json():
            raise HTTPException(status_code=404, detail="User not found")

        user_id = user_res.json()[0]["user_id"]

        # Verify profile belongs to user
        profile_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/profiles",
            headers=headers,
            params={
                "profile_id": f"eq.{profile_id}",
                "user_id": f"eq.{user_id}"
            }
        )
        if profile_res.status_code != 200 or not profile_res.json():
            raise HTTPException(status_code=403, detail="Access denied to this profile")

        # Update the profile
        update_res = await client.patch(
            f"{SUPABASE_URL}/rest/v1/profiles?profile_id=eq.{profile_id}",
            headers=headers,
            json=details.dict(exclude_unset=True)
        )

        if update_res.status_code >= 300:
            raise HTTPException(status_code=500, detail="Failed to edit profile")

        return {"message": "Profile updated successfully"}
    

@profiles_router.delete("/delete-profile")
async def delete_profile(data: ProfileDelete, user: dict = Depends(verify_token)):
    user_email = user["sub"]

    async with httpx.AsyncClient() as client:
        # 1. Get user_id from email
        user_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/users",
            headers=headers,
            params={"email": f"eq.{user_email}"}
        )
        if user_res.status_code != 200 or not user_res.json():
            raise HTTPException(status_code=404, detail="User not found")
        user_id = user_res.json()[0]["user_id"]

        # 2. Find profile by name + pin + user_id
        profile_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/profiles",
            headers=headers,
            params={
                "user_id": f"eq.{user_id}",
                "name": f"eq.{data.name}",
                "pin": f"eq.{data.pin}"
            }
        )
        if profile_res.status_code != 200 or not profile_res.json():
            raise HTTPException(status_code=404, detail="Profile not found or incorrect PIN")

        profile_id = profile_res.json()[0]["profile_id"]

        # 3. Delete the matched profile
        delete_res = await client.delete(
            f"{SUPABASE_URL}/rest/v1/profiles",
            headers=headers,
            params={"profile_id": f"eq.{profile_id}"}
        )
        if delete_res.status_code >= 300:
            raise HTTPException(status_code=500, detail="Failed to delete profile")

        return {"message": f"Profile '{data.name}' deleted successfully"}


@profiles_router.get("/get-user-profiles")
async def get_user_profiles(user: dict = Depends(verify_token)):
    user_email = user["sub"]

    async with httpx.AsyncClient() as client:
        user_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/users",
            headers=headers,
            params={"email": f"eq.{user_email}"}
        )
        if user_res.status_code != 200 or not user_res.json():
            raise HTTPException(status_code=404, detail="User not found")

        user_id = user_res.json()[0]["user_id"]

        profiles_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/profiles?user_id=eq.{user_id}&select=name",
            headers=headers
        )
        if profiles_res.status_code != 200:
            raise HTTPException(status_code=500, detail="Could not fetch profiles")

        return {"profiles": profiles_res.json()}
