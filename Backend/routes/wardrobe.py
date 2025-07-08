from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Path, Body
from typing import List
from auth import verify_token
import os, aiofiles, httpx, json, re
from uuid import uuid4
from dotenv import load_dotenv
from io import BytesIO
from rembg import remove
import google.generativeai as genai
import pillow_heif
pillow_heif.register_heif_opener()
from PIL import Image

load_dotenv()

wardrobe_router = APIRouter()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_WARDROBE_BUCKET", "wardrobe-images")

headers = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json"
}

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

@wardrobe_router.post("/upload_clothes")
async def upload_multiple_clothes(
    images: List[UploadFile] = File(...),
    user: dict = Depends(verify_token)
):
    profile_id = user.get("profile_id")
    user_email = user["sub"]

    if not profile_id:
        raise HTTPException(status_code=400, detail="No profile selected.")

    if len(images) > 20:
        raise HTTPException(status_code=400, detail="Max 20 images allowed at once.")

    async with httpx.AsyncClient() as client:
        user_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/users",
            headers=headers,
            params={"email": f"eq.{user_email}"}
        )

        if user_res.status_code != 200 or not user_res.json():
            raise HTTPException(status_code=404, detail="User not found")

        user_id = user_res.json()[0]["user_id"]
        uploaded_items = []

        for image in images:
            if image.content_type not in ["image/jpeg", "image/jpg", "image/png", "image/webp", "image/avif"]:
                raise HTTPException(status_code=400, detail=f"Unsupported format: {image.filename}")

            unique_name = f"{profile_id}/{uuid4()}.png"

            try:
                image_bytes = await image.read()
                image_stream = BytesIO(image_bytes)
                with Image.open(image_stream) as img:
                    img = img.convert("RGBA")
                    buffer = BytesIO()
                    img.save(buffer, format="PNG")
                    buffer.seek(0)
                    png_bytes = buffer.read()

                bg_removed_bytes = remove(png_bytes)

                local_path = f"temp_{uuid4()}.png"
                async with aiofiles.open(local_path, 'wb') as f:
                    await f.write(bg_removed_bytes)

                try:
                    features = await analyze_cloth_features(local_path)
                finally:
                    try:
                        os.remove(local_path)
                    except Exception as e:
                        print("[WARNING] Temp file deletion failed:", str(e))

                storage_res = await client.post(
                    f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_STORAGE_BUCKET}/{unique_name}",
                    headers={
                        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                        "Content-Type": "image/png"
                    },
                    content=bg_removed_bytes
                )

                if storage_res.status_code >= 300:
                    raise HTTPException(status_code=500, detail="Upload to storage failed.")

                image_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_STORAGE_BUCKET}/{unique_name}"

                record = {
                    "user_id": user_id,
                    "profile_id": profile_id,
                    "image_url": image_url,
                    **features
                }

                db_res = await client.post(
                    f"{SUPABASE_URL}/rest/v1/wardrobe_clothes",
                    headers=headers,
                    json=record
                )

                if db_res.status_code >= 300:
                    raise HTTPException(status_code=500, detail="Failed to insert cloth record.")

                uploaded_items.append({
                    "image_url": image_url,
                    "features": features
                })

            except Exception as e:
                import traceback
                print("[ERROR] Failed to process image:", image.filename)
                traceback.print_exc()
                raise HTTPException(status_code=500, detail=f"Failed to process {image.filename}")


    return {
        "message": f"{len(uploaded_items)} wardrobe items uploaded and analyzed.",
        "items": uploaded_items
    }


async def analyze_cloth_features(image_path: str):
    try:
        with Image.open(image_path) as img:
            model = genai.GenerativeModel("gemini-1.5-flash")

            prompt = (
                "You are an expert clothing tagger. Given an image of a single clothing item, "
                "return a JSON object with these fields only — no extra text, no markdown:\n"
                "{\n"
                '  "pattern": "...",\n'
                '  "texture": "...",\n'
                '  "color": "...",\n'
                '  "category": "...",\n'
                '  "subcategory": "..."\n'
                "}"
            )

            res = model.generate_content([prompt, img])
            raw = res.text.strip()

            if raw.startswith("```"):
                raw = re.sub(r"^```[a-zA-Z]*\n", "", raw)
                raw = re.sub(r"\n```$", "", raw)

            return json.loads(raw)

    except Exception as e:
        print("[ERROR] Gemini feature extraction failed:", str(e))
        raise Exception(f"Gemini failed: {str(e)}")


@wardrobe_router.put("/edit_clothing/{cloth_id}")
async def edit_clothing_metadata(
    cloth_id: str = Path(..., description="UUID of the clothing item"),
    updates: dict = Body(...),
    user: dict = Depends(verify_token)
):
    profile_id = user.get("profile_id")
    if not profile_id:
        raise HTTPException(status_code=400, detail="No profile selected.")

    async with httpx.AsyncClient() as client:
        check_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/wardrobe_clothes",
            headers=headers,
            params={"cloth_id": f"eq.{cloth_id}", "select": "profile_id"}
        )

        if check_res.status_code != 200 or not check_res.json():
            raise HTTPException(status_code=404, detail="Clothing item not found.")

        item = check_res.json()[0]
        if item["profile_id"] != profile_id:
            raise HTTPException(status_code=403, detail="This item doesn't belong to the current profile.")

        update_res = await client.patch(
            f"{SUPABASE_URL}/rest/v1/wardrobe_clothes?cloth_id=eq.{cloth_id}",
            headers=headers,
            json=updates
        )

        if update_res.status_code >= 300:
            raise HTTPException(status_code=500, detail="Failed to update clothing metadata.")

        return {
            "message": "Clothing metadata updated successfully.",
            "cloth_id": cloth_id,
            "updated_fields": updates
        }


@wardrobe_router.delete("/delete_clothing/{cloth_id}")
async def delete_clothing_item(
    cloth_id: str = Path(..., description="UUID of the clothing item to delete"),
    user: dict = Depends(verify_token)
):
    profile_id = user.get("profile_id")
    if not profile_id:
        raise HTTPException(status_code=400, detail="No profile selected.")

    async with httpx.AsyncClient() as client:
        check_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/wardrobe_clothes",
            headers=headers,
            params={"cloth_id": f"eq.{cloth_id}", "select": "profile_id"}
        )

        if check_res.status_code != 200 or not check_res.json():
            raise HTTPException(status_code=404, detail="Clothing item not found.")

        item = check_res.json()[0]
        if item["profile_id"] != profile_id:
            raise HTTPException(status_code=403, detail="You do not have permission to delete this item.")

        delete_res = await client.delete(
            f"{SUPABASE_URL}/rest/v1/wardrobe_clothes?cloth_id=eq.{cloth_id}",
            headers=headers
        )

        if delete_res.status_code >= 300:
            raise HTTPException(status_code=500, detail="Failed to delete clothing item.")

        return {
            "message": "Clothing item deleted successfully.",
            "cloth_id": cloth_id
        }


@wardrobe_router.get("/get_wardrobe")
async def get_wardrobe(user: dict = Depends(verify_token)):
    profile_id = user.get("profile_id")
    if not profile_id:
        raise HTTPException(status_code=400, detail="No profile selected.")

    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{SUPABASE_URL}/rest/v1/wardrobe_clothes",
            headers=headers,
            params={"profile_id": f"eq.{profile_id}"}
        )
        if res.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to fetch wardrobe items.")
        return {"items": res.json()}


@wardrobe_router.get("/get_wardrobe_item/{cloth_id}")
async def get_wardrobe_item(cloth_id: str, user: dict = Depends(verify_token)):
    profile_id = user.get("profile_id")
    if not profile_id:
        raise HTTPException(status_code=400, detail="No profile selected.")

    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{SUPABASE_URL}/rest/v1/wardrobe_clothes",
            headers=headers,
            params={"cloth_id": f"eq.{cloth_id}", "select": "*"}
        )

        if res.status_code != 200 or not res.json():
            raise HTTPException(status_code=404, detail="Clothing item not found.")

        item = res.json()[0]
        if item["profile_id"] != profile_id:
            raise HTTPException(status_code=403, detail="Unauthorized access.")

        return {"item": item}
