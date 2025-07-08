# code to add user face markers

import os
import cv2
import numpy as np
from insightface.app import FaceAnalysis

# Settings
FACEBANK_DIR = r"D:\Workspace\MirrorR\backend\Face Register\facebank"
OUTPUT_FILE = r"D:\Workspace\MirrorR\backend\facebank.npy"
MIN_DET_SCORE = 0.7

def initialize_model():
    app = FaceAnalysis(name="buffalo_l")
    app.prepare(ctx_id=-1)  # -1 = CPU, 0 = GPU
    return app

def extract_embedding(app, image_path):
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Cannot read image: {image_path}")
    
    faces = app.get(img)
    if not faces:
        raise ValueError("No face detected")

    best_face = max(faces, key=lambda f: f.det_score)
    if best_face.det_score < MIN_DET_SCORE:
        raise ValueError(f"Low quality face: score={best_face.det_score:.2f}")

    return best_face.embedding

def build_facebank(app, base_dir):
    facebank = {}

    for person_name in os.listdir(base_dir):
        person_path = os.path.join(base_dir, person_name)
        if not os.path.isdir(person_path):
            continue

        embeddings = []
        for file in os.listdir(person_path):
            if file.lower().endswith((".jpg", ".jpeg", ".png")):
                img_path = os.path.join(person_path, file)
                try:
                    emb = extract_embedding(app, img_path)
                    embeddings.append(emb)
                    print(f"✅ Processed {file} for {person_name}")
                except Exception as e:
                    print(f"⚠️ {file} skipped ({e})")

        if embeddings:
            avg_embedding = np.mean(embeddings, axis=0)
            facebank[person_name] = avg_embedding
            print(f"✅ {person_name} added with {len(embeddings)} embeddings")
        else:
            print(f"❌ No valid faces for {person_name}")

    return facebank

def main():
    print("🔍 Initializing model...")
    app = initialize_model()

    print("📦 Building facebank...")
    facebank = build_facebank(app, FACEBANK_DIR)

    np.save(OUTPUT_FILE, facebank)
    print(f"💾 Saved facebank to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
