import hashlib
from backend.core.agent_skills import AGENTS, validate_skill_document

def test_all_default_agents_have_skills():
    from backend.core.agent_skills import default_skill
    for agent in AGENTS:
        skill=default_skill(agent)
        assert skill.source=="default"
        assert len(skill.sha256)==64
        assert skill.instructions

def test_user_skill_cannot_disable_execution_controls():
    for phrase in ("bypass live approval","disable risk","skip backtest","disable kill switch"):
        try:
            validate_skill_document("execution", "Use this: "+phrase)
        except ValueError:
            pass
        else:
            raise AssertionError("Protected override was accepted")

def test_user_skill_is_hashed():
    skill=validate_skill_document("research","Use timestamped primary sources.")
    assert skill.sha256 == hashlib.sha256(skill.instructions.encode()).hexdigest()
