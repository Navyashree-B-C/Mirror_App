from fastapi import UploadFile, File, Depends, HTTPException, APIRouter
import os, aiofiles, httpx
from uuid import uuid4
from dotenv import load_dotenv
from supabase import create_client
from auth import verify_token

load_dotenv()

profile_picture_router = APIRouter()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
BUCKET_NAME = "profile-pictures"

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

headers = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json"
}

@profile_picture_router.post("/upload_profile_picture")
async def upload_profile_picture(
    file: UploadFile = File(...),
    user: dict = Depends(verify_token)
):
    profile_id = user.get("profile_id")
    user_email = user.get("sub")

    if not profile_id:
        raise HTTPException(status_code=400, detail="Missing profile_id in token")

    temp_path = f"temp_profile_{uuid4().hex}.jpg"
    try:
        async with aiofiles.open(temp_path, "wb") as f:
            await f.write(await file.read())

        async with httpx.AsyncClient() as client:
            user_res = await client.get(
                f"{SUPABASE_URL}/rest/v1/users",
                headers=headers,
                params={"email": f"eq.{user_email}"}
            )
            if user_res.status_code != 200 or not user_res.json():
                raise HTTPException(status_code=404, detail="User not found")

            user_id = user_res.json()[0]["user_id"]

            with open(temp_path, "rb") as pf:
                supabase_path = f"user_{user_id}/profile_{profile_id}/profile_pic.jpg"
                supabase.storage.from_(BUCKET_NAME).upload(
                    path=supabase_path,
                    file=pf,
                    file_options={"content-type": "image/jpeg"}
                )

            public_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{supabase_path}"

            update_res = await client.patch(
                f"{SUPABASE_URL}/rest/v1/profiles?profile_id=eq.{profile_id}",
                headers=headers,
                json={"profile_picture_url": public_url}
            )
            if update_res.status_code >= 300:
                raise HTTPException(status_code=500, detail="Failed to update profile with picture URL")

        return {
            "message": "Profile picture uploaded successfully.",
            "profile_picture_url": public_url
        }

    finally:
        try:
            os.remove(temp_path)
        except:
            pass
