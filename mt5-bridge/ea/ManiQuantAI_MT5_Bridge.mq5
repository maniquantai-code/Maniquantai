//+------------------------------------------------------------------+
//| ManiQuantAI MT5 Bridge                                           |
//| Runs inside the user's MetaTrader 5 terminal.                   |
//|                                                                  |
//| The EA polls the ManiQuantAI HTTPS bridge API for server-approved |
//| jobs and executes only execution jobs returned for its token.   |
//+------------------------------------------------------------------+
#property strict
#property version   "1.0.0"
#property description "ManiQuantAI MT5 Bridge"
#property description "Connects a user's MT5 terminal to ManiQuantAI over HTTPS."

input string ManiQuantAPI = "https://api.maniquantai.com";
input string BridgeToken  = "";
input int    PollSeconds  = 2;
input int    Deviation    = 20;
input long   MagicNumber  = 260821;

string g_api;
datetime g_last_poll = 0;

string JsonString(const string json,const string key,const string fallback="")
{
   string needle="\""+key+"\"";
   int p=StringFind(json,needle);
   if(p<0) return fallback;
   p=StringFind(json,":",p+StringLen(needle));
   if(p<0) return fallback;
   p++;
   while(p<StringLen(json) && (StringGetCharacter(json,p)==' ' || StringGetCharacter(json,p)=='\t')) p++;
   if(p>=StringLen(json) || StringGetCharacter(json,p)!='\"') return fallback;
   p++;
   int e=p;
   while(e<StringLen(json))
   {
      if(StringGetCharacter(json,e)=='\"' && (e==p || StringGetCharacter(json,e-1)!='\\')) break;
      e++;
   }
   if(e>=StringLen(json)) return fallback;
   return StringSubstr(json,p,e-p);
}

double JsonNumber(const string json,const string key,const double fallback=0.0)
{
   string needle="\""+key+"\"";
   int p=StringFind(json,needle);
   if(p<0) return fallback;
   p=StringFind(json,":",p+StringLen(needle));
   if(p<0) return fallback;
   p++;
   while(p<StringLen(json) && (StringGetCharacter(json,p)==' ' || StringGetCharacter(json,p)=='\t')) p++;
   int e=p;
   while(e<StringLen(json))
   {
      ushort c=StringGetCharacter(json,e);
      if((c>='0' && c<='9') || c=='-' || c=='+' || c=='.' || c=='e' || c=='E') e++; else break;
   }
   if(e==p) return fallback;
   return StringToDouble(StringSubstr(json,p,e-p));
}

bool JsonBool(const string json,const string key,const bool fallback=false)
{
   string needle="\""+key+"\"";
   int p=StringFind(json,needle);
   if(p<0) return fallback;
   p=StringFind(json,":",p+StringLen(needle));
   if(p<0) return fallback;
   string tail=StringSubstr(json,p+1,8);
   StringTrimLeft(tail); StringTrimRight(tail);
   return (StringFind(tail,"true")>=0);
}

string HttpGet(const string path,int &status)
{
   char result[];
   char data[];
   string headers="Accept: application/json\r\nAuthorization: Bearer "+BridgeToken+"\r\n";
   string url=g_api+path;
   ResetLastError();
   status=WebRequest("GET",url,headers,15000,data,result,headers);
   if(status==-1)
   {
      Print("ManiQuantAI WebRequest failed. Add API URL to MT5 Tools > Options > Expert Advisors > Allow WebRequest. Error=",GetLastError());
      return "";
   }
   return CharArrayToString(result);
}

string HttpPost(const string path,const string body,int &status)
{
   char result[];
   char data[];
   StringToCharArray(body,data,0,StringLen(body));
   string headers="Content-Type: application/json\r\nAccept: application/json\r\nAuthorization: Bearer "+BridgeToken+"\r\n";
   ResetLastError();
   status=WebRequest("POST",g_api+path,headers,15000,data,result,headers);
   if(status==-1)
   {
      Print("ManiQuantAI POST failed. Error=",GetLastError());
      return "";
   }
   return CharArrayToString(result);
}

void SendHeartbeat()
{
   MqlTick tick;
   string symbol=_Symbol;
   SymbolInfoTick(symbol,tick);
   string body=StringFormat("{\"symbol\":\"%s\",\"bid\":%.10f,\"ask\":%.10f,\"account_login\":%I64d,\"server\":\"%s\"}",
                           symbol,tick.bid,tick.ask,AccountInfoInteger(ACCOUNT_LOGIN),AccountInfoString(ACCOUNT_SERVER));
   int status=0;
   HttpPost("/api/mt5-bridge/heartbeat",body,status);
}

bool ExecuteJob(const string job)
{
   string id=JsonString(job,"id","");
   string symbol=JsonString(job,"symbol","");
   if(symbol=="") symbol=JsonString(job,"request_symbol","");
   string side=JsonString(job,"side","");
   if(side=="") side=JsonString(job,"request_side","");
   double volume=JsonNumber(job,"volume",0.0);
   if(volume<=0.0) volume=JsonNumber(job,"request_volume",0.0);
   double sl=JsonNumber(job,"stop_loss",0.0);
   double tp=JsonNumber(job,"take_profit",0.0);
   if(symbol=="" || volume<=0.0 || (side!="buy" && side!="sell"))
      return false;

   if(!SymbolSelect(symbol,true))
   {
      Print("ManiQuantAI: symbol unavailable: ",symbol);
      return false;
   }
   MqlTick tick;
   if(!SymbolInfoTick(symbol,tick)) return false;

   MqlTradeRequest req={};
   MqlTradeResult  res={};
   req.action=TRADE_ACTION_DEAL;
   req.symbol=symbol;
   req.volume=volume;
   req.type=(side=="buy" ? ORDER_TYPE_BUY : ORDER_TYPE_SELL);
   req.price=(side=="buy" ? tick.ask : tick.bid);
   req.sl=sl;
   req.tp=tp;
   req.deviation=Deviation;
   req.magic=MagicNumber;
   req.type_time=ORDER_TIME_GTC;
   req.type_filling=ORDER_FILLING_FOK;
   req.comment="ManiQuantAI";

   if(!OrderSend(req,res))
   {
      Print("ManiQuantAI order send failed: ",GetLastError());
      if(id!="") { int st=0; HttpPost("/api/mt5-bridge/execution/"+id+"/fail",StringFormat("{\"job_id\":\"%s\",\"error\":\"OrderSend failed\"}",id),st); }
      return false;
   }

   if(id!="")
   {
      string payload=StringFormat("{\"job_id\":\"%s\",\"result\":{\"retcode\":%u,\"order\":%I64u,\"deal\":%I64u,\"volume\":%.8f,\"price\":%.10f,\"comment\":\"%s\"}}",
                                  id,res.retcode,res.order,res.deal,res.volume,res.price,res.comment);
      int st=0;
      if(res.retcode==TRADE_RETCODE_DONE || res.retcode==TRADE_RETCODE_PLACED)
         HttpPost("/api/mt5-bridge/execution/"+id+"/complete",payload,st);
      else
         HttpPost("/api/mt5-bridge/execution/"+id+"/fail",StringFormat("{\"job_id\":\"%s\",\"error\":\"MT5 retcode %u: %s\"}",id,res.retcode,res.comment),st);
   }
   return true;
}

void PollJobs()
{
   int status=0;
   string json=HttpGet("/api/mt5-bridge/jobs",status);
   if(status<200 || status>=300 || json=="") return;

   // The current bridge API returns {"jobs":[...]}. The EA intentionally
   // handles one job per poll to avoid duplicate execution and excessive load.
   int jobs=StringFind(json,"\"jobs\"");
   if(jobs<0) return;
   int first=StringFind(json,"{",jobs);
   if(first<0) return;
   int depth=0;
   bool in_string=false;
   for(int i=first;i<StringLen(json);i++)
   {
      ushort c=StringGetCharacter(json,i);
      if(c=='\"' && (i==0 || StringGetCharacter(json,i-1)!='\\')) in_string=!in_string;
      if(in_string) continue;
      if(c=='{') depth++;
      if(c=='}')
      {
         depth--;
         if(depth==0)
         {
            string job=StringSubstr(json,first,i-first+1);
            string type=JsonString(job,"job_type","execution");
            if(type=="execution") ExecuteJob(job);
            break;
         }
      }
   }
}

int OnInit()
{
   if(StringLen(BridgeToken)<16)
   {
      Print("ManiQuantAI: enter the personal Bridge Token in EA inputs.");
      return INIT_PARAMETERS_INCORRECT;
   }
   g_api=ManiQuantAPI;
   StringTrimRight(g_api);
   while(StringLen(g_api)>0 && StringSubstr(g_api,StringLen(g_api)-1,1)=="/")
      g_api=StringSubstr(g_api,0,StringLen(g_api)-1);
   EventSetTimer(MathMax(1,PollSeconds));
   Print("ManiQuantAI MT5 Bridge initialized. API=",g_api);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   SendHeartbeat();
   PollJobs();
}
