# ============================================
# VERIBUILD BACKEND API (Python + FastAPI)
# Deploy to Render.com
# ============================================

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase_py import create_client, Client
import os
from datetime import datetime, timedelta
import jwt
from typing import Optional
import uuid

# ============================================
# CONFIGURATION
# ============================================
app = FastAPI(title="VeriBuild API", version="1.0")

# CORS (Allow frontend to call this API)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with your Vercel URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase Connection
SUPABASE_URL = os.getenv("SUPABASE_URL", "YOUR_SUPABASE_URL_HERE")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "YOUR_SUPABASE_ANON_KEY_HERE")
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-this")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============================================
# DATA MODELS (Pydantic)
# ============================================

class UserRegister(BaseModel):
    email: str
    password: str
    full_name: str
    role: str = "architect"
    phone: Optional[str] = None
    company_name: Optional[str] = None

class UserLogin(BaseModel):
    email: str
    password: str

class SubmissionCreate(BaseModel):
    project_name: str
    project_address: str
    city: str
    land_size: float
    usage_type: str
    declared_scale: str
    file_url: str

class SubmissionUpdate(BaseModel):
    status: Optional[str] = None
    file_url: Optional[str] = None

class CommentCreate(BaseModel):
    review_id: str
    comment_text: str
    x_coord: Optional[float] = None
    y_coord: Optional[float] = None
    page_number: Optional[int] = None

# ============================================
# AUTHENTICATION HELPERS
# ============================================

def create_jwt_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "role": role,
        "exp": datetime.utcnow() + timedelta(days=7)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def verify_jwt_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_current_user(token: str = Depends(verify_jwt_token)):
    # Fetch user from Supabase
    response = supabase.table("users").select("*").eq("id", token["user_id"]).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="User not found")
    return response.data[0]

# ============================================
# API ENDPOINTS
# ============================================

@app.get("/")
def root():
    return {"message": "VeriBuild API is running!", "status": "healthy"}

# ---------- AUTH ----------
@app.post("/api/auth/register")
def register(user: UserRegister):
    # Check if user exists
    existing = supabase.table("users").select("*").eq("email", user.email).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # In production, hash password with bcrypt
    # For MVP, we store plaintext (UPGRADE BEFORE LAUNCH)
    new_user = {
        "id": str(uuid.uuid4()),
        "email": user.email,
        "password_hash": user.password,  # TODO: Hash this!
        "full_name": user.full_name,
        "role": user.role,
        "phone": user.phone,
        "company_name": user.company_name,
        "created_at": datetime.utcnow().isoformat()
    }
    
    response = supabase.table("users").insert(new_user).execute()
    if not response.data:
        raise HTTPException(status_code=400, detail="Registration failed")
    
    token = create_jwt_token(new_user["id"], user.email, user.role)
    return {"token": token, "user": response.data[0]}

@app.post("/api/auth/login")
def login(user: UserLogin):
    # Find user
    response = supabase.table("users").select("*").eq("email", user.email).execute()
    if not response.data:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    db_user = response.data[0]
    # TODO: Verify hashed password
    if db_user["password_hash"] != user.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_jwt_token(db_user["id"], db_user["email"], db_user["role"])
    return {"token": token, "user": db_user}

# ---------- SUBMISSIONS ----------
@app.post("/api/submissions")
def create_submission(submission: SubmissionCreate, current_user=Depends(get_current_user)):
    if current_user["role"] != "architect":
        raise HTTPException(status_code=403, detail="Only architects can submit plans")
    
    new_submission = {
        "id": str(uuid.uuid4()),
        "architect_id": current_user["id"],
        "project_name": submission.project_name,
        "project_address": submission.project_address,
        "city": submission.city,
        "land_size": submission.land_size,
        "usage_type": submission.usage_type,
        "declared_scale": submission.declared_scale,
        "file_url": submission.file_url,
        "status": "submitted",
        "submitted_at": datetime.utcnow().isoformat()
    }
    
    response = supabase.table("submissions").insert(new_submission).execute()
    return {"submission": response.data[0]}

@app.get("/api/submissions")
def get_submissions(current_user=Depends(get_current_user)):
    if current_user["role"] == "architect":
        # Architects see their own submissions
        response = supabase.table("submissions").select("*").eq("architect_id", current_user["id"]).execute()
    elif current_user["role"] == "council_officer":
        # Council sees all submissions
        response = supabase.table("submissions").select("*").execute()
    else:
        response = supabase.table("submissions").select("*").execute()
    
    return {"submissions": response.data}

@app.get("/api/submissions/{submission_id}")
def get_submission(submission_id: str, current_user=Depends(get_current_user)):
    response = supabase.table("submissions").select("*").eq("id", submission_id).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Submission not found")
    return {"submission": response.data[0]}

@app.put("/api/submissions/{submission_id}")
def update_submission(submission_id: str, update: SubmissionUpdate, current_user=Depends(get_current_user)):
    # Check ownership
    sub = supabase.table("submissions").select("*").eq("id", submission_id).execute()
    if not sub.data:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    if current_user["role"] not in ["admin", "council_officer"] and sub.data[0]["architect_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    if update.status == "approved":
        update_data["approved_at"] = datetime.utcnow().isoformat()
    
    response = supabase.table("submissions").update(update_data).eq("id", submission_id).execute()
    return {"submission": response.data[0]}

# ---------- COMMENTS ----------
@app.post("/api/comments")
def create_comment(comment: CommentCreate, current_user=Depends(get_current_user)):
    new_comment = {
        "id": str(uuid.uuid4()),
        "review_id": comment.review_id,
        "comment_text": comment.comment_text,
        "x_coord": comment.x_coord,
        "y_coord": comment.y_coord,
        "page_number": comment.page_number,
        "created_at": datetime.utcnow().isoformat()
    }
    
    response = supabase.table("review_comments").insert(new_comment).execute()
    return {"comment": response.data[0]}

@app.get("/api/comments/{review_id}")
def get_comments(review_id: str):
    response = supabase.table("review_comments").select("*").eq("review_id", review_id).execute()
    return {"comments": response.data}

# ---------- LEADERBOARD (Public) ----------
@app.get("/api/leaderboard")
def get_leaderboard():
    response = supabase.table("leaderboard_cache").select("*").order("approved_count", desc=True).limit(50).execute()
    return {"leaderboard": response.data}

# ---------- HEALTH CHECK ----------
@app.get("/api/health")
def health_check():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
