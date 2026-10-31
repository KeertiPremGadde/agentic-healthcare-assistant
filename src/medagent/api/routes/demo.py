"""A tiny browser page to try the API and watch the SSE stream before the real frontend exists
(Phase 6). Served only when APP_ENV=local. No data leaves the page except calls to this API; the
token lives in a JavaScript variable (not localStorage) and model output is inserted as text,
never as HTML."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MedAgent demo</title>
<style>
 body{font:15px/1.5 system-ui,sans-serif;max-width:720px;margin:1.5rem auto;padding:0 1rem;color:#1b1f23}
 .notice{background:#fff4ce;border:1px solid #e3c766;padding:.6rem .8rem;border-radius:6px;margin-bottom:1rem}
 fieldset{border:1px solid #ccd;border-radius:6px;margin-bottom:1rem}
 input,button{font:inherit;padding:.4rem .6rem} input{margin-right:.4rem}
 #log{border:1px solid #ccd;border-radius:6px;min-height:240px;max-height:55vh;overflow:auto;padding:.6rem}
 .msg{margin:.4rem 0;white-space:pre-wrap} .user{color:#0b57d0} .bot{color:#1b1f23}
 .step{color:#6b7280;font-style:italic} .err{color:#b3261e} .conf{background:#eef3ff;padding:.5rem;border-radius:6px}
 #chat{display:none}
</style></head><body>
<h1>MedAgent demo</h1>
<div class="notice">This is a demo with <b>synthetic data</b>. Do not enter real personal or health information.</div>
<fieldset id="auth"><legend>Account</legend>
 <input id="u" placeholder="username" autocomplete="username">
 <input id="p" type="password" placeholder="password (10+ chars)" autocomplete="current-password">
 <button id="reg">Register</button> <button id="login">Log in</button> <span id="authmsg"></span>
</fieldset>
<div id="chat">
 <div id="log"></div>
 <p><input id="m" size="52" placeholder="Ask a health question, find a doctor, book..." maxlength="1000">
 <button id="send">Send</button> <small id="who"></small></p>
</div>
<script>
let token = null, conversation = null;
const $ = (id) => document.getElementById(id);
const log = $("log");
function add(cls, text){ const d=document.createElement("div"); d.className="msg "+cls; d.textContent=text; log.appendChild(d); log.scrollTop=log.scrollHeight; return d; }
async function api(path, opts={}){ opts.headers = Object.assign({}, opts.headers, token ? {Authorization:"Bearer "+token} : {}); return fetch(path, opts); }
async function errorText(r){ try{ return (await r.json()).error.message; }catch{ return r.status+" "+r.statusText; } }

async function register(){
  const r = await fetch("/v1/auth/register",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:$("u").value,password:$("p").value})});
  $("authmsg").textContent = r.ok ? "Registered. Now log in." : await errorText(r);
}
async function login(){
  const r = await fetch("/v1/auth/login",{method:"POST",body:new URLSearchParams({username:$("u").value,password:$("p").value})});
  if(!r.ok){ $("authmsg").textContent = await errorText(r); return; }
  token = (await r.json()).access_token; $("p").value="";
  $("auth").style.display="none"; $("chat").style.display="block"; $("who").textContent="Logged in as "+$("u").value;
  add("step","Logged in. Say hello!");
}

async function readStream(response){
  if(!response.ok){ add("err", await errorText(response)); return; }
  const reader = response.body.getReader(), dec = new TextDecoder();
  let buf = "", bubble = null, status = null;
  for(;;){
    const {value, done} = await reader.read(); if(done) break;
    buf += dec.decode(value, {stream:true});
    let i; while((i = buf.indexOf("\n\n")) >= 0){
      const block = buf.slice(0,i); buf = buf.slice(i+2);
      let ev = "message", data = "";
      for(const line of block.split("\n")){ if(line.startsWith("event:")) ev=line.slice(6).trim(); else if(line.startsWith("data:")) data+=line.slice(5).trim(); }
      if(!data) continue; const d = JSON.parse(data);
      if(ev==="step"){ if(!status) status=add("step",""); status.textContent=d.label; }
      else if(ev==="token"){ if(status){status.remove(); status=null;} if(!bubble) bubble=add("bot",""); bubble.textContent+=d.text; }
      else if(ev==="confirmation"){ if(status){status.remove(); status=null;} confirmBox(d); }
      else if(ev==="done"){ conversation = d.conversation_id; if(status) status.remove(); add("step","["+d.usage.input_tokens+" in / "+d.usage.output_tokens+" out tokens, ~$"+d.usage.est_cost_usd.toFixed(4)+"]"); }
      else if(ev==="error"){ add("err", d.message); }
    }
  }
}
function confirmBox(d){
  const box = add("conf", d.question + " "); const yes=document.createElement("button"), no=document.createElement("button");
  yes.textContent="Yes"; no.textContent="No";
  const answer = async (ok) => { yes.disabled=no.disabled=true; await readStream(await api("/v1/chat/"+conversation+"/resume",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({confirmed:ok})})); };
  yes.onclick=()=>answer(true); no.onclick=()=>answer(false); box.append(yes," ",no);
}
async function send(){
  const text=$("m").value.trim(); if(!text) return; $("m").value=""; add("user","You: "+text);
  const body = {message:text}; if(conversation) body.conversation_id = conversation;
  await readStream(await api("/v1/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}));
}
$("reg").onclick=register; $("login").onclick=login; $("send").onclick=send;
$("m").addEventListener("keydown",(e)=>{ if(e.key==="Enter") send(); });
</script></body></html>
"""

CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; frame-ancestors 'none'"
)


@router.get("/demo", response_class=HTMLResponse)
async def demo() -> HTMLResponse:
    return HTMLResponse(PAGE, headers={"Content-Security-Policy": CSP})
