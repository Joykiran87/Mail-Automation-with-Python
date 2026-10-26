"""MailDesk - IMAP mail counter/reader. Credentials are used per request and never stored or logged."""
import imaplib, email, re, os, html as htmlmod
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

SERVERS = {
    "gmail": "imap.gmail.com",
    "yahoo": "imap.mail.yahoo.com",
    "icloud": "imap.mail.me.com",
}
MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
GMAIL_TABS = ["primary", "social", "promotions", "updates", "forums"]
MAX_LIST, MAX_READ = 300, 40


class Bad(Exception):
    def __init__(self, msg, code=400):
        self.msg, self.code = msg, code


@app.after_request
def no_store(r):
    r.headers["Cache-Control"] = "no-store"
    return r


@app.errorhandler(Bad)
def bad(e):
    return jsonify(error=e.msg), e.code


@app.route("/")
def home():
    return app.send_static_file("index.html")


def imap_date(d):
    return f"{d.day:02d}-{MON[d.month-1]}-{d.year}"


def parse_range(data):
    try:
        s = datetime.strptime(data.get("start", ""), "%Y-%m-%d")
        e = datetime.strptime(data.get("end") or data["start"], "%Y-%m-%d")
    except (ValueError, KeyError):
        raise Bad("Choose a valid start date.")
    if e < s:
        raise Bad("The end date must not be before the start date.")
    return s, e


HELP = {
    "gmail": "Turn on 2-Step Verification in your Google Account, then create an app password under Security > 2-Step Verification > App passwords.",
    "yahoo": "In Yahoo Account Security, choose Generate app password.",
    "icloud": "At appleid.apple.com open Sign-In and Security > App-Specific Passwords and create one.",
}


def err_text(ex):
    a = ex.args[0] if ex.args else ex
    return (a.decode(errors="replace") if isinstance(a, bytes) else str(a)).strip()


def connect(data):
    prov = (data.get("provider") or "").lower()
    user = data.get("email", "").strip()
    pw = re.sub(r"\s+", "", data.get("password", ""))  # app passwords may be shown with spaces
    if prov not in SERVERS:
        raise Bad("Unknown mail provider.")
    if not user or not pw:
        raise Bad("Enter both your email address and your app password.")
    logins = [user]
    if prov == "icloud" and "@" in user and user.split("@")[1].lower() in ("icloud.com", "me.com", "mac.com"):
        logins.append(user.split("@")[0])  # iCloud sometimes wants the name before the @
    last = ""
    for u in logins:
        try:
            M = imaplib.IMAP4_SSL(SERVERS[prov], 993, timeout=30)
        except (OSError, imaplib.IMAP4.abort):
            raise Bad("Could not reach the mail server. Check your internet and try again.", 502)
        try:
            M.login(u, pw)
            return M, prov
        except imaplib.IMAP4.error as ex:
            last = err_text(ex)
            try: M.logout()
            except Exception: pass
        except (OSError, imaplib.IMAP4.abort):
            raise Bad("The mail server closed the connection. Try again.", 502)
    raise Bad("Login failed. Use an app password, not your normal password. " + HELP[prov]
              + " (Server said: " + last + ")", 401)


def special_folder(M, flag, default):
    try:
        _, lines = M.list()
        for l in lines or []:
            m = re.match(r'\((.*?)\) "(.*?)" (.*)', l.decode(errors="ignore"))
            if m and flag in m.group(1):
                return m.group(3).strip().strip('"')
    except Exception:
        pass
    return default


def select(M, folder):
    typ, _ = M.select('"%s"' % folder, readonly=True)
    return typ == "OK"


def search(M, s, e, gm=None):
    since, before = imap_date(s), imap_date(e + timedelta(days=1))
    if gm is not None:
        q = f'"{gm} after:{s:%Y/%m/%d} before:{(e + timedelta(days=1)):%Y/%m/%d}"'
        typ, d = M.search(None, "X-GM-RAW", q)
    else:
        typ, d = M.search(None, "SINCE", since, "BEFORE", before)
    return d[0].split() if typ == "OK" and d and d[0] else []


def dec(v):
    try:
        return str(make_header(decode_header(v or ""))).strip()
    except Exception:
        return v or ""


def fetch_all(M, ids, spec, chunk=40):
    out = []
    for i in range(0, len(ids), chunk):
        typ, data = M.fetch(b",".join(ids[i:i + chunk]), spec)
        out += [t[1] for t in data if isinstance(t, tuple)]
    return out


def payload(part):
    b = part.get_payload(decode=True) or b""
    return b.decode(part.get_content_charset() or "utf-8", errors="replace")


def body_of(msg):
    plain = htm = None
    for p in msg.walk():
        if p.get_content_disposition() == "attachment":
            continue
        ct = p.get_content_type()
        if ct == "text/plain" and plain is None:
            plain = payload(p)
        elif ct == "text/html" and htm is None:
            htm = payload(p)
    if plain and plain.strip():
        return plain.strip()
    if htm:
        t = re.sub(r"(?is)<(script|style).*?</\1>", "", htm)
        t = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", t)
        t = htmlmod.unescape(re.sub(r"<[^>]+>", "", t))
        return re.sub(r"\n\s*\n+", "\n\n", t).strip()
    return "(no readable text)"


def inbox_ids(M, s, e):
    if not select(M, "INBOX"):
        raise Bad("Could not open the inbox.", 502)
    ids = search(M, s, e)
    return ids[::-1]  # newest first


@app.post("/api/login")
def login():
    M, _ = connect(request.get_json(force=True))
    M.logout()
    return jsonify(ok=True)


@app.post("/api/count")
def count():
    data = request.get_json(force=True)
    s, e = parse_range(data)
    M, prov = connect(data)
    try:
        if not select(M, "INBOX"):
            raise Bad("Could not open the inbox.", 502)
        res = {}
        if prov == "gmail":
            for t in GMAIL_TABS:
                res[t] = len(search(M, s, e, gm=f"category:{t}"))
            spam = special_folder(M, "\\Junk", "[Gmail]/Spam")
            res["spam"] = len(search(M, s, e)) if select(M, spam) else 0
            total = len(search_inbox_total(M, s, e)) + res["spam"]
            return jsonify(total=total, categories=res)
        return jsonify(total=len(search(M, s, e)))
    finally:
        try: M.logout()
        except Exception: pass


def search_inbox_total(M, s, e):
    select(M, "INBOX")
    return search(M, s, e)


@app.post("/api/list")
def listing():
    data = request.get_json(force=True)
    s, e = parse_range(data)
    M, _ = connect(data)
    try:
        ids = inbox_ids(M, s, e)
        total, ids = len(ids), ids[:MAX_LIST]
        rows = []
        for raw in fetch_all(M, ids, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"):
            m = email.message_from_bytes(raw)
            rows.append(dict(sender=dec(m["From"]), subject=dec(m["Subject"]) or "(no subject)", date=dec(m["Date"])))
        return jsonify(total=total, shown=len(rows), mails=rows)
    finally:
        try: M.logout()
        except Exception: pass


@app.post("/api/read")
def read():
    data = request.get_json(force=True)
    s, e = parse_range(data)
    M, _ = connect(data)
    try:
        ids = inbox_ids(M, s, e)
        total, ids = len(ids), ids[:MAX_READ]
        mails = []
        for raw in fetch_all(M, ids, "(BODY.PEEK[])", chunk=10):
            m = email.message_from_bytes(raw)
            mails.append(dict(sender=dec(m["From"]), subject=dec(m["Subject"]) or "(no subject)",
                              date=dec(m["Date"]), body=body_of(m)))
        return jsonify(total=total, shown=len(mails), mails=mails)
    finally:
        try: M.logout()
        except Exception: pass


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
