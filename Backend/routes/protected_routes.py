# routes/protected_routes.py
from fastapi import APIRouter, Depends
from auth import verify_token

protected_router = APIRouter()

@protected_router.get("/current-user")
async def get_current_user(user: dict = Depends(verify_token)):
    return {"email": user["sub"]}
