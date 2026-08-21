import os,time,logging,requests
from datetime import datetime
import MetaTrader5 as mt5
API=os.environ["MANIQUANT_API_URL"].rstrip("/");TOKEN=os.environ["MT5_BRIDGE_TOKEN"];POLL=float(os.getenv("MT5_BRIDGE_POLL_SECONDS","2"))
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")

def rates(job):
 tf=getattr(mt5,job["timeframe"],mt5.TIMEFRAME_M15);data=mt5.copy_rates_range(job["symbol"].upper(),tf,datetime.fromisoformat(job["date_from"].replace("Z","+00:00")),datetime.fromisoformat(job["date_to"].replace("Z","+00:00")))
 if data is None:raise RuntimeError(f"MT5 rates failed: {mt5.last_error()}")
 return [{"time":int(x["time"]),"open":float(x["open"]),"high":float(x["high"]),"low":float(x["low"]),"close":float(x["close"]),"tick_volume":int(x["tick_volume"])} for x in data]
def account():
 a=mt5.account_info();t=mt5.terminal_info();return {"login":int(a.login) if a else None,"server":a.server if a else None,"terminal_connected":bool(t and t.connected)}
def main():
 while True:
  try:
   if not mt5.initialize():logging.warning("MT5 initialize failed: %s",mt5.last_error());time.sleep(5);continue
   r=requests.get(f"{API}/api/mt5-bridge/jobs",params={"token":TOKEN},timeout=15);r.raise_for_status()
   for job in r.json().get("jobs",[]):
    try:requests.post(f"{API}/api/mt5-bridge/jobs/{job['id']}/complete",json={"token":TOKEN,"job_id":job["id"],"rates":rates(job),"account":account()},timeout=30).raise_for_status()
    except Exception as e:
     try:requests.post(f"{API}/api/mt5-bridge/jobs/{job['id']}/fail",json={"token":TOKEN,"job_id":job["id"],"error":str(e)[:1000]},timeout=15)
     except Exception:pass
   time.sleep(POLL)
  except Exception as e:logging.warning("Bridge: %s",e);time.sleep(5)
if __name__=="__main__":
 try:main()
 finally:mt5.shutdown()
