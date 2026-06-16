"""HTML template extracted from arena.gui.templates."""
from __future__ import annotations

GUI_LOGIN_HTML = """<!DOCTYPE html>
<html><head><title>Arena Bridge — Login</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:#0d1117;color:#c9d1d9;display:flex;justify-content:center;align-items:center;min-height:100vh}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:2.5rem;width:400px;text-align:center}
.card h1{color:#58a6ff;margin-bottom:.25rem;font-size:1.6rem}
.card .sub{color:#8b949e;margin-bottom:1.5rem;font-size:.85rem}
.card input{width:100%;padding:.7rem 1rem;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:.9rem;font-family:monospace;outline:none;margin-bottom:.75rem}
.card input:focus{border-color:#58a6ff;box-shadow:0 0 0 3px rgba(88,166,255,.15)}
.card button{width:100%;padding:.7rem;background:#238636;color:#fff;border:none;border-radius:6px;font-size:.9rem;cursor:pointer;font-weight:600;transition:background .15s}
.card button:hover{background:#2ea043}
.card .err{color:#f85149;font-size:.8rem;margin-top:.5rem;min-height:1.2em}
.card .hint{color:#484f58;font-size:.75rem;margin-top:1.25rem}
</style></head>
<body>
<div class="card">
<h1>Arena Bridge</h1>
<p class="sub">Enter your auth token to access the dashboard</p>
<form id="form" onsubmit="return login()">
<input type="password" id="token" placeholder="Auth token" autofocus autocomplete="off">
<button type="submit">Sign In</button>
<div class="err" id="err"></div>
</form>
<p class="hint">Token is stored in token.txt in the bridge directory</p>
</div>
<script>
var REDIR=location.pathname;
function login(e){
  if(e)e.preventDefault();
  var t=document.getElementById('token').value.trim();
  if(!t){document.getElementById('err').textContent='Please enter a token';return false}
  document.getElementById('err').textContent='';
  document.querySelector('button').textContent='Signing in...';
  fetch('/v1/status',{headers:{'Authorization':'Bearer '+t}}).then(function(r){
    if(r.ok){
      localStorage.setItem('arena_token',t);
      var sep=REDIR.indexOf('?')>-1?'&':'?';
      location.href=REDIR+sep+'token='+encodeURIComponent(t);
    }else{
      document.getElementById('err').textContent='Invalid token';
      document.querySelector('button').textContent='Sign In';
    }
  }).catch(function(){
    document.getElementById('err').textContent='Connection failed';
    document.querySelector('button').textContent='Sign In';
  });
  return false;
}
var saved=localStorage.getItem('arena_token');
if(saved){document.getElementById('token').value=saved;login()}
</script>
</body></html>"""
