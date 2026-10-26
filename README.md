# MailDesk

Responsive web app (Flask + IMAP) to count, list and read mail by date or date range for Gmail, Yahoo and iCloud.
Gmail counts are split into primary, social, promotions, updates, forums and spam; other providers show the total only.

## Run locally
```
pip install -r requirements.txt
python app.py     # open http://localhost:5000
```

## Deploy from GitHub
GitHub Pages only hosts static files, so the Python backend needs a host:
1. Push this repo to GitHub.
2. Create a Web Service on Render/Railway/Fly from the repo (uses `Procfile`: `gunicorn app:app`). The site is served at the same URL.
3. (Optional) To use GitHub Pages for the front end: publish the `static/` folder and set `window.API_BASE` in `static/config.js` to your backend URL.
Always serve over HTTPS because passwords travel to the backend.

## Sign in with an app password
Gmail, Yahoo and iCloud do not allow normal passwords over IMAP. Create an app password and type it in the password box (spaces are ignored):
- Gmail: Google Account > Security > turn on 2-Step Verification > App passwords.
- Yahoo: Account Security > Generate app password.
- iCloud: appleid.apple.com > Sign-In and Security > App-Specific Passwords.
Hotmail/Outlook is not supported.

## Privacy
Credentials are used for a single request and are never stored or logged. Mail is opened read-only and is not marked as read. Do not add logging of request bodies.
