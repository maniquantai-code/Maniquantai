"""Safe agent-skill registry and user skill validation."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

AGENTS=("research","strategy_compiler","backtest","risk","paper_trading","execution","market_intelligence","portfolio","compliance")

@dataclass(frozen=True)
class Skill:
    agent: str
    name: str
    version: str
    instructions: str
    source: str
    sha256: str

SKILLS_DIR=Path(__file__).resolve().parents[2]/"agent-skills"

def _sha(text:str)->str:
    return hashlib.sha256(text.encode()).hexdigest()

def default_skill(agent:str)->Skill:
    if agent not in AGENTS: raise ValueError("Unknown agent")
    p=SKILLS_DIR/f"{agent}.md"
    text=p.read_text(encoding="utf-8")
    return Skill(agent,p.stem,"1.0.0",text,"default",_sha(text))

def validate_skill_document(agent:str,text:str)->Skill:
    if agent not in AGENTS: raise ValueError("Unknown agent")
    if not text or len(text)>30000: raise ValueError("Skill file must be 1-30000 characters")
    if "\x00" in text: raise ValueError("Invalid skill file")
    forbidden=("bypass live approval","disable risk","ignore risk","skip backtest","skip paper trading","disable kill switch","reveal api key","export secret")
    low=text.lower()
    if any(x in low for x in forbidden): raise ValueError("Skill attempts to override a protected execution control")
    return Skill(agent,"user-skill","1.0.0",text,"user",_sha(text))

def skill_manifest()->dict[str,Any]:
    return {"agents":[{"agent":a,"default_skill":default_skill(a).__dict__} for a in AGENTS]}
