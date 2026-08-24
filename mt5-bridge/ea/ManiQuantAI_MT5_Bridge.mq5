//+------------------------------------------------------------------+
//| ManiQuantAI MT5 Bridge                                           |
//| Connects a user's MetaTrader 5 terminal to ManiQuantAI.          |
//+------------------------------------------------------------------+
#property strict
#property version "1.0.2"
#property description "ManiQuantAI MT5 Bridge"

input string ManiQuantAPI = "https://maniquantai.vercel.app";
input string BridgeToken  = "";
input int    PollSeconds  = 2;
input int    Deviation    = 20;
input long   MagicNumber  = 260821;

string g_api;

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

string HttpGet(const string path,int &status)
{
   char result[];
   char data[];
   string headers="Accept: application/json\r\nAuthorization: Bearer "+BridgeToken+"\r\n";
   ResetLastError();
   status=WebRequest("GET",g_api+path,headers,15000,data,result,headers);
   if(status==-1)
   {
      Print("ManiQuantAI WebRequest failed. Add https://maniquantai.vercel.app to MT5 WebRequest allow-list. Error=",GetLastError());
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
      Print("ManiQuantAI POST failed. Add https://maniquantai.vercel.app to MT5 WebRequest allow-list. Error=",GetLastError());
      return "";
   }
   return CharArrayToString(result);
}

void SendHeartbeat()
{
   MqlTick tick;
   SymbolInfoTick(_Symbol,tick);
   string body=StringFormat("{\"symbol\":\"%s\",\"bid\":%.10f,\"ask\":%.10f,\"account_login\":%I64d,\"server\":\"%s\"}",_Symbol,tick.bid,tick.ask,AccountInfoInteger(ACCOUNT_LOGIN),AccountInfoString(ACCOUNT_SERVER));
   int status=0;
   string response=HttpPost("/api/mt5-bridge/heartbeat",body,status);
   if(status<200 || status>=300)
      Print("ManiQuantAI heartbeat rejected. HTTP=",status," Response=",response);
}

void CompleteJob(const string id,const bool ok,const string message,const MqlTradeResult &res)
{
   if(id=="") return;
   int status=0;
   string body;
   if(ok)
      body=StringFormat("{\"token\":\"%s\",\"job_id\":\"%s\",\"result\":{\"retcode\":%u,\"order\":%I64u,\"deal\":%I64u,\"volume\":%.8f,\"price\":%.10f,\"comment\":\"%s\"}}",BridgeToken,id,res.retcode,res.order,res.deal,res.volume,res.price,res.comment);
   else
      body=StringFormat("{\"token\":\"%s\",\"job_id\":\"%s\",\"error\":\"%s\"}",BridgeToken,id,message);
   string path=(ok ? "/api/mt5-bridge/execution/"+id+"/complete" : "/api/mt5-bridge/execution/"+id+"/fail");
   HttpPost(path,body,status);
}

void ExecuteJob(const string job)
{
   string id=JsonString(job,"id","");
   string symbol=JsonString(job,"symbol","");
   string side=JsonString(job,"side","");
   double volume=JsonNumber(job,"volume",0.0);
   double sl=JsonNumber(job,"stop_loss",0.0);
   double tp=JsonNumber(job,"take_profit",0.0);
   if(symbol=="" || volume<=0.0 || (side!="buy" && side!="sell")) return;
   if(!SymbolSelect(symbol,true)) { Print("ManiQuantAI symbol unavailable: ",symbol); return; }

   MqlTick tick;
   if(!SymbolInfoTick(symbol,tick)) return;
   MqlTradeRequest req={};
   MqlTradeResult res={};
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

   bool sent=OrderSend(req,res);
   if(!sent || (res.retcode!=TRADE_RETCODE_DONE && res.retcode!=TRADE_RETCODE_PLACED))
   {
      Print("ManiQuantAI order failed. retcode=",res.retcode," error=",GetLastError());
      CompleteJob(id,false,StringFormat("MT5 retcode %u: %s",res.retcode,res.comment),res);
      return;
   }
   CompleteJob(id,true,"",res);
}

void PollJobs()
{
   int status=0;
   string json=HttpGet("/api/mt5-bridge/jobs?token="+BridgeToken,status);
   if(status<200 || status>=300 || json=="") return;
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
            ExecuteJob(StringSubstr(json,first,i-first+1));
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
   while(StringLen(g_api)>0 && StringSubstr(g_api,StringLen(g_api)-1,1)=="/") g_api=StringSubstr(g_api,0,StringLen(g_api)-1);
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
