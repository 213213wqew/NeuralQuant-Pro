//+------------------------------------------------------------------+
//| GridMartingaleMA04StatusPanel.mq5                                |
//| Reads Python-exported state, draws panel and TP lines in MT5.    |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"
#property description "GridMartingaleMA04 MT5 panel / TP lines / close buttons"

#include <Trade/Trade.mqh>

input ulong  InpMagic            = 2025894;
input string InpStatusExportFolder = "GridMartingaleMA04"; // 与 Python bridge 的 strategy_name 一致；利滚利选 CompoundMartin
input string InpStatusSymbol     = "";
input bool   InpShowUI           = true;
input bool   InpDrawInnerTPLines = true;
input color  InpColorCloseAll    = clrRed;
input color  InpColorCloseBuy    = clrOrange;
input color  InpColorCloseSell   = clrBlue;
input color  InpBuyTPLineColor   = clrDodgerBlue;
input color  InpSellTPLineColor  = clrYellow;
input color  InpHedgeModeColor   = clrMagenta;
input int    InpRefreshSeconds   = 1;
input int    InpDisconnectIfUnchangedSeconds = 3; // 状态文件内 updated_at 连续不变达到此秒数 → 显示未连接
input int    InpPanelHeightPct     = 92;  // 展开时面板高度占图表高度百分比（自适应），约 70-92
input int    InpPanelMinHeight     = 320; // 面板最小高度（像素）
input int    InpPanelScrollStep    = 20;  // 每次点击 ▲▼ 滚动的像素
input int    InpPanelBottomReserve = 96; // 自面板底边向上的安全区(与按钮行取较小值)，越大可滚动文字越早裁切、越不易压住底部按钮

CTrade g_trade;
string g_prefix;
bool   g_panelCollapsed=false;
string g_keys[];
string g_vals[];
int    g_pair_count=0;
int    g_panel_scroll=0;
int    g_box_h=400;
int    g_scroll_max=0;
int    g_panel_content_bottom_cached=720;
int    g_clip_top_panel=0;
int    g_clip_bottom_panel=600;
int    g_track_updated_at=-1;       // 最近一次见到的文件内 updated_at
datetime g_track_unchanged_since=0; // 从何时起持续为该 updated_at（本机时间）

string SafeSymbolName(const string symbol)
  {
   string out="";
   for(int i=0;i<StringLen(symbol);i++)
     {
      ushort ch=(ushort)StringGetCharacter(symbol,i);
      bool is_digit=(ch>='0' && ch<='9');
      bool is_upper=(ch>='A' && ch<='Z');
      bool is_lower=(ch>='a' && ch<='z');
      out += (is_digit || is_upper || is_lower) ? StringFormat("%c", ch) : "_";
     }
   return out;
  }

string StatusSymbol()
  {
   string s=InpStatusSymbol;
   StringTrimLeft(s);
   StringTrimRight(s);
   return (s=="" ? _Symbol : s);
  }

string AccountScopeName()
  {
   string server=AccountInfoString(ACCOUNT_SERVER);
   return SafeSymbolName(IntegerToString((int)AccountInfoInteger(ACCOUNT_LOGIN))+"_"+server);
  }

string StatusRelativePath(const bool account_scoped=true)
  {
   // 只返回 MT5 Common Files 下的相对路径。
   // FileOpen(..., FILE_COMMON) 会固定读取 C:\Users\<用户>\AppData\Roaming\MetaQuotes\Terminal\Common\Files。
   string folder=InpStatusExportFolder;
   StringReplace(folder,"\\","_");
   StringReplace(folder,"/","_");
   if(StringLen(folder)<=0)
      folder="GridMartingaleMA04";
   string base="NeuralQuant\\"+folder+"\\";
   if(account_scoped)
      base=base+AccountScopeName()+"\\";
   return base + SafeSymbolName(StatusSymbol()) + "_" + IntegerToString((int)AccountInfoInteger(ACCOUNT_LOGIN)) + ".txt";
  }

void ResetPairs()
  {
   ArrayResize(g_keys,0);
   ArrayResize(g_vals,0);
   g_pair_count=0;
  }

void PutPair(const string key,const string val)
  {
   const int n=g_pair_count+1;
   ArrayResize(g_keys,n);
   ArrayResize(g_vals,n);
   g_keys[g_pair_count]=key;
   g_vals[g_pair_count]=val;
   g_pair_count=n;
  }

string GetValue(const string key,const string fallback="")
  {
   for(int i=0;i<g_pair_count;i++)
      if(g_keys[i]==key)
         return g_vals[i];
   return fallback;
  }

double GetValueDouble(const string key,const double fallback=0.0)
  {
   string v=GetValue(key,"");
   return (v=="" ? fallback : StringToDouble(v));
  }

int GetValueInt(const string key,const int fallback=0)
  {
   string v=GetValue(key,"");
   return (v=="" ? fallback : (int)StringToInteger(v));
  }

bool GetValueBool(const string key,const bool fallback=false)
  {
   string v=GetValue(key, fallback ? "true" : "false");
   StringToLower(v);
   return (v=="true" || v=="1");
  }

bool LoadStatusFile()
  {
   ResetPairs();
   const string path=StatusRelativePath(true);
   ResetLastError();
   int handle=FileOpen(path, FILE_READ|FILE_TXT|FILE_COMMON|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE);
   if(handle==INVALID_HANDLE)
      return false;

   while(!FileIsEnding(handle))
     {
      string line=FileReadString(handle);
      if(line=="")
         continue;
      const int eq=StringFind(line,"=");
      if(eq<=0)
         continue;
      PutPair(StringSubstr(line,0,eq), StringSubstr(line,eq+1));
     }
   FileClose(handle);
   return g_pair_count>0;
  }

void PutDefaultStatus()
  {
   ResetPairs();
   PutPair("strategy","GridMartingaleMA04");
   PutPair("symbol",StatusSymbol());
   PutPair("magic",IntegerToString((int)InpMagic));
   PutPair("enable_trading","false");
   PutPair("trade_mode","normal");
   PutPair("hedge_from","-");
   PutPair("hedge_side","-");
   PutPair("hedge_target","0");
   PutPair("state","ready");
   PutPair("buy_count","0");
   PutPair("sell_count","0");
   PutPair("net_lots","0");
   PutPair("total_lots","0");
   PutPair("session_open_count","0");
   PutPair("buy_avg","0");
   PutPair("sell_avg","0");
   PutPair("buy_pnl","0");
   PutPair("sell_pnl","0");
   PutPair("total_pnl","0");
   PutPair("floating_pnl","0");
   PutPair("drawdown_pct","0");
   PutPair("risk_level","low");
   PutPair("margin_level","0");
   PutPair("buy_tp","0");
   PutPair("sell_tp","0");
   PutPair("freeze_until","0");
   PutPair("ai_regime","unknown");
   PutPair("ai_direction","NEUTRAL");
   PutPair("ai_trend_family","none");
   PutPair("ai_confidence","0");
   PutPair("ai_trend_quality","0");
   PutPair("current_state","unknown");
   PutPair("current_phase","unknown");
   PutPair("current_direction","NEUTRAL");
   PutPair("current_confidence","0");
   PutPair("current_impulse_state","none");
   PutPair("current_impulse_phase","none");
   PutPair("current_impulse_direction","NEUTRAL");
   PutPair("current_impulse_confidence","0");
   PutPair("current_impulse_age","0");
   PutPair("current_impulse_extension_atr","0");
   PutPair("current_impulse_rebound_atr","0");
   PutPair("current_crash_state","none");
   PutPair("current_crash_phase","none");
   PutPair("current_crash_direction","NEUTRAL");
   PutPair("current_crash_confidence","0");
   PutPair("current_crash_age","0");
   PutPair("current_crash_extension_atr","0");
   PutPair("current_crash_rebound_atr","0");
   PutPair("future_impulse_warning","none");
   PutPair("future_impulse_direction","NEUTRAL");
   PutPair("future_impulse_level","none");
   PutPair("future_impulse_expected_minutes","0");
   PutPair("future_impulse_window_min","0");
   PutPair("future_impulse_window_max","0");
   PutPair("future_impulse_confidence","0");
   PutPair("future_impulse_success_rate","0");
   PutPair("future_impulse_false_rate","0");
   PutPair("future_impulse_strong_rate","0");
   PutPair("future_impulse_samples","0");
   PutPair("updated_at",IntegerToString((int)TimeLocal()));
  }

bool LoadEffectiveStatus()
  {
   const bool loaded=LoadStatusFile();
   if(!loaded)
     {
      g_track_updated_at=-1;
      PutDefaultStatus();
      return false;
     }
   const int u=GetValueInt("updated_at",0);
   if(u<=0)
     {
      g_track_updated_at=-1;
      PutDefaultStatus();
      return false;
     }
   const datetime now=TimeLocal();
   if(u!=g_track_updated_at)
     {
      g_track_updated_at=u;
      g_track_unchanged_since=now;
     }
   else
     {
      const int need=MathMax(1,InpDisconnectIfUnchangedSeconds);
      if((int)(now-g_track_unchanged_since)>=need)
        {
         PutDefaultStatus();
         return false;
        }
     }
   return true;
  }

string RiskLabel(const string code)
  {
   if(code=="low")     return "低";
   if(code=="medium")  return "中";
   if(code=="high")    return "高";
   if(code=="extreme") return "极高";
   return code;
  }

string StateLabel(const string code)
  {
   if(code=="ready")  return "就绪";
   if(code=="frozen") return "冻结";
   return code;
  }

string TradeModeLabel(const string code)
  {
   if(code=="normal") return "常规";
   if(code=="hedge")  return "对冲";
   return code;
  }

string AiRegimeLabel(const string code)
  {
   if(code=="trending")         return "趋势中";
   if(code=="ranging")          return "震荡中";
   if(code=="trend_up")         return "确认上涨";
   if(code=="trend_down")       return "确认下跌";
   if(code=="impulse_up")       return "急涨冲击";
   if(code=="impulse_down")     return "急跌冲击";
   if(code=="trend_up_watch")   return "上涨观察";
   if(code=="trend_down_watch") return "下跌观察";
   if(code=="range")            return "震荡";
   if(code=="volatile")         return "高波动";
   if(code=="transition")       return "过渡";
   if(code=="unknown")          return "未知";
   return code;
  }

string AiFamilyLabel(const string code)
  {
   if(code=="ensemble_gru_trend") return "GRU+趋势共振";
   if(code=="qlib_gru")           return "GRU模型";
   if(code=="clean")   return "确认趋势";
   if(code=="impulse") return "冲击趋势";
   if(code=="watch")   return "早期观察";
   if(code=="none")    return "无趋势";
   return code;
  }

string CurrentStateLabel(const string code)
  {
   if(StringFind(code,"score:")>=0)
     {
      string s=code;
      StringReplace(s,"score:","评分:");
      StringReplace(s,"adx:"," ADX:");
      StringReplace(s,"atr:"," ATR:");
      StringReplace(s,"slope:"," 斜率:");
      StringReplace(s,"prob:"," 概率:");
      return s;
     }
   if(code=="surge_up")                return "短线急涨";
   if(code=="surge_down")              return "短线急跌";
   if(code=="pullback_after_up")       return "上涨回调";
   if(code=="rebound_after_down")      return "下跌反弹";
   if(code=="stabilizing_after_up")    return "涨后消化";
   if(code=="stabilizing_after_down")  return "跌后消化";
   if(code=="range")                   return "短线震荡";
   if(code=="transition")              return "短线过渡";
   if(code=="unknown")                 return "未知";
   return code;
  }

string DirectionLabel(const string code)
  {
   if(code=="BUY")     return "向上";
   if(code=="SELL")    return "向下";
   if(code=="NEUTRAL") return "中性";
   return code;
  }

string ShockLabel(const string code)
  {
   if(code=="potential")       return "潜在冲击";
   if(code=="high_risk")       return "高风险冲击";
   if(code=="active_move")     return "异动进行中";
   if(code=="upside_shock" || code=="upside_impulse")     return "上涨预警";
   if(code=="downside_shock" || code=="downside_impulse") return "下跌预警";
   if(code=="none")           return "无预警";
   return code;
  }

string ImpulseStateLabel(const string code,const string dir)
  {
   if(code=="impulse_start")  return (dir=="BUY" ? "上涨启动" : (dir=="SELL" ? "下跌启动" : "冲击启动"));
   if(code=="impulse_active") return (dir=="BUY" ? "上涨进行" : (dir=="SELL" ? "下跌进行" : "冲击进行"));
   if(code=="impulse_late")   return (dir=="BUY" ? "上涨衰减" : (dir=="SELL" ? "下跌衰减" : "冲击后段"));
   if(code=="none")           return "无冲击";
   return code;
  }

string LearningOutcomeLabel(const string code)
  {
   if(code=="success") return "成功";
   if(code=="false")   return "误报";
   if(code=="neutral") return "中性";
   if(code=="none")    return "无";
   return code;
  }

void PanelButton(const string name,const int yy,const string txt,const color clr,const int x,const int w,const int h)
  {
   color bg=clr;
   if(clr==clrYellow || clr==clrWhite || clr==clrLime)
      bg=clrDimGray;
   if(ObjectFind(0,name)<0)
      ObjectCreate(0,name,OBJ_BUTTON,0,0,0);
   ObjectSetInteger(0,name,OBJPROP_CORNER,CORNER_LEFT_UPPER);
   ObjectSetInteger(0,name,OBJPROP_XDISTANCE,x);
   ObjectSetInteger(0,name,OBJPROP_YDISTANCE,yy);
   ObjectSetInteger(0,name,OBJPROP_XSIZE,w);
   ObjectSetInteger(0,name,OBJPROP_YSIZE,h);
   ObjectSetString(0,name,OBJPROP_TEXT,txt);
   ObjectSetInteger(0,name,OBJPROP_COLOR,clrWhite);
   ObjectSetInteger(0,name,OBJPROP_BGCOLOR,bg);
   ObjectSetInteger(0,name,OBJPROP_BORDER_COLOR,clrBlack);
   ObjectSetInteger(0,name,OBJPROP_FONTSIZE,8);
   ObjectSetInteger(0,name,OBJPROP_ZORDER,50);
  }

void PanelText(const string name,const int x,const int y,const string txt,const color clr,const int size,const bool bold)
  {
   if(ObjectFind(0,name)<0)
      ObjectCreate(0,name,OBJ_LABEL,0,0,0);
   ObjectSetInteger(0,name,OBJPROP_CORNER,CORNER_LEFT_UPPER);
   ObjectSetInteger(0,name,OBJPROP_XDISTANCE,x);
   ObjectSetInteger(0,name,OBJPROP_YDISTANCE,y);
   ObjectSetString(0,name,OBJPROP_TEXT,txt);
   ObjectSetInteger(0,name,OBJPROP_COLOR,clr);
   ObjectSetInteger(0,name,OBJPROP_FONTSIZE,size);
   ObjectSetString(0,name,OBJPROP_FONT,bold ? "Arial Bold" : "Arial");
   ObjectSetInteger(0,name,OBJPROP_ZORDER,10);
  }

void PanelTextScroll(const string name,const int x,const int yLogical,const int scr,const string txt,const color clr,const int size,const bool bold)
  {
   int dy=yLogical-scr;
   const int maxDy=g_clip_bottom_panel-(size/3+2);
   if(dy<g_clip_top_panel-3 || dy>maxDy)
     {
      if(ObjectFind(0,name)>=0)
        {
         ObjectSetInteger(0,name,OBJPROP_TIMEFRAMES,OBJ_NO_PERIODS);
        }
      return;
     }
   PanelText(name,x,dy,txt,clr,size,bold);
   ObjectSetInteger(0,name,OBJPROP_TIMEFRAMES,OBJ_ALL_PERIODS);
  }

void PanelBox(const string name,const int x,const int y,const int w,const int h,const color bg,const color border)
  {
   if(ObjectFind(0,name)<0)
      ObjectCreate(0,name,OBJ_RECTANGLE_LABEL,0,0,0);
   ObjectSetInteger(0,name,OBJPROP_CORNER,CORNER_LEFT_UPPER);
   ObjectSetInteger(0,name,OBJPROP_XDISTANCE,x);
   ObjectSetInteger(0,name,OBJPROP_YDISTANCE,y);
   ObjectSetInteger(0,name,OBJPROP_XSIZE,w);
   ObjectSetInteger(0,name,OBJPROP_YSIZE,h);
   ObjectSetInteger(0,name,OBJPROP_BGCOLOR,bg);
   ObjectSetInteger(0,name,OBJPROP_BORDER_COLOR,border);
   ObjectSetInteger(0,name,OBJPROP_COLOR,border);
   ObjectSetInteger(0,name,OBJPROP_STYLE,STYLE_SOLID);
   ObjectSetInteger(0,name,OBJPROP_WIDTH,1);
   ObjectSetInteger(0,name,OBJPROP_BACK,false);
   ObjectSetInteger(0,name,OBJPROP_ZORDER,1);
  }

void EnsurePanel()
  {
   if(!InpShowUI)
     {
      ObjectDelete(0,g_prefix+"_box");
      ObjectDelete(0,g_prefix+"_btn_toggle");
      ObjectDelete(0,g_prefix+"_btn_all");
      ObjectDelete(0,g_prefix+"_btn_buy");
      ObjectDelete(0,g_prefix+"_btn_sell");
      ObjectDelete(0,g_prefix+"_btn_scr_up");
      ObjectDelete(0,g_prefix+"_btn_scr_down");
      return;
     }

   const int x=8, y=16;
   const int boxW=260;
   long chartH=(long)ChartGetInteger(0,CHART_HEIGHT_IN_PIXELS);
   int pct=MathMax(50,MathMin(95,InpPanelHeightPct));
   int hFromChart=(int)(chartH*pct/100)-24;
   if(hFromChart<InpPanelMinHeight)
      hFromChart=InpPanelMinHeight;
   if(hFromChart>(int)chartH-28)
      hFromChart=MathMax(InpPanelMinHeight,(int)chartH-28);
   g_box_h=(g_panelCollapsed ? 110 : hFromChart);

   PanelBox(g_prefix+"_box",x,y,boxW,g_box_h,(color)0x1B0D05,clrDodgerBlue);
   PanelButton(g_prefix+"_btn_toggle",y+8,(g_panelCollapsed ? "展开" : "缩小"),clrDarkGray,x+boxW-56,46,18);

   if(g_panelCollapsed)
     {
      ObjectDelete(0,g_prefix+"_btn_all");
      ObjectDelete(0,g_prefix+"_btn_buy");
      ObjectDelete(0,g_prefix+"_btn_sell");
      ObjectDelete(0,g_prefix+"_btn_scr_up");
      ObjectDelete(0,g_prefix+"_btn_scr_down");
     }
   else
     {
      const int by=y+g_box_h-28;
      const int bw=78, bh=22, gap=6;
      PanelButton(g_prefix+"_btn_all",by,"全部平仓",InpColorCloseAll,x+8,bw,bh);
      PanelButton(g_prefix+"_btn_buy",by,"平多单",InpColorCloseBuy,x+8+bw+gap,bw,bh);
      PanelButton(g_prefix+"_btn_sell",by,"平空单",InpColorCloseSell,x+8+(bw+gap)*2,bw,bh);
      const int scr1=by-46;
      const int scr2=by-24;
      PanelButton(g_prefix+"_btn_scr_up",scr1,"▲",clrDarkGray,x+boxW-26,22,18);
      PanelButton(g_prefix+"_btn_scr_down",scr2,"▼",clrDarkGray,x+boxW-26,22,18);
     }
  }

void UpdateRichPanel()
  {
   if(!InpShowUI)
      return;

   const bool loaded=LoadEffectiveStatus();
   int y=18;
   PanelText(g_prefix+"_title",14,y,"网格EA",clrAqua,12,true); y+=18;
   PanelText(g_prefix+"_sub",14,y,StatusSymbol()+"  "+EnumToString((ENUM_TIMEFRAMES)_Period),clrSilver,9,false); y+=20;

   const bool termOK=(bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED);
   const bool eaOK=(bool)MQLInfoInteger(MQL_TRADE_ALLOWED);
   const bool accOK=(bool)AccountInfoInteger(ACCOUNT_TRADE_ALLOWED) && (bool)AccountInfoInteger(ACCOUNT_TRADE_EXPERT);
   const bool allOK=termOK && eaOK && accOK;
   const string permTxt=allOK ? "交易权限正常" : StringFormat("交易受限|终端:%s EA:%s 账户:%s",(termOK?"是":"否"),(eaOK?"是":"否"),(accOK?"是":"否"));
   PanelText(g_prefix+"_perm",14,y,permTxt,(allOK?clrLime:clrRed),9,true); y+=16;

   if(g_panelCollapsed)
     {
      PanelText(g_prefix+"_mini",14,y,(loaded ? "点击展开查看详情" : "等待Python状态/初始状态"),clrSilver,8,false);
      return;
     }

   const int yScrollTop=y;
   const int buyN=GetValueInt("buy_count",0);
   const int sellN=GetValueInt("sell_count",0);
   const double buyAvg=GetValueDouble("buy_avg",0.0);
   const double sellAvg=GetValueDouble("sell_avg",0.0);
   const double buyPL=GetValueDouble("buy_pnl",0.0);
   const double sellPL=GetValueDouble("sell_pnl",0.0);
   const double realizedPL=GetValueDouble("total_pnl",0.0);
   const double floatPL=GetValueDouble("floating_pnl",0.0);
   const double netLots=GetValueDouble("net_lots",0.0);
   const double allLots=GetValueDouble("total_lots",0.0);
   const double dd=GetValueDouble("drawdown_pct",0.0);
   const double marginPct=GetValueDouble("margin_level",0.0);
   const string risk=RiskLabel(GetValue("risk_level","low"));
   const string mode=(GetValueBool("enable_trading",true) ? "运行中" : "已停止");
   const string tradeModeTxt=TradeModeLabel(GetValue("trade_mode","normal"));
   const string hedgeFromTxt=GetValue("hedge_from","-");
   const string hedgeSideTxt=GetValue("hedge_side","-");
   const double hedgeTp=GetValueDouble("hedge_target",0.0);
    const string aiDir=GetValue("ai_direction","NEUTRAL");
   const string aiModelDir=GetValue("ai_model_direction","NEUTRAL");
   const string aiTradeDir=GetValue("ai_trade_direction","NEUTRAL");
   const string aiRegime=GetValue("ai_regime_cn",GetValue("ai_regime","unknown"));
   const string aiFamily=GetValue("ai_trend_family_cn",GetValue("ai_trend_family","none"));
   const string currentState=GetValue("current_state","unknown");
   const string currentPhase=GetValue("current_phase","-");
   const string currentDirection=GetValue("current_direction","NEUTRAL");
   const string impulseState=GetValue("current_impulse_state","none");
   const string impulseDirection=GetValue("current_impulse_direction","NEUTRAL");
   const double impulseConf=GetValueDouble("current_impulse_confidence",0.0);
   const int impulseAge=GetValueInt("current_impulse_age",0);
   const double impulseExt=GetValueDouble("current_impulse_extension_atr",0.0);
    const string shock=GetValue("future_impulse_warning","none");
   const string shockCn=GetValue("future_impulse_warning_cn",shock);
   const double aiConf=GetValueDouble("ai_confidence",0.0);
   const double aiProb=GetValueDouble("ai_probability",0.5);
   const string shortDir=GetValue("short_direction","NEUTRAL");
   const string shortDirTxt=GetValue("short_direction_cn","短线震荡");
   const string shortPatternTxt=GetValue("short_pattern_cn","未知");
   const string shortPrediction=GetValue("short_prediction","NEUTRAL");
   const string shortPredictionTxt=GetValue("short_prediction_cn","短线震荡");
   const string shortReason=GetValue("short_reason","-");
   const string shortModelTypeTxt=GetValue("short_model_type_cn","规则识别-未校准");
   const double shortConf=GetValueDouble("short_confidence",0.0);
   const string mlShortPrediction=GetValue("ml_short_direction","NEUTRAL");
   const string mlShortPredictionTxt=GetValue("ml_short_direction_cn","短线无可靠方向");
   const string mlShortReason=GetValue("ml_short_reason","短线模型未训练");
   const string mlShortModelTxt=GetValue("ml_short_model_type_cn","短线模型未训练");
   const double mlShortConf=GetValueDouble("ml_short_confidence",0.0);
   const int mlShortHorizon=GetValueInt("ml_short_horizon",0);
   const string vPrediction=GetValue("v_prediction","NEUTRAL");
   const string vPredictionTxt=GetValue("v_prediction_cn","短线无可靠方向");
   const string vPatternTxt=GetValue("v_pattern_cn","无V结构");
   const string vReason=GetValue("v_reason","V反转模型未训练");
   const string vModelTxt=GetValue("v_model_type_cn","V反转模型不可用");
   const string vModelConfirmTxt=GetValue("v_model_confirm_cn","无模型确认");
   const string vReliabilityTxt=GetValue("v_reliability_cn","低");
   const double vConf=GetValueDouble("v_confidence",0.0);
   const double shockConf=GetValueDouble("future_impulse_confidence",0.0);
   const double shockSuccess=GetValueDouble("future_impulse_success_rate",0.0);
   const int shockMin=GetValueInt("future_impulse_window_min",0);
   const int shockMax=GetValueInt("future_impulse_window_max",0);
   const int shockExpected=GetValueInt("future_impulse_expected_minutes",0);
   const int learnSamples=GetValueInt("future_impulse_learning_samples",0);
   const double learnSuccess=GetValueDouble("future_impulse_learning_success_rate",0.0);
   const double learnFalse=GetValueDouble("future_impulse_learning_false_rate",0.0);
   const int learnPending=GetValueInt("future_impulse_learning_pending",0);
   const bool learnReady=GetValueBool("future_impulse_learning_ready",false);
   const string learnLast=GetValue("future_impulse_learning_last_outcome","none");
   const string aiDirTxt=(aiDir=="BUY" ? "偏多" : (aiDir=="SELL" ? "偏空" : "震荡"));
   const string aiModelDirTxt=(aiModelDir=="BUY" ? "确认多头" : (aiModelDir=="SELL" ? "确认空头" : "未达确认阈值"));
   const string aiTradeDirTxt=(aiTradeDir=="BUY" ? "执行多头" : (aiTradeDir=="SELL" ? "执行空头" : "观望"));
   const string aiRegimeTxt=AiRegimeLabel(aiRegime);
   const string aiFamilyTxt=AiFamilyLabel(aiFamily);
   const string currentStateTxt=CurrentStateLabel(currentState);
   const string currentDirTxt=DirectionLabel(currentDirection);
   const string impulseTxt=ImpulseStateLabel(impulseState,impulseDirection);
   const color aiDirClr=(aiDir=="BUY" ? clrLime : (aiDir=="SELL" ? clrTomato : clrSilver));
   const color impulseClr=(impulseDirection=="BUY" ? clrLime : (impulseDirection=="SELL" ? clrTomato : clrSilver));
   const color shortClr=(shortPrediction=="BUY" ? clrLime : (shortPrediction=="SELL" ? clrTomato : clrSilver));
   const color mlShortClr=(mlShortPrediction=="BUY" ? clrLime : (mlShortPrediction=="SELL" ? clrTomato : clrSilver));
   const color vClr=(vPrediction=="BUY" ? clrLime : (vPrediction=="SELL" ? clrTomato : clrSilver));
    const string shockTxt=ShockLabel(shockCn);
   const bool shockUp=(shock=="upside_shock" || shock=="upside_impulse");
   const bool shockDown=(shock=="downside_shock" || shock=="downside_impulse");
   const color shockClr=(shockUp ? clrLime : (shockDown ? clrTomato : clrSilver));

   const int res=MathMax(70,MathMin(140,InpPanelBottomReserve));
   const int boxTop=16;
   const int btnRowY=boxTop+g_box_h-28;
   const int contentClipBottom=MathMin(boxTop+g_box_h-res,btnRowY-12);
   const int scrollClipFloor=contentClipBottom-6;
   g_clip_top_panel=yScrollTop;
   g_clip_bottom_panel=contentClipBottom;
   g_scroll_max=MathMax(0,g_panel_content_bottom_cached-scrollClipFloor);
   if(g_panel_scroll>g_scroll_max)
      g_panel_scroll=g_scroll_max;
   if(g_panel_scroll<0)
      g_panel_scroll=0;

   PanelTextScroll(g_prefix+"_src",18,y,g_panel_scroll,(loaded ? "状态文件 正常" : "状态文件 停止/初始"),(loaded?clrLime:clrOrange),8,true); y+=14;

   PanelTextScroll(g_prefix+"_sec_ai",14,y,g_panel_scroll,"【趋势方向/模型确认】",clrYellow,11,true); y+=18;
   PanelTextScroll(g_prefix+"_ai_big",18,y,g_panel_scroll,"趋势方向: "+currentStateTxt,aiDirClr,11,true); y+=17;
   PanelTextScroll(g_prefix+"_ai1",18,y,g_panel_scroll,"判断理由",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_ai1v",150,y,g_panel_scroll,currentPhase,aiDirClr,9,true); y+=14;
   PanelTextScroll(g_prefix+"_ai2",18,y,g_panel_scroll,"趋势状态",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_ai2v",150,y,g_panel_scroll,aiDirTxt+" / "+aiRegimeTxt,aiDirClr,9,true); y+=14;
   PanelTextScroll(g_prefix+"_ai3",18,y,g_panel_scroll,"模型确认",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_ai3v",150,y,g_panel_scroll,aiModelDirTxt,aiDirClr,9,true); y+=14;
   PanelTextScroll(g_prefix+"_ai3b",18,y,g_panel_scroll,"短线形态",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_ai3bv",150,y,g_panel_scroll,shortPatternTxt,shortClr,9,true); y+=14;
   PanelTextScroll(g_prefix+"_ai3c",18,y,g_panel_scroll,"短线提示",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_ai3cv",150,y,g_panel_scroll,shortReason,shortClr,9,true); y+=14;
   PanelTextScroll(g_prefix+"_ai3d",18,y,g_panel_scroll,"模型确认",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_ai3dv",150,y,g_panel_scroll,vModelConfirmTxt,vClr,9,true); y+=14;
   PanelTextScroll(g_prefix+"_ai3e",18,y,g_panel_scroll,"可靠等级",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_ai3ev",150,y,g_panel_scroll,vReliabilityTxt+" / "+vReason,vClr,9,true); y+=14;
   PanelTextScroll(g_prefix+"_ai4",18,y,g_panel_scroll,"未来冲击预警",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_ai4v",150,y,g_panel_scroll,shockTxt,shockClr,10,true); y+=14;
   PanelTextScroll(g_prefix+"_ai5",18,y,g_panel_scroll,"未来预计分钟",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_ai5v",150,y,g_panel_scroll,(shockExpected>0?IntegerToString(shockExpected)+"分":"-"),shockClr,9,true); y+=14;
   PanelTextScroll(g_prefix+"_ai6",18,y,g_panel_scroll,"未来风险窗口",clrSlateGray,9,false);
   string shockWindow="-";
   if(shock!="none" && shockMax>0)
      shockWindow=StringFormat("%d-%d分/%d分 %.0f%%",shockMin,shockMax,shockExpected,shockConf*100.0);
   PanelTextScroll(g_prefix+"_ai6v",150,y,g_panel_scroll,shockWindow,shockClr,9,true); y+=14;
   y+=6;

   PanelTextScroll(g_prefix+"_sec_pos",14,y,g_panel_scroll,"| 持仓",clrDeepSkyBlue,10,true); y+=16;
   PanelTextScroll(g_prefix+"_p1",18,y,g_panel_scroll,"多单数量",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_p1v",150,y,g_panel_scroll,IntegerToString(buyN),clrDodgerBlue,9,true); y+=14;
   PanelTextScroll(g_prefix+"_p2",18,y,g_panel_scroll,"空单数量",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_p2v",150,y,g_panel_scroll,IntegerToString(sellN),clrTomato,9,true); y+=14;
   PanelTextScroll(g_prefix+"_p3",18,y,g_panel_scroll,"净手数",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_p3v",150,y,g_panel_scroll,StringFormat("%+.2f",netLots),clrAqua,9,true); y+=14;
   PanelTextScroll(g_prefix+"_p4",18,y,g_panel_scroll,"网格层数",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_p4v",150,y,g_panel_scroll,IntegerToString(buyN+sellN),clrLime,9,true); y+=14;
   PanelTextScroll(g_prefix+"_p4o",18,y,g_panel_scroll,"本轮开仓",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_p4ov",150,y,g_panel_scroll,IntegerToString(GetValueInt("session_open_count",0)),clrWhite,9,true); y+=14;
   PanelTextScroll(g_prefix+"_p5",18,y,g_panel_scroll,"多单均价",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_p5v",150,y,g_panel_scroll,(buyN>0?DoubleToString(buyAvg,_Digits):"-"),clrDodgerBlue,9,true); y+=14;
   PanelTextScroll(g_prefix+"_p6",18,y,g_panel_scroll,"空单均价",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_p6v",150,y,g_panel_scroll,(sellN>0?DoubleToString(sellAvg,_Digits):"-"),clrTomato,9,true); y+=20;

   PanelTextScroll(g_prefix+"_sec_pl",14,y,g_panel_scroll,"| 盈亏",clrDeepSkyBlue,10,true); y+=16;
   PanelTextScroll(g_prefix+"_l1",18,y,g_panel_scroll,"本轮已实现",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_l1v",150,y,g_panel_scroll,StringFormat("%+.2f",realizedPL),(realizedPL>=0?clrLime:clrTomato),10,true); y+=14;
   PanelTextScroll(g_prefix+"_l1f",18,y,g_panel_scroll,"浮动合计",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_l1fv",150,y,g_panel_scroll,StringFormat("%+.2f",floatPL),(floatPL>=0?clrLime:clrTomato),9,true); y+=14;
   PanelTextScroll(g_prefix+"_l2",18,y,g_panel_scroll,"多单盈亏",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_l2v",150,y,g_panel_scroll,StringFormat("%+.2f",buyPL),(buyPL>=0?clrLime:clrTomato),9,true); y+=14;
   PanelTextScroll(g_prefix+"_l3",18,y,g_panel_scroll,"空单盈亏",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_l3v",150,y,g_panel_scroll,StringFormat("%+.2f",sellPL),(sellPL>=0?clrLime:clrTomato),9,true); y+=14;
   PanelTextScroll(g_prefix+"_l4",18,y,g_panel_scroll,"总手数",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_l4v",150,y,g_panel_scroll,StringFormat("%.2f",allLots),clrAqua,9,true); y+=20;

   PanelTextScroll(g_prefix+"_sec_risk",14,y,g_panel_scroll,"| 风险",clrDeepSkyBlue,10,true); y+=16;
   PanelTextScroll(g_prefix+"_r1",18,y,g_panel_scroll,"风险级别",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_r1v",150,y,g_panel_scroll,risk,(dd<5.0?clrLime:(dd<12.0?clrYellow:clrTomato)),10,true); y+=14;
   PanelTextScroll(g_prefix+"_r2",18,y,g_panel_scroll,"回撤",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_r2v",150,y,g_panel_scroll,StringFormat("%.2f%%",dd),clrYellow,9,true); y+=14;
   PanelTextScroll(g_prefix+"_r3",18,y,g_panel_scroll,"保证金率",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_r3v",150,y,g_panel_scroll,(marginPct>0?StringFormat("%.1f%%",marginPct):"-"),clrAqua,9,true); y+=20;

   PanelTextScroll(g_prefix+"_sec_st",14,y,g_panel_scroll,"| 策略",clrDeepSkyBlue,10,true); y+=16;
   PanelTextScroll(g_prefix+"_s1",18,y,g_panel_scroll,"账户模式",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_s1v",150,y,g_panel_scroll,(AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO?"模拟":"实盘"),clrWhite,9,true); y+=14;
   PanelTextScroll(g_prefix+"_s2",18,y,g_panel_scroll,"运行状态",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_s2v",150,y,g_panel_scroll,mode,(GetValueBool("enable_trading",true)?clrLime:clrOrange),9,true); y+=14;
   PanelTextScroll(g_prefix+"_s3",18,y,g_panel_scroll,"常规流程",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_s3v",150,y,g_panel_scroll,"双向首单+各自网格",clrWhite,9,true); y+=14;
   PanelTextScroll(g_prefix+"_s4",18,y,g_panel_scroll,"交易模式",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_s4v",150,y,g_panel_scroll,tradeModeTxt,(GetValue("trade_mode","normal")=="normal"?clrLime:InpHedgeModeColor),9,true); y+=14;
   PanelTextScroll(g_prefix+"_s4b",18,y,g_panel_scroll,"对冲来源",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_s4bv",150,y,g_panel_scroll,hedgeFromTxt,(GetValue("trade_mode","normal")=="normal"?clrSilver:clrYellow),9,true); y+=14;
   PanelTextScroll(g_prefix+"_s5",18,y,g_panel_scroll,"对冲方向",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_s5v",150,y,g_panel_scroll,hedgeSideTxt,clrAqua,9,true); y+=14;
   PanelTextScroll(g_prefix+"_s6",18,y,g_panel_scroll,"对冲目标",clrSlateGray,9,false);
   PanelTextScroll(g_prefix+"_s6v",150,y,g_panel_scroll,StringFormat("+%.2f",hedgeTp),clrYellow,9,true);
   y+=16;
   g_panel_content_bottom_cached=y;
   g_scroll_max=MathMax(0,y-scrollClipFloor);
   if(g_panel_scroll>g_scroll_max)
      g_panel_scroll=g_scroll_max;
   if(g_panel_scroll<0)
      g_panel_scroll=0;
  }

void DrawTPLines()
  {
   const long ch=0;
   const string b=g_prefix+"_tp_buy";
   const string s=g_prefix+"_tp_sell";
   if(!InpDrawInnerTPLines)
     {
      ObjectDelete(ch,b);
      ObjectDelete(ch,s);
      ChartRedraw(ch);
      return;
     }

   if(!LoadEffectiveStatus())
     {
      ObjectDelete(ch,b);
      ObjectDelete(ch,s);
      ChartRedraw(ch);
      return;
     }

   const int nb=GetValueInt("buy_count",0);
   const int ns=GetValueInt("sell_count",0);
   const double pb=GetValueDouble("buy_tp",0.0);
   const double ps=GetValueDouble("sell_tp",0.0);

   if(nb<=0 || pb<=0.0)
      ObjectDelete(ch,b);
   else
     {
      if(ObjectFind(ch,b)<0)
         ObjectCreate(ch,b,OBJ_HLINE,0,0,pb);
      ObjectSetDouble(ch,b,OBJPROP_PRICE,pb);
      ObjectSetInteger(ch,b,OBJPROP_COLOR,InpBuyTPLineColor);
     }

   if(ns<=0 || ps<=0.0)
      ObjectDelete(ch,s);
   else
     {
      if(ObjectFind(ch,s)<0)
         ObjectCreate(ch,s,OBJ_HLINE,0,0,ps);
      ObjectSetDouble(ch,s,OBJPROP_PRICE,ps);
      ObjectSetInteger(ch,s,OBJPROP_COLOR,InpSellTPLineColor);
     }
   ChartRedraw(ch);
  }

bool CloseSide(const int typ)
  {
   bool any=false;
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      const ulong ticket=PositionGetTicket(i);
      if(ticket==0 || !PositionSelectByTicket(ticket))
         continue;
      if(PositionGetString(POSITION_SYMBOL)!=StatusSymbol())
         continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC)!=InpMagic)
         continue;
      if((int)PositionGetInteger(POSITION_TYPE)!=typ)
         continue;
      any=true;
      if(!g_trade.PositionClose(ticket))
         Print("Close failed ticket=",ticket," ret=",g_trade.ResultRetcode()," ",g_trade.ResultRetcodeDescription());
     }
   return any;
  }

int OnInit()
  {
   g_prefix="GMMA_PANEL_"+IntegerToString((int)InpMagic);
   EventSetTimer(MathMax(1,InpRefreshSeconds));
   EnsurePanel();
   UpdateRichPanel();
   DrawTPLines();
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   ObjectsDeleteAll(0,g_prefix);
  }

void OnTimer()
  {
   EnsurePanel();
   UpdateRichPanel();
   DrawTPLines();
  }

void OnChartEvent(const int id,const long &lparam,const double &dparam,const string &sparam)
  {
   if(id==CHARTEVENT_CHART_CHANGE)
     {
      EnsurePanel();
      UpdateRichPanel();
      DrawTPLines();
      return;
     }

   if(id!=CHARTEVENT_OBJECT_CLICK)
      return;

   if(sparam==g_prefix+"_btn_toggle")
     {
      g_panelCollapsed=!g_panelCollapsed;
      g_panel_scroll=0;
      ObjectsDeleteAll(0,g_prefix);
      EnsurePanel();
      UpdateRichPanel();
      DrawTPLines();
      return;
     }

   if(sparam==g_prefix+"_btn_scr_up")
     {
      g_panel_scroll=MathMax(0,g_panel_scroll-InpPanelScrollStep);
      ObjectSetInteger(0,sparam,OBJPROP_STATE,false);
      EnsurePanel();
      UpdateRichPanel();
      DrawTPLines();
      ChartRedraw(0);
      return;
     }

   if(sparam==g_prefix+"_btn_scr_down")
     {
      g_panel_scroll+=InpPanelScrollStep;
      ObjectSetInteger(0,sparam,OBJPROP_STATE,false);
      EnsurePanel();
      UpdateRichPanel();
      DrawTPLines();
      ChartRedraw(0);
      return;
     }

   if(sparam==g_prefix+"_btn_all")
     {
      CloseSide(POSITION_TYPE_BUY);
      CloseSide(POSITION_TYPE_SELL);
     }
   if(sparam==g_prefix+"_btn_buy")
      CloseSide(POSITION_TYPE_BUY);
   if(sparam==g_prefix+"_btn_sell")
      CloseSide(POSITION_TYPE_SELL);

   if(StringFind(sparam,g_prefix+"_btn_")==0)
      ObjectSetInteger(0,sparam,OBJPROP_STATE,false);
  }
