"""
لوحة تحكم ويب عربية متكاملة لإضافة القنوات بروابطها أو أسمائها وتخزينها في النظام
وعرض صفقات الأزواج التي تم التحقق من مشروعيتها.
"""
import hmac
from flask import Flask, render_template, request, jsonify, Response
from channel_manager import load_channels, add_channel, remove_channel
from halal_checker import load_halal_tokens, add_halal_token
from signals_store import load_signals, clear_signals
from settings_store import load_settings
from bot_verifier import set_halal_bot
from config import WEB_PORT, WEB_HOST, PANEL_USERNAME, PANEL_PASSWORD

app = Flask(__name__)

@app.before_request
def require_login():
    """حماية اللوحة بكلمة مرور (HTTP Basic Auth) عند ضبط PANEL_PASSWORD"""
    if not PANEL_PASSWORD:
        return None
    auth = request.authorization
    if auth and hmac.compare_digest(auth.username or "", PANEL_USERNAME) \
            and hmac.compare_digest(auth.password or "", PANEL_PASSWORD):
        return None
    return Response("يرجى تسجيل الدخول", 401, {"WWW-Authenticate": 'Basic realm="Trading Panel"'})

def render_panel(message=None, status_type="info"):
    signals = load_signals()
    return render_template(
        "index.html",
        channels=load_channels(),
        tokens=load_halal_tokens(),
        settings=load_settings(),
        approved_signals=[s for s in signals if s["is_halal"]],
        rejected_signals=[s for s in signals if not s["is_halal"]],
        message=message,
        status_type=status_type
    )

@app.route("/", methods=["GET"])
def index():
    return render_panel()

@app.route("/api/signals", methods=["GET"])
def api_signals():
    """إرجاع الصفقات بصيغة JSON لتحديث الصفحة تلقائياً"""
    signals = load_signals()
    if request.args.get("halal") == "1":
        signals = [s for s in signals if s["is_halal"]]
    return jsonify(signals)

@app.route("/add-channel", methods=["POST"])
def handle_add_channel():
    channel_input = request.form.get("channel_input", "").strip()
    channel_title = request.form.get("channel_title", "").strip()
    result = add_channel(channel_input, channel_title)
    if result["success"]:
        result["message"] += " سيتم الانضمام إليها تلقائياً خلال دقيقة."
    return render_panel(result["message"], "success" if result["success"] else "warning")

@app.route("/remove-channel", methods=["POST"])
def handle_remove_channel():
    identifier = request.form.get("identifier", "").strip()
    result = remove_channel(identifier)
    return render_panel(result["message"], "info" if result["success"] else "danger")

@app.route("/add-token", methods=["POST"])
def handle_add_token():
    ticker = request.form.get("ticker", "").strip()
    notes = request.form.get("notes", "مضافة عبر لوحة التحكم").strip()
    if ticker:
        add_halal_token(ticker, notes)
        return render_panel(f"تم حفظ العملة ({ticker.upper()}) في القائمة البيضاء بنجاح.", "success")
    return render_panel("يرجى إدخال رمز العملة.", "warning")

@app.route("/set-bot", methods=["POST"])
def handle_set_bot():
    result = set_halal_bot(
        request.form.get("bot_username", ""),
        request.form.get("query_template", "")
    )
    return render_panel(result["message"], "success" if result["success"] else "warning")

@app.route("/clear-signals", methods=["POST"])
def handle_clear_signals():
    clear_signals()
    return render_panel("تم مسح سجل الصفقات.", "info")

if __name__ == "__main__":
    print(f"🚀 لوحة التحكم تعمل الآن على الرابط: http://127.0.0.1:{WEB_PORT}")
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False)
