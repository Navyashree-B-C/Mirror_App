# models.py
from pydantic import BaseModel, EmailStr, Field, model_validator
from typing import Optional

class UserSignup(BaseModel):
    name: str = Field(..., min_length=2)
    email: EmailStr
    password: str = Field(..., min_length=6)
    confirm_password: str

    @model_validator(mode="after")
    def check_passwords(self):
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self

class VerifyOTP(BaseModel):
    email: EmailStr
    otp: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class ProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=20)
    pin: int = Field(..., ge=1000, le=9999, description="4-digit PIN")

class ProfileLogin(BaseModel):
    name: str = Field(..., min_length=1)
    pin: int = Field(..., ge=1000, le=9999)

class ProfileDetails(BaseModel):
    gender: Optional[str]
    age: Optional[int]
    height: Optional[float]
    weight: Optional[float]
    style_preferences: Optional[str]

class ProfileDetailsExtraction(BaseModel):
    skin_tone: Optional[str]
    face_shape: Optional[str]
    hair_color: Optional[str]
    body_shape: Optional[str]
    

class ProfileEdit(BaseModel):
    gender: Optional[str] = None
    age: Optional[int] = None
    height: Optional[float] = None
    weight: Optional[float] = None
    skin_tone: Optional[str] = None
    face_shape: Optional[str] = None
    hair_color: Optional[str] = None
    body_shape: Optional[str] = None
    style_preferences: Optional[str] = None

class ProfileDelete(BaseModel):
    name: str
    pin: int

class WardrobeClothEdit(BaseModel):
    pattern: Optional[str] = None
    texture: Optional[str] = None
    color: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None