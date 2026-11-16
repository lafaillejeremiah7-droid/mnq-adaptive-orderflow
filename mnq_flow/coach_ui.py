"""Tiny localhost-only UI for manual MNQ evaluation coaching. No order execution."""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from .manual_coach import checklist
from .payout_coach import ET, config_read, journal_read, number, risk_check, summary, usd

PORT = 8766
MAX_BODY = 16_384

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MNQ 25K Evaluation Coach</title>
<style>
:root{color-scheme:dark;font-family:system-ui,-apple-system,sans-serif}
*{box-sizing:border-box}
body{background:#0b1018;color:#e5e9f0;max-width:1050px;margin:auto;padding:24px 15px 70px;line-height:1.45}
h1{font-size:1.8rem;margin:0 0 8px}h2{font-size:1.25rem;margin:0 0 14px}
p{color:#b3becc}
.panel{border:1px solid #2a3546;background:#131d29;border-radius:13px;padding:20px;margin:16px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:12px}
label{display:block;font-size:.87rem;color:#aebccc}
input,select{display:block;margin-top:6px;width:100%;padding:10px;font:inherit;color:#f4f5f6;border-radius:7px;border:1px solid #445269;background:#0b1420}
input[type=checkbox]{display:inline;width:auto;transform:scale(1.35);margin:8px 12px 8px 4px}
button{background:#78aefb;border:none;border-radius:8px;color:#08101d;font-weight:750;padding:13px 18px;margin:15px 0 0;cursor:pointer;font:inherit}
button:disabled{opacity:.5}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#0b1420;padding:14px;border-radius:8px;border:1px solid #303f52}
strong{color:#f1f4f8}.muted{font-size:.88rem}
.status{font-size:1.1rem;font-weight:700}
.ok{color:#7ae1a1}.no{color:#ff8888}
progress{width:100%;height:18px;accent-color:#78aefb}
</style>
</head>
<body>
<h1>MNQ Evaluation Coach</h1>
<p>25K evaluation • Risk first • No brokerage connection • Never submits orders</p>
<section class="panel">
<h2>Automatic live MNQ feed</h2>
<div id="liveFeed" class="status">Waiting for a licensed live market-data connection...</div>
<pre id="liveDetails">No live data received. This does not read your existing chart subscription.</pre>
<p class="muted">This section updates automatically. Market signals are experimental, not trading orders or verified evidence of a profitable strategy. A separate licensed data connection is required.</p>
</section>
<section class="panel"><h2>Evaluation progress</h2>
<div id="progressText">Loading local journal...</div><progress id="progress" max="1500" value="0"></progress>
<p class="muted">Progress is calculated from your manually recorded net trade P&L, not official account data.</p>
</section>
<section class="panel">
<h2>Review a proposed setup</h2>
<p class="muted">You already see volume profile, absorption, delta and CVD on your chart. Enter your observations and up-to-date broker figures. Nothing is read automatically.</p>
<form id="checkForm">
<div class="grid">
<label>Direction<select name="side"><option value="long">Long</option><option value="short">Short</option></select></label>
<label>15m bias<select name="bias"><option value="up">Up</option><option value="down">Down</option><option value="neutral">Neutral</option></select></label>
<label>Nearest volume-profile level<select name="level"><option value="val">VAL</option><option value="poc">POC</option><option value="vah">VAH</option><option value="other">None</option></select></label>
<label>Level reaction<select name="reaction"><option value="rejection">Rejection</option><option value="reclaim">Reclaim</option><option value="acceptance">Acceptance</option><option value="none">None</option></select></label>
<label>Absorption observation<select name="absorption"><option value="bullish">Bullish</option><option value="bearish">Bearish</option><option value="none">None</option></select></label>
<label>5m delta<select name="delta5"><option value="positive">Positive</option><option value="negative">Negative</option><option value="neutral">Neutral</option></select></label>
<label>CVD direction<select name="cvd"><option value="rising">Rising</option><option value="falling">Falling</option><option value="flat">Flat</option></select></label>
<label>1m trigger seen?<input type="checkbox" name="trigger"></label>
</div>
<h2 style="margin-top:22px">Position and account</h2>
<div class="grid">
<label>Entry price<input name="entry" inputmode="decimal" type="number" step="0.25" required placeholder="Actual proposed price"></label>
<label>Stop price<input name="stop" inputmode="decimal" type="number" step="0.25" required placeholder="Actual stop"></label>
<label>MNQ contracts<input name="contracts" type="number" min="1" step="1" value="1" required></label>
<label>Current broker equity ($)<input name="equity" type="number" step="0.01" required placeholder="Includes unrealized P&L"></label>
<label>Current drawdown floor ($)<input name="floor" type="number" step="0.01" required placeholder="From firm dashboard"></label>
<label>Open contracts<input name="open_contracts" type="number" min="0" step="1" value="0" required></label>
<label>Today's broker realized NET P&L ($)<input name="broker_day_net" type="number" step="0.01" value="0" required></label>
<label>Trades today (broker)<input name="broker_trades" type="number" min="0" step="1" value="0" required></label>
<label>Consecutive losses<input name="broker_losses" type="number" min="0" step="1" value="0" required></label>
</div>
<button type="submit">Review risk</button>
</form>
<pre id="result">No setup checked.</pre>
</section>
<section class="panel">
<h2>Record a completed trade</h2>
<p class="muted">After the trade closes, enter its realized NET result including fees. Check your broker statement first. This local journal is not synchronized.</p>
<form id="recordForm">
<div class="grid">
<label>Session date (New York)<input name="date" type="date" required></label>
<label>Net P&L ($)<input name="net" type="number" step="0.01" required placeholder="Example: -25.50"></label>
<label>Setup label<input name="setup" maxlength="50" placeholder="Example: VAL rejection"></label>
</div>
<button type="submit">Record closed trade</button>
</form>
<pre id="recordResult">No trades recorded through this page.</pre>
</section>
<p class="muted">REVIEW ONLY is not a recommendation to trade, a risk guarantee, or proof of an edge. Actual fills can exceed planned risk. The firm account dashboard takes priority over this manual tool.</p>
<script>
"use strict";
async function callApi(endpoint,payload){
  const response=await fetch(endpoint,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
  const data=await response.json();
  if(!response.ok)throw Error(data.error||"Request failed");
  return data;
}
async function refreshLive(){
  const label=document.getElementById("liveFeed");
  const details=document.getElementById("liveDetails");
  try{
    const response=await fetch("/api/live",{cache:"no-store"});
    const state=await response.json();
    if (!response.ok) throw Error(state.error || "Feed unavailable");
    if(!state.connected){
      label.textContent="NO LIVE FEED — "+state.status;
      label.className="status no";
      details.textContent=state.reason || "No recent complete MNQ minute received.";
      return;
    }
    label.textContent=state.actionable_live_candidate ?
      "EXPERIMENTAL SETUP: "+state.signal : "LIVE MNQ — NO CONFIRMED CANDIDATE";
    label.className=state.actionable_live_candidate?"status ok":"status";
    const profile=state.developing_rth_profile || {};
    details.textContent=
      "Contract: "+(state.contract || "unknown")+
      "\nCompleted minute: "+state.asof+
      "\n15m bias: "+state.fifteen_minute_bias+
      "\n5m delta: "+(state.five_minute_closed?.delta ?? "warming up")+
      "\n1m delta: "+(state.one_minute?.delta ?? "warming up")+
      "\nRTH CVD: "+state.rth_cvd+
      "\nPOC / VAH / VAL: "+[profile.poc,profile.vah,profile.val].map(v=>v??"n/a").join(" / ")+
      "\nAbsorption proxy: "+JSON.stringify(state.absorption_proxy)+
      "\nData healthy: "+state.data_healthy+
      "\n\nNo automated order placement. Broker risk limits are not monitored.";
  }catch(error){
    label.textContent="FEED ERROR";
    label.className="status no";
    details.textContent=String(error);
  }
}
async function refresh(){
  try{
    const response=await fetch("/api/status");
    const data=await response.json();
    if(!response.ok)throw Error(data.error||"Status unavailable");
    const target=data.evaluation_profit_target||1500;
    const amount=data.recorded_net_profit;
    document.getElementById("progress").max=target;
    document.getElementById("progress").value=Math.max(0,Math.min(target,amount));
    document.getElementById("progressText").textContent=
      "$"+amount.toFixed(2)+" net logged / $"+target.toFixed(2)+
      " evaluation target. Remaining: $"+data.profit_remaining.toFixed(2)+
      ". Consistency: none. Recorded trades: "+data.recorded_trades+".";
  }catch(error){
    document.getElementById("progressText").textContent=String(error);
  }
}
function payloadFrom(form){
  const data=new FormData(form);
  return Object.fromEntries(data.entries());
}
document.getElementById("checkForm").addEventListener("submit",async event=>{
  event.preventDefault();
  const out=document.getElementById("result");
  out.textContent="Checking...";
  const obj=payloadFrom(event.target);
  obj.trigger=event.target.elements.trigger.checked;
  try{
    const result=await callApi("/api/check",obj);
    out.textContent=result.decision+"\n\n"+
      (result.reasons.length ? "Reasons:\n- "+result.reasons.join("\n- "):"All supplied checks passed. Manual review still required.")+
      "\n\nEstimated planned loss: $"+result.estimated_planned_risk_usd.toFixed(2)+
      "\nAvailable configured budget: $"+result.available_risk_budget_usd.toFixed(2)+
      "\n\n"+result.warning;
    out.className=result.decision==="BLOCK"?"no":"ok";
  }catch(error){out.textContent=String(error);out.className="no";}
});
document.getElementById("recordForm").addEventListener("submit",async event=>{
  event.preventDefault();
  const out=document.getElementById("recordResult");
  const obj=payloadFrom(event.target);
  try{
    const response=await callApi("/api/record",obj);
    out.textContent="Recorded date "+response.recorded.date+
      " net P&L $"+response.recorded.net_pnl+
      ". Journal trade count: "+response.status.recorded_trades;
    await refresh();
  }catch(error){out.textContent=String(error);}
});
refresh();
refreshLive();
setInterval(refreshLive,5000);
</script>
</body>
</html>
"""

def check_payload(payload: dict[str, Any], config: dict, rows: list, now: datetime) -> dict:
    choices = {
        "side": ("long", "short"),
        "bias": ("up", "down", "neutral"),
        "level": ("poc", "vah", "val", "other"),
        "reaction": ("rejection", "reclaim", "acceptance", "none"),
        "absorption": ("bullish", "bearish", "none"),
        "delta5": ("positive", "negative", "neutral"),
        "cvd": ("rising", "falling", "flat"),
    }
    for field, options in choices.items():
        if payload.get(field) not in options:
            raise ValueError(f"Invalid {field}")
    for field in ("contracts", "open_contracts", "broker_trades", "broker_losses"):
        value = int(payload[field])
        if str(value) != str(payload[field]):
            raise ValueError(f"Invalid integer: {field}")
    reported = checklist(
        payload["side"], payload["bias"], payload["level"], payload["reaction"],
        payload["absorption"], payload["delta5"], payload["cvd"],
        payload.get("trigger") is True,
    )
    result = risk_check(
        config, rows, side=payload["side"], entry=number(payload["entry"]),
        stop=number(payload["stop"]), contracts=int(payload["contracts"]),
        equity=number(payload["equity"]), floor=number(payload["floor"]),
        open_contracts=int(payload["open_contracts"]),
        broker_day_net=number(payload["broker_day_net"]),
        broker_trades=int(payload["broker_trades"]),
        broker_losses=int(payload["broker_losses"]), at=now,
        setup=(payload["side"] + "_candidate") if reported["passed"] else "none",
    )
    result["manual_chart_checklist"] = reported
    return result

def record_payload(payload: dict, journal_path: str | Path, config: dict) -> dict:
    session = str(payload["date"])
    date.fromisoformat(session)
    setup = str(payload.get("setup", "manual"))
    if len(setup) > 50:
        raise ValueError("Setup label too long")
    item = {"date": session, "net_pnl": usd(number(payload["net"])), "setup": setup}
    with open(journal_path, "a", encoding="utf-8") as output:
        output.write(json.dumps(item, separators=(",", ":")) + "\n")
    return {"recorded": item, "status": summary(config, journal_read(journal_path))}

def handler_class(config_path: str, journal_path: str):
    class Handler(BaseHTTPRequestHandler):
        def _check_host(self) -> bool:
            if self.headers.get("Host") not in (
                f"127.0.0.1:{PORT}", f"localhost:{PORT}"
            ):
                self._json({"error": "Invalid Host"}, 403)
                return False
            return True

        def _json(self, obj: dict, code: int = 200):
            raw = json.dumps(obj, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if not self._check_host():
                return
            if self.path == "/":
                raw = PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                    "connect-src 'self'; form-action 'self'",
                )
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            elif self.path == "/api/live":
                try:
                    path = Path("live_status.json")
                    if not path.exists():
                        self._json({
                            "connected": False, "status": "NOT CONNECTED",
                            "reason": "Start a licensed feed with python3 -m mnq_flow.live_stream. "
                                      "No synthetic or delayed prices will be shown as live."
                        })
                    else:
                        latest = json.loads(path.read_text(encoding="utf-8"))
                        observed = datetime.fromisoformat(latest["asof"])
                        age = (datetime.now(ET) - observed.astimezone(ET)).total_seconds()
                        if age < 0 or age > 120 or not latest.get("data_healthy"):
                            self._json({
                                "connected": False, "status": "STALE OR DEGRADED",
                                "reason": "Latest minute is stale or has incomplete source data. "
                                          "Do not use it for an entry.",
                                "age_seconds": round(age, 2),
                            })
                        else:
                            latest["connected"] = True
                            latest["actionable_live_candidate"] = bool(
                                latest.get("signal") != "none"
                                and latest.get("actionable_live_candidate")
                            )
                            self._json(latest)
                except (OSError, KeyError, ValueError, json.JSONDecodeError) as err:
                    self._json({"error": str(err)}, 400)
            elif self.path == "/api/status":
                try:
                    self._json(summary(config_read(config_path), journal_read(journal_path)))
                except (OSError, KeyError, ValueError, json.JSONDecodeError) as err:
                    self._json({"error": str(err)}, 400)
            else:
                self._json({"error": "Unknown endpoint"}, 404)

        def do_POST(self):
            if not self._check_host():
                return
            if self.path not in ("/api/check", "/api/record"):
                return self._json({"error": "Unknown endpoint"}, 404)
            if self.headers.get("Origin") not in (
                None, f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"
            ):
                return self._json({"error": "Invalid request origin"}, 403)
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return self._json({"error": "Expected application/json"}, 415)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    raise ValueError("Request too large or empty")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Expected JSON object")
                cfg = config_read(config_path)
                if self.path == "/api/check":
                    result = check_payload(payload, cfg, journal_read(journal_path),
                                           datetime.now(ET))
                else:
                    result = record_payload(payload, journal_path, cfg)
                self._json(result)
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as err:
                self._json({"error": str(err)}, 400)

    return Handler

def main() -> None:
    p = argparse.ArgumentParser(description="Offline-first manual MNQ evaluation dashboard")
    p.add_argument("--config", default="account.json")
    p.add_argument("--journal", default="trades.jsonl")
    args = p.parse_args()
    cfg = Path(args.config)
    if not cfg.exists():
        p.error("Missing account.json; first copy sample/evaluation_25k_example.json to account.json")
    config_read(cfg)
    # Single threaded, no remote access, never opens a broker trade.
    with HTTPServer(("127.0.0.1", PORT), handler_class(str(cfg), args.journal)) as server:
        print(f"Local-only MNQ coach: http://127.0.0.1:{PORT}")
        print("Keep terminal open; use Ctrl+C to stop. No remote market or account sync.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Stopped")

if __name__ == "__main__":
    main()
