from fastapi import UploadFile, File, Form, Depends, HTTPException, APIRouter
import os, json, uuid, aiofiles, httpx, logging, re
from PIL import Image
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import google.generativeai as genai
from auth import verify_token
from datetime import datetime
from dotenv import load_dotenv
from uuid import uuid4
from supabase import create_client

load_dotenv()

profile_creation_router = APIRouter()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
BUCKET_NAME = "profile-pictures"

genai.configure(api_key=GEMINI_API_KEY)

headers = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json"
}

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

class ProfileDetails(BaseModel):
    name: str
    pin: str
    age: int
    gender: str
    weight: float
    height: float
    color_preferences: str

@profile_creation_router.post("/create_complete_profile")
async def create_complete_profile(
    name: str = Form(...),
    pin: str = Form(...),
    age: int = Form(...),
    gender: str = Form(...),
    weight: float = Form(...),
    height: float = Form(...),
    color_preferences: str = Form(...),

    half_image: UploadFile = File(...),
    full_image: UploadFile = File(...),
    profile_pic: UploadFile = File(...),

    user: dict = Depends(verify_token)
):
    user_email = user["sub"]
    profile_id = str(uuid4())
    logging.info(f"Received profile creation request for user: {user_email}, new profile_id: {profile_id}")

    # Combine form fields into a dictionary
    details = {
        "name": name,
        "pin": pin,
        "age": age,
        "gender": gender,
        "weight": weight,
        "height": height,
        "color_preferences": color_preferences
    }

    profile_name = details["name"]
    pin = details["pin"]

    ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
    half_ext = os.path.splitext(half_image.filename)[1].lower()
    full_ext = os.path.splitext(full_image.filename)[1].lower()
    profile_pic_ext = os.path.splitext(profile_pic.filename)[1].lower()

    if half_ext not in ALLOWED_EXTENSIONS or full_ext not in ALLOWED_EXTENSIONS or profile_pic_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported image format")

    temp_dir = "temp_images"
    os.makedirs(temp_dir, exist_ok=True)
    half_path = os.path.join(temp_dir, f"half_{uuid.uuid4().hex}{half_ext}")
    full_path = os.path.join(temp_dir, f"full_{uuid.uuid4().hex}{full_ext}")
    profile_pic_path = os.path.join(temp_dir, f"profile_{uuid.uuid4().hex}{profile_pic_ext}")

    try:
        async with aiofiles.open(half_path, "wb") as f:
            await f.write(await half_image.read())
        async with aiofiles.open(full_path, "wb") as f:
            await f.write(await full_image.read())
        async with aiofiles.open(profile_pic_path, "wb") as f:
            await f.write(await profile_pic.read())

        face_features = await extract_face_features_from_half_image(half_path, user_email)
        body_features = await extract_body_features_from_full_image(full_path, user_email)

        merged_details = details.copy()
        merged_details.update(face_features)
        merged_details.update(body_features)

        async with httpx.AsyncClient(timeout=20.0) as client:
            user_res = await client.get(
                f"{SUPABASE_URL}/rest/v1/users",
                headers=headers,
                params={"email": f"eq.{user_email}"}
            )
            if user_res.status_code != 200 or not user_res.json():
                raise HTTPException(status_code=404, detail="User not found")
            user_id = user_res.json()[0]["user_id"]

            count_res = await client.get(
                f"{SUPABASE_URL}/rest/v1/profiles?select=profile_id&user_id=eq.{user_id}",
                headers=headers
            )
            if len(count_res.json()) >= 8:
                raise HTTPException(status_code=403, detail="Maximum 8 profiles allowed")

            name_check = await client.get(
                f"{SUPABASE_URL}/rest/v1/profiles",
                headers=headers,
                params={"user_id": f"eq.{user_id}", "name": f"eq.{profile_name}"}
            )
            if name_check.status_code == 200 and name_check.json():
                raise HTTPException(status_code=409, detail="Profile name already exists")

            with open(profile_pic_path, "rb") as pf:
                supabase_path = f"user_{user_id}/profile_{profile_id}/profile_pic{profile_pic_ext}"
                content_type = f"image/{profile_pic_ext.replace('.', '') if profile_pic_ext != '.jpg' else 'jpeg'}"
                supabase.storage.from_(BUCKET_NAME).upload(
                    path=supabase_path,
                    file=pf,
                    file_options={"content-type": content_type}
                )

            public_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{supabase_path}"
            merged_details.update({"profile_picture_url": public_url})

            now = datetime.utcnow().isoformat()
            create_res = await client.post(
                f"{SUPABASE_URL}/rest/v1/profiles",
                headers=headers,
                json={
                    "profile_id": profile_id,
                    "user_id": user_id,
                    "name": profile_name,
                    "pin": pin,
                    "created_at": now,
                    **merged_details
                }
            )
            if create_res.status_code >= 300:
                raise HTTPException(status_code=500, detail="Could not create profile")

        return {
            "message": "Profile created successfully.",
            "profile_id": profile_id,
            "profile_picture_url": public_url,
            "details": merged_details
        }

    finally:
        for path in [half_path, full_path, profile_pic_path]:
            try:
                os.remove(path)
            except:
                pass

def extract_json_from_response(text: str) -> dict:
    try:
        match = re.search(r"```json(.*?)```", text, re.DOTALL)
        cleaned = match.group(1).strip() if match else re.search(r"\{.*?\}", text, re.DOTALL).group(0)
        return json.loads(cleaned)
    except Exception:
        raise HTTPException(status_code=500, detail=f"Gemini returned invalid JSON. Raw: {text}")


async def extract_face_features_from_half_image(image_path: str, user_email: str):
    try:
        with Image.open(image_path) as img:
            img.load()
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = """
            From this upper-body or face image, return ONLY a valid JSON in this format:
            {
              "skin_tone": "<category>-<hex_code>",
              "face_shape": "<face_shape>",
              "hair_color": "<category>-<hex_code>"
            }
            Where:
            - skin_tone category is one of ["fair", "light", "medium", "olive", "brown", "dark"]
            - face_shape is one of ["oval", "round", "square", "heart", "diamond", "oblong", "triangle"]
            - hair_color category is one of ["black", "brown", "blonde", "red", "grey", "white", "dyed"]
            - hex_code is the closest matching HEX color (e.g., #a36f40)
            Only return the JSON object.
            """
            response = model.generate_content([prompt, img])
            return extract_json_from_response(response.text.strip())
    except Exception:
        raise HTTPException(status_code=500, detail="Face feature extraction failed")


async def extract_body_features_from_full_image(image_path: str, user_email: str):
    try:
        with Image.open(image_path) as img:
            img.load()
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = """
            Analyze this full-body image and return ONLY a valid JSON in the following format:
            {
              "body_shape": One of ["rectangle", "pear", "apple", "hourglass", "inverted_triangle", "diamond", "round"]
            }
            """
            response = model.generate_content([prompt, img])
            return extract_json_from_response(response.text.strip())
    except Exception:
        raise HTTPException(status_code=500, detail="Body feature extraction failed")
