# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.auth_routes import router as auth_router
from routes.protected_routes import protected_router
from routes.profiles_route import profiles_router
from routes.profile_creation import profile_creation_router
from routes.wardrobe import wardrobe_router
from routes.profile_picture import profile_picture_router
from routes.generate_vector_from_images import vector_from_images_router
from routes.recovery_routes import recovery_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(protected_router)
app.include_router(profiles_router)
app.include_router(profile_creation_router)
app.include_router(wardrobe_router)
app.include_router(profile_picture_router)
app.include_router(vector_from_images_router)
app.include_router(recovery_router)

@app.get("/")
async def root():
    return {"message": "Server is up and running!"}
