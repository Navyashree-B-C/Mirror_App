from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from typing import List, Dict
from auth import verify_token
from supabase import create_client
import os
import aiofiles
import uuid
from dotenv import load_dotenv
import httpx
import numpy as np
import cv2
from insightface.app import FaceAnalysis

# === Load Environment ===
load_dotenv()

# === Supabase Config ===
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
BUCKET_NAME = "profile-faces"

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

headers = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json"
}

vector_from_images_router = APIRouter()

MIN_DET_SCORE = 0.7

def initialize_model():
    app = FaceAnalysis(name="buffalo_l")
    app.prepare(ctx_id=-1)  # -1 = CPU, 0 = GPU
    return app

def extract_embedding(app, image_bytes):
    # Convert bytes to numpy array
    np_arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Cannot decode image bytes")
    faces = app.get(img)
    if not faces:
        raise ValueError("No face detected")
    best_face = max(faces, key=lambda f: f.det_score)
    if best_face.det_score < MIN_DET_SCORE:
        raise ValueError(f"Low quality face: score={best_face.det_score:.2f}")
    return best_face.embedding

@vector_from_images_router.post("/generate_and_upload_vector")
async def generate_and_upload_vector(
    images: List[UploadFile] = File(...),
    user: Dict = Depends(verify_token)
):
    try:
        user_id = user["user_id"]
        profile_id = user["profile_id"]

        # Validate profile belongs to user
        async with httpx.AsyncClient() as client:
            profile_check = await client.get(
                f"{SUPABASE_URL}/rest/v1/profiles",
                headers=headers,
                params={
                    "profile_id": f"eq.{profile_id}",
                    "user_id": f"eq.{user_id}"
                }
            )
            if profile_check.status_code != 200 or not profile_check.json():
                raise HTTPException(status_code=403, detail="Profile does not belong to the user.")

        # Initialize face model
        app = initialize_model()
        embeddings = []
        for image in images:
            if image.content_type not in ["image/jpeg", "image/jpg", "image/png"]:
                continue  # skip unsupported
            image_bytes = await image.read()
            try:
                emb = extract_embedding(app, image_bytes)
                embeddings.append(emb)
            except Exception as e:
                # Optionally log or collect errors
                continue
        if not embeddings:
            raise HTTPException(status_code=400, detail="No valid face embeddings found in images.")
        avg_embedding = np.mean(embeddings, axis=0)

        # Save .npy file temporarily
        temp_dir = "temp_vectors"
        os.makedirs(temp_dir, exist_ok=True)
        temp_filename = f"{uuid.uuid4()}.npy"
        temp_path = os.path.join(temp_dir, temp_filename)
        np.save(temp_path, avg_embedding)

        # Upload to Supabase Storage
        supabase_path = f"user_{user_id}/profile_{profile_id}/facial_vector.npy"
        with open(temp_path, "rb") as file_data:
            upload_result = supabase.storage.from_(BUCKET_NAME).upload(
                path=supabase_path,
                file=file_data,
                file_options={"content-type": "application/octet-stream"},
            )
        os.remove(temp_path)

        # Generate signed URL (1 hour)
        signed_url = supabase.storage.from_(BUCKET_NAME).create_signed_url(
            path=supabase_path,
            expires_in=3600
        )

        # Update Supabase profile row
        async with httpx.AsyncClient() as client:
            update_res = await client.patch(
                f"{SUPABASE_URL}/rest/v1/profiles?profile_id=eq.{profile_id}",
                headers=headers,
                json={"facial_vector_path": supabase_path}
            )
            if update_res.status_code >= 300:
                raise HTTPException(status_code=500, detail="Failed to update profile with .npy path")

        return {
            "message": "Facial vector generated and uploaded successfully",
            "storage_path": supabase_path,
            "signed_url": signed_url
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vector generation/upload failed: {e}") 