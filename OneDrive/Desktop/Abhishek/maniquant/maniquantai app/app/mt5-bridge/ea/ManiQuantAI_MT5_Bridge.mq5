//+------------------------------------------------------------------+
//| ManiQuantAI MT5 Bridge                                           |
//| Automatic market-data + deterministic execution bridge.         |
//+------------------------------------------------------------------+
#property strict
#property version "1.1.0"
#property description "ManiQuantAI MT5 Bridge"

input string ManiQuantAPI = "https://maniquantai.vercel.app";
input string BridgeToken  = "";
input int    PollSeconds  = 2;
input int    Deviation    = 20;
input long   MagicNumber  = 260821;

string g_api;

string JsonString(const string json,const string key,const string fallback="")
{
   string needle="\""+key+"\""; int p=StringFind(json,needle); if(p<0) return fallback;
   p=StringFind(json,":",p+StringLen(needle)); if(p<0) return fallback; p++;
   while(p<StringLen(json) && (StringGetCharacter(json,p)==' ' || StringGetCharacter(json,p)=='\t')) p++;
   if(p>=StringLen(json) || StringGetCharacter(json,p)!='\"') return fallback; p++; int e=p;
   while(e<StringLen(json)){ if(StringGetCharacter(json,e)=='\"' && (e==p || StringGetCharacter(json,e-1)!='\\')) break; e++; }
   if(e>=StringLen(json)) return fallback; return StringSubstr(json,p,e-p);
}

double JsonNumber(const string json,const string key,const double fallback=0.0)
{
   string needle="\""+key+"\""; int p=StringFind(json,needle); if(p<0) return fallback;
   p=StringFind(json,":",p+StringLen(needle)); if(p<0) return fallback; p++;
   while(p<StringLen(json) && (StringGetCharacter(json,p)==' ' || StringGetCharacter(json,p)=='\t')) p++;
   int e=p; while(e<StringLen(json)){ ushort c=StringGetCharacter(json,e); if((c>='0'&&c<='9')||c=='-'||c=='+'||c=='.'||c=='e'||c=='E') e++; else break; }
   if(e==p) return fallback; return StringToDouble(StringSubstr(json,p,e-p));
}

string HttpGet(const string path,int &status)
{
   char result[]; char data[]; string headers="Accept: application/json\r\nAuthorization: Bearer "+BridgeToken+"\r\n"; ResetLastError();
   status=WebRequest("GET",g_api+path,headers,15000,data,result,headers);
   if(status==-1){Print("ManiQuantAI WebRequest failed. Add ",g_api," to MT5 WebRequest allow-list. Error=",GetLastError()); return "";}
   return CharArrayToString(result);
}

string HttpPost(const string path,const string body,int &status)
{
   char result[]; char data[]; StringToCharArray(body,data,0,StringLen(body));
   string headers="Content-Type: application/json\r\nAccept: application/json\r\nAuthorization: Bearer "+BridgeToken+"\r\n"; ResetLastError();
   status=WebRequest("POST",g_api+path,headers,15000,data,result,headers);
   if(status==-1){Print("ManiQuantAI POST failed. Add ",g_api," to MT5 WebRequest allow-list. Error=",GetLastError()); return "";}
   return CharArrayToString(result);
}

void SendHeartbeat()
{
   MqlTick tick; SymbolInfoTick(_Symbol,tick);
   string body=StringFormat("{\"symbol\":\"%s\",\"bid\":%.10f,\"ask\":%.10f,\"account_login\":%I64d,\"server\":\"%s\"}",_Symbol,tick.bid,tick.ask,AccountInfoInteger(ACCOUNT_LOGIN),AccountInfoString(ACCOUNT_SERVER));
   int status=0; string response=HttpPost("/api/mt5-bridge/heartbeat",body,status);
   if(status<200 || status>=300) Print("ManiQuantAI heartbeat rejected. HTTP=",status," Response=",response);
}

void CompleteJob(const string id,const bool ok,const string message,const string result_json="")
{
   if(id=="") return; int status=0; string body;
   if(ok) body=StringFormat("{\"token\":\"%s\",\"job_id\":\"%s\",\"result\":%s}",BridgeToken,id,(result_json==""?"{}":result_json));
   else body=StringFormat("{\"token\":\"%s\",\"job_id\":\"%s\",\"error\":\"%s\"}",BridgeToken,id,message);
   HttpPost(ok?"/api/mt5-bridge/execution/"+id+"/complete":"/api/mt5-bridge/execution/"+id+"/fail",body,status);
}

ENUM_TIMEFRAMES TfFromString(const string tf)
{
   if(tf=="1m") return PERIOD_M1; if(tf=="5m") return PERIOD_M5; if(tf=="15m") return PERIOD_M15; if(tf=="30m") return PERIOD_M30;
   if(tf=="1h") return PERIOD_H1; if(tf=="4h") return PERIOD_H4; if(tf=="1d") return PERIOD_D1; return PERIOD_M15;
}

int VolumeDigits(const double step)
{
   if(step>=1.0) return 0; if(step>=0.1) return 1; if(step>=0.01) return 2; if(step>=0.001) return 3; return 4;
}

double NormalizeVolume(const string symbol,double volume)
{
   double minv=SymbolInfoDouble(symbol,SYMBOL_VOLUME_MIN), maxv=SymbolInfoDouble(symbol,SYMBOL_VOLUME_MAX), step=SymbolInfoDouble(symbol,SYMBOL_VOLUME_STEP);
   if(step<=0) step=minv; volume=MathMax(minv,MathMin(maxv,volume)); volume=MathFloor(volume/step+1e-9)*step; return NormalizeDouble(volume,VolumeDigits(step));
}

bool HasOpenPosition(const string symbol,const int max_positions)
{
   int count=0; for(int i=0;i<PositionsTotal();i++){ulong ticket=PositionGetTicket(i); if(ticket>0 && PositionSelectByTicket(ticket) && PositionGetString(POSITION_SYMBOL)==symbol) count++;}
   return count>=MathMax(1,max_positions);
}

void ExecuteJob(const string job)
{
   string id=JsonString(job,"id",""); string symbol=JsonString(job,"symbol",""); string side=JsonString(job,"side","");
   double volume=JsonNumber(job,"volume",0.0), risk_pct=JsonNumber(job,"risk_percent",0.0), sl=JsonNumber(job,"stop_loss",0.0), tp=JsonNumber(job,"take_profit",0.0);
   int max_positions=(int)JsonNumber(job,"max_positions",1);
   if(symbol=="" || (side!="buy" && side!="sell")) return;
   if(!SymbolSelect(symbol,true)){CompleteJob(id,false,"MT5 symbol unavailable: "+symbol);return;}
   if(HasOpenPosition(symbol,max_positions)){CompleteJob(id,false,"Position limit reached for "+symbol);return;}
   MqlTick tick; if(!SymbolInfoTick(symbol,tick)){CompleteJob(id,false,"No live tick for "+symbol);return;}
   double entry=(side=="buy"?tick.ask:tick.bid);
   if(risk_pct>0 && volume<=0 && sl>0)
   {
      double profit=0.0; ENUM_ORDER_TYPE ot=(side=="buy"?ORDER_TYPE_BUY:ORDER_TYPE_SELL);
      if(!OrderCalcProfit(ot,symbol,1.0,entry,sl,profit)){CompleteJob(id,false,"Could not calculate broker-aware risk size");return;}
      double loss_per_lot=MathAbs(profit), risk_money=AccountInfoDouble(ACCOUNT_EQUITY)*risk_pct/100.0;
      if(loss_per_lot<=0 || risk_money<=0){CompleteJob(id,false,"Invalid risk sizing inputs");return;}
      volume=NormalizeVolume(symbol,risk_money/loss_per_lot);
   }
   if(volume<=0){CompleteJob(id,false,"Execution volume is zero and risk sizing was unavailable");return;}
   int digits=(int)SymbolInfoInteger(symbol,SYMBOL_DIGITS); sl=sl>0?NormalizeDouble(sl,digits):0; tp=tp>0?NormalizeDouble(tp,digits):0;
   MqlTradeRequest req={}; MqlTradeResult res={}; req.action=TRADE_ACTION_DEAL; req.symbol=symbol; req.volume=volume; req.type=(side=="buy"?ORDER_TYPE_BUY:ORDER_TYPE_SELL); req.price=entry; req.sl=sl; req.tp=tp; req.deviation=Deviation; req.magic=MagicNumber; req.type_time=ORDER_TIME_GTC; req.type_filling=ORDER_FILLING_IOC; req.comment="ManiQuantAI";
   bool sent=OrderSend(req,res); if(!sent || (res.retcode!=TRADE_RETCODE_DONE && res.retcode!=TRADE_RETCODE_PLACED)){CompleteJob(id,false,StringFormat("MT5 retcode %u: %s",res.retcode,res.comment));return;}
   string result=StringFormat("{\"retcode\":%u,\"order\":%I64u,\"deal\":%I64u,\"volume\":%.8f,\"price\":%.10f,\"equity\":%.2f,\"comment\":\"%s\"}",res.retcode,res.order,res.deal,res.volume,res.price,AccountInfoDouble(ACCOUNT_EQUITY),res.comment);
   CompleteJob(id,true,"",result);
}

void CompleteMarketData(const string id,const string rates_json)
{
   int status=0; string body=StringFormat("{\"token\":\"%s\",\"job_id\":\"%s\",\"rates\":%s,\"account\":{\"balance\":%.2f,\"equity\":%.2f,\"currency\":\"%s\"}}",BridgeToken,id,rates_json,AccountInfoDouble(ACCOUNT_BALANCE),AccountInfoDouble(ACCOUNT_EQUITY),AccountInfoString(ACCOUNT_CURRENCY));
   HttpPost("/api/mt5-bridge/jobs/"+id+"/complete",body,status);
}

void MarketDataJob(const string job)
{
   string id=JsonString(job,"id",""); string symbol=JsonString(job,"symbol",_Symbol); string tf=JsonString(job,"timeframe","15m"); int count=(int)JsonNumber(job,"count",200); if(count<20) count=20; if(count>5000) count=5000;
   if(!SymbolSelect(symbol,true)){int status=0;string body=StringFormat("{\"token\":\"%s\",\"error\":\"MT5 symbol unavailable: %s\"}",BridgeToken,symbol);HttpPost("/api/mt5-bridge/jobs/"+id+"/fail",body,status);return;}
   MqlRates rates[]; ArraySetAsSeries(rates,false); int n=CopyRates(symbol,TfFromString(tf),0,count,rates); if(n<=0){int status=0;string body=StringFormat("{\"token\":\"%s\",\"error\":\"CopyRates failed for %s\"}",BridgeToken,symbol);HttpPost("/api/mt5-bridge/jobs/"+id+"/fail",body,status);return;}
   string out="["; for(int i=0;i<n;i++){if(i>0)out+=",";out+=StringFormat("{\"ts\":%I64d,\"open\":%.10f,\"high\":%.10f,\"low\":%.10f,\"close\":%.10f,\"volume\":%I64d}",(long)rates[i].time*1000,rates[i].open,rates[i].high,rates[i].low,rates[i].close,(long)rates[i].tick_volume);} out+="]"; CompleteMarketData(id,out);
}

void ProcessJob(const string job)
{
   string type=JsonString(job,"job_type",""); if(type=="execution") ExecuteJob(job); else if(type=="market_data") MarketDataJob(job);
}

void PollJobs()
{
   int status=0; string json=HttpGet("/api/mt5-bridge/jobs?token="+BridgeToken,status); if(status<200||status>=300||json=="")return;
   int jobs=StringFind(json,"\"jobs\""); if(jobs<0)return; int pos=StringFind(json,"{",jobs); if(pos<0)return;
   for(int j=0;j<5;j++){if(pos<0||pos>=StringLen(json))break;int depth=0;bool in_string=false;int end=-1;for(int i=pos;i<StringLen(json);i++){ushort c=StringGetCharacter(json,i);if(c=='\"'&&(i==0||StringGetCharacter(json,i-1)!='\\'))in_string=!in_string;if(in_string)continue;if(c=='{')depth++;if(c=='}'){depth--;if(depth==0){end=i;break;}}}if(end<0)break;ProcessJob(StringSubstr(json,pos,end-pos+1));pos=StringFind(json,"{",end+1);}
}

int OnInit(){if(StringLen(BridgeToken)<16){Print("ManiQuantAI: enter the personal Bridge Token in EA inputs.");return INIT_PARAMETERS_INCORRECT;}g_api=ManiQuantAPI;StringTrimRight(g_api);while(StringLen(g_api)>0&&StringSubstr(g_api,StringLen(g_api)-1,1)=="/")g_api=StringSubstr(g_api,0,StringLen(g_api)-1);EventSetTimer(MathMax(1,PollSeconds));Print("ManiQuantAI MT5 Bridge initialized. API=",g_api);return INIT_SUCCEEDED;}
void OnDeinit(const int reason){EventKillTimer();}
void OnTimer(){SendHeartbeat();PollJobs();}
