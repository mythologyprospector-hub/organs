"""Small browser client for the existing Organs I/O front door.

The page is presentation only. It sends text to /io/interpret and never
executes an operation itself.
"""

from fastapi.responses import HTMLResponse

PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Renaissance Doorway</title>
  <style>
    :root { color-scheme: dark; }
    body { margin:0; font-family:system-ui,sans-serif; background:#111; color:#eee; }
    main { max-width:900px; margin:0 auto; padding:32px 20px 48px; }
    h1 { margin-bottom:4px; }
    .sub { color:#aaa; margin-top:0; }
    textarea { width:100%; min-height:130px; box-sizing:border-box; padding:14px;
      border:1px solid #444; border-radius:10px; background:#181818; color:#fff;
      font:inherit; resize:vertical; }
    button { margin-top:12px; padding:10px 18px; border:0; border-radius:8px;
      background:#eee; color:#111; font-weight:700; cursor:pointer; }
    button:disabled { opacity:.5; cursor:wait; }
    .result { margin-top:24px; padding:18px; border:1px solid #333;
      border-radius:10px; background:#181818; }
    .badge { display:inline-block; padding:4px 9px; border-radius:999px;
      background:#2a2a2a; font-weight:700; }
    pre { white-space:pre-wrap; overflow:auto; color:#bbb; }
    .examples { color:#aaa; line-height:1.7; }
    code { color:#ddd; }
  </style>
</head>
<body>
<main>
  <h1>Renaissance Doorway</h1>
  <p class="sub">A small, inspectable window into the human-facing semantic boundary.</p>

  <textarea id="text" placeholder="Say something to Renaissance..."></textarea>
  <br>
  <button id="send">Interpret</button>

  <div class="examples">
    <p>Try:</p>
    <ul>
      <li><code>I want to learn how Linux paths work.</code></li>
      <li><code>How can we tell which explanation fits?</code></li>
      <li><code>That's interesting.</code></li>
      <li><code>Something is wrong.</code></li>
    </ul>
  </div>

  <section class="result" aria-live="polite">
    <strong>Disposition:</strong> <span id="disposition" class="badge">waiting</span>
    <div id="details"></div>
    <pre id="raw"></pre>
  </section>
</main>
<script>
const text = document.getElementById("text");
const send = document.getElementById("send");
const disposition = document.getElementById("disposition");
const details = document.getElementById("details");
const raw = document.getElementById("raw");

send.addEventListener("click", async () => {
  const value = text.value.trim();
  if (!value) return;

  send.disabled = true;
  disposition.textContent = "working";
  details.textContent = "";
  raw.textContent = "";

  try {
    const response = await fetch("/io/interpret", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text: value})
    });
    const data = await response.json();

    disposition.textContent = data.disposition || (data.matched ? "operational" : "unknown");

    if (data.disposition) {
      const parts = [
        data.capability ? "capability: " + data.capability : "",
        data.mode ? "mode: " + data.mode : ""
      ].filter(Boolean);
      details.textContent = parts.join(" · ");
    } else if (data.message) {
      details.textContent = data.message;
    }

    raw.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    disposition.textContent = "error";
    details.textContent = String(error);
  } finally {
    send.disabled = false;
  }
});

text.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    send.click();
  }
});
</script>
</body>
</html>
"""

def render() -> HTMLResponse:
    return HTMLResponse(PAGE)
