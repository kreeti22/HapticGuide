from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="HapticGuide Deprecated")

@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse(
        """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>HapticGuide Deprecated</title>
  <style>
    body { font-family: Arial, sans-serif; background: #111827; color: #f8fafc; margin: 0; display: flex; align-items: center; justify-content: center; min-height: 100vh; }
    .card { max-width: 520px; padding: 24px; border-radius: 20px; background: rgba(15, 23, 42, 0.95); box-shadow: 0 10px 40px rgba(0,0,0,0.35); }
    h1 { margin-top: 0; font-size: 28px; }
    p { line-height: 1.6; }
    code { display: block; padding: 12px; background: #0f172a; border-radius: 12px; margin-top: 12px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Deprecated Server</h1>
    <p>You are running <strong>backend/app.py</strong>, which is the old WebSocket transport layer and should no longer be used.</p>
    <p>Use the new HTTP transport server instead:</p>
    <code>python main.py</code>
    <p>Then open the same IP address in your browser again.</p>
  </div>
</body>
</html>
        """,
        status_code=200,
    )
