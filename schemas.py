"""
Database Schemas for SafeShe

Each Pydantic model represents a collection in MongoDB. The collection name is the lowercase of the class name.
Example: class User(BaseModel) -> collection "user"
"""
from pydantic import BaseModel, Field, EmailStr, HttpUrl
from typing import Optional, List
from datetime import datetime

# User accounts (OAuth-backed)
class User(BaseModel):
    name: Optional[str] = Field(None, description="Full name")
    email: Optional[EmailStr] = Field(None, description="Email address")
    provider: Optional[str] = Field(None, description="OAuth provider (google/microsoft/apple/mock)")
    provider_id: Optional[str] = Field(None, description="Provider user id")
    photo_url: Optional[HttpUrl] = Field(None, description="Avatar URL")
    is_active: bool = Field(default=True)

# Trusted guardians for a user
class Guardian(BaseModel):
    user_id: str = Field(..., description="Owner user id")
    name: str = Field(..., description="Guardian name")
    phone: Optional[str] = Field(None, description="Phone number")
    email: Optional[EmailStr] = Field(None, description="Email address")
    relationship: Optional[str] = Field(None, description="Relationship to user")

# Live location points for background tracking
class Trackpoint(BaseModel):
    user_id: str = Field(..., description="Tracked user id")
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    accuracy: Optional[float] = Field(None, ge=0)
    speed: Optional[float] = Field(None, ge=0, description="m/s")
    heading: Optional[float] = Field(None, ge=0, le=360)
    battery: Optional[float] = Field(None, ge=0, le=100)
    ts: Optional[datetime] = Field(None, description="Client timestamp (optional)")

# Incident reports
class Incident(BaseModel):
    user_id: str = Field(..., description="Reporter user id")
    type: str = Field(..., description="Type: sos, harassment, stalking, accident, other")
    description: Optional[str] = None
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lng: Optional[float] = Field(None, ge=-180, le=180)
    media_urls: List[HttpUrl] = Field(default_factory=list)
    severity: Optional[int] = Field(None, ge=1, le=5)

# Area safety alerts (public data or user-sourced)
class Areaalert(BaseModel):
    title: str
    message: str
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    radius_m: int = Field(..., ge=50, le=20000)
    level: str = Field(..., description="info|caution|danger")
