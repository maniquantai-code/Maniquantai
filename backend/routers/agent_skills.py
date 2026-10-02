from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from backend.routers.auth import get_current_user
from backend.core.agent_skills import AGENTS, validate_skill_document
import hashlib, json, os
import httpx

api_router=APIRouter(prefix="/api/agent-skills",tags=["agent-skills"])
SB=os.getenv("SUPABASE_URL","").rstrip("/")
ANON=(os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_PUBLISHABLE_KEY") or "").strip()

def _headers(user):
    token=user.get("access_token") or user.get("token") or ""
    return {"Authorization":"Bearer "+token,"apikey":ANON,"Content-Type":"application/json"}

@api_router.get("")
async def list_skills(user=Depends(get_current_user)):
    uid=user["id"]
    async with httpx.AsyncClient(timeout=10) as c:
        r=await c.get(f"{SB}/rest/v1/agent_skills",headers=_headers(user),params={"user_id":f"eq.{uid}","active":"eq.true","select":"id,agent_name,name,version,sha256,source,active,created_at,updated_at","order":"agent_name.asc,created_at.desc"})
    if not r.is_success: raise HTTPException(502,"Could not load agent skills")
    return {"agents":list(AGENTS),"skills":r.json()}

@api_router.post("/{agent_name}/upload")
async def upload_skill(agent_name:str,file:UploadFile=File(...),user=Depends(get_current_user)):
    if agent_name not in AGENTS: raise HTTPException(400,"Unknown agent")
    if file.content_type not in {"text/plain","text/markdown","application/json","application/octet-stream"}:
        raise HTTPException(415,"Upload a Markdown, text, or JSON skill file")
    data=await file.read()
    if len(data)>30000: raise HTTPException(413,"Skill file exceeds 30 KB")
    try: text=data.decode("utf-8")
    except UnicodeDecodeError: raise HTTPException(400,"Skill file must be UTF-8")
    try: skill=validate_skill_document(agent_name,text)
    except ValueError as e: raise HTTPException(400,str(e))
    uid=user["id"]; payload={"user_id":uid,"agent_name":skill.agent,"name":file.filename or "user-skill","version":skill.version,"content":skill.instructions,"sha256":skill.sha256,"source":"user","active":True}
    async with httpx.AsyncClient(timeout=10) as c:
        r=await c.post(f"{SB}/rest/v1/agent_skills",headers=_headers(user),json=payload)
    if not r.is_success: raise HTTPException(502,"Could not save agent skill")
    return {"ok":True,"agent":skill.agent,"name":payload["name"],"sha256":skill.sha256}

@api_router.delete("/{skill_id}")
async def delete_skill(skill_id:str,user=Depends(get_current_user)):
    uid=user["id"]
    async with httpx.AsyncClient(timeout=10) as c:
        r=await c.patch(f"{SB}/rest/v1/agent_skills",headers=_headers(user),params={"id":f"eq.{skill_id}","user_id":f"eq.{uid}"},json={"active":False})
    if not r.is_success: raise HTTPException(502,"Could not disable agent skill")
    return {"ok":True}
