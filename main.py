# ============================================
# VERIBUILD BACKEND API (Using Supabase REST API)
# Deploy to Render.com
# ============================================

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import os
from datetime import datetime, timedelta
import jwt
from typing import Optional
import uuid
import json

# ============================================
# CONFIGURATION
# ============================================
app = FastAPI(title="VeriBuild API", version="1.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-this")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("WARNING: SUPABASE_URL or SUPABASE_KEY not set!")

# Supabase REST API Headers
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

# ============================================
# DATA MODELS
# ============================================

class UserRegister(BaseModel):
    email: str
    password: str
    full_name: str
    role: str = "architect"
    phone: Optional[str] = None
    company_name: Optional[str] = None
    city: Optional[str] = None  # NEW
    registration_number: Optional[str] = None  # NEW

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
    url = f"{SUPABASE_URL}/rest/v1/users?id=eq.{token['user_id']}&select=*"
    response = requests.get(url, headers=SUPABASE_HEADERS)
    if response.status_code != 200 or not response.json():
        raise HTTPException(status_code=404, detail="User not found")
    return response.json()[0]

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
    url = f"{SUPABASE_URL}/rest/v1/users?email=eq.{user.email}&select=*"
    response = requests.get(url, headers=SUPABASE_HEADERS)
    if response.json():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create user
    new_user = {
    "id": str(uuid.uuid4()),
    "email": user.email,
    "password_hash": user.password,
    "full_name": user.full_name,
    "role": user.role,
    "phone": user.phone,
    "company_name": user.company_name,
    "city": user.city,  # NEW
    "registration_number": user.registration_number,  # NEW
    "created_at": datetime.utcnow().isoformat()
    }
    
    url = f"{SUPABASE_URL}/rest/v1/users"
    response = requests.post(url, headers=SUPABASE_HEADERS, json=new_user)
    if response.status_code != 201:
        raise HTTPException(status_code=400, detail="Registration failed")
    
    token = create_jwt_token(new_user["id"], user.email, user.role)
    return {"token": token, "user": new_user}

@app.post("/api/auth/login")
def login(user: UserLogin):
    url = f"{SUPABASE_URL}/rest/v1/users?email=eq.{user.email}&select=*"
    response = requests.get(url, headers=SUPABASE_HEADERS)
    if not response.json():
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    db_user = response.json()[0]
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
    
    url = f"{SUPABASE_URL}/rest/v1/submissions"
    response = requests.post(url, headers=SUPABASE_HEADERS, json=new_submission)
    if response.status_code != 201:
        raise HTTPException(status_code=400, detail="Submission failed")
    
    return {"submission": new_submission}

@app.get("/api/submissions")
def get_submissions(current_user=Depends(get_current_user)):
    if current_user["role"] == "architect":
        url = f"{SUPABASE_URL}/rest/v1/submissions?architect_id=eq.{current_user['id']}&select=*"
    else:
        url = f"{SUPABASE_URL}/rest/v1/submissions?select=*"
    
    response = requests.get(url, headers=SUPABASE_HEADERS)
    return {"submissions": response.json()}

@app.get("/api/submissions/{submission_id}")
def get_submission(submission_id: str):
    url = f"{SUPABASE_URL}/rest/v1/submissions?id=eq.{submission_id}&select=*"
    response = requests.get(url, headers=SUPABASE_HEADERS)
    if not response.json():
        raise HTTPException(status_code=404, detail="Submission not found")
    return {"submission": response.json()[0]}

@app.put("/api/submissions/{submission_id}")
def update_submission(submission_id: str, update: SubmissionUpdate, current_user=Depends(get_current_user)):
    # Check ownership
    url = f"{SUPABASE_URL}/rest/v1/submissions?id=eq.{submission_id}&select=*"
    check = requests.get(url, headers=SUPABASE_HEADERS)
    if not check.json():
        raise HTTPException(status_code=404, detail="Submission not found")
    
    sub = check.json()[0]
    if current_user["role"] not in ["admin", "council_officer"] and sub["architect_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    if update.status == "approved":
        update_data["approved_at"] = datetime.utcnow().isoformat()
    
    url = f"{SUPABASE_URL}/rest/v1/submissions?id=eq.{submission_id}"
    response = requests.patch(url, headers=SUPABASE_HEADERS, json=update_data)
    return {"submission": update_data}

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
    
    url = f"{SUPABASE_URL}/rest/v1/review_comments"
    response = requests.post(url, headers=SUPABASE_HEADERS, json=new_comment)
    if response.status_code != 201:
        raise HTTPException(status_code=400, detail="Failed to add comment")
    return {"comment": new_comment}

@app.get("/api/comments/{review_id}")
def get_comments(review_id: str):
    url = f"{SUPABASE_URL}/rest/v1/review_comments?review_id=eq.{review_id}&select=*"
    response = requests.get(url, headers=SUPABASE_HEADERS)
    return {"comments": response.json()}

# ---------- LEADERBOARD ----------
@app.get("/api/leaderboard")
def get_leaderboard():
    # Get all approved submissions grouped by architect
    url = f"{SUPABASE_URL}/rest/v1/submissions?status=eq.approved&select=architect_id"
    response = requests.get(url, headers=SUPABASE_HEADERS)
    submissions = response.json()
    
    # Count approvals per architect
    counts = {}
    for sub in submissions:
        architect_id = sub["architect_id"]
        counts[architect_id] = counts.get(architect_id, 0) + 1
    
    # Get architect names
    leaderboard = []
    for architect_id, count in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:50]:
        url = f"{SUPABASE_URL}/rest/v1/users?id=eq.{architect_id}&select=full_name,company_name"
        user_resp = requests.get(url, headers=SUPABASE_HEADERS)
        if user_resp.json():
            user = user_resp.json()[0]
            leaderboard.append({
                "architect_name": user["full_name"],
                "company": user.get("company_name", ""),
                "approved_count": count
            })
    
    return {"leaderboard": leaderboard}

# ---------- HEALTH CHECK ----------
@app.get("/api/health")
def health_check():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
