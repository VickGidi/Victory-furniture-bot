from flask import Flask, jsonify, request, render_template
from difflib import SequenceMatcher
import json
import re
import os

app = Flask(__name__)

# Load knowledge base (expects a list of dicts, see provided knowledge_base.json)
DATA_PATH = os.path.join(os.path.dirname(__file__), "knowledge_base.json")
with open(DATA_PATH, "r", encoding="utf-8") as f:
    KB = json.load(f)

# Build product/category/branches indexes in a backward-compatible way
# Support both older "category" keyed items and structured 'type' entries.
PRODUCTS = [item for item in KB if item.get("type") == "product" or (item.get("category") and item.get("category") != "Info" and item.get("url"))]
CATEGORIES = sorted({(item.get("category") or "").lower() for item in KB if item.get("category") and item.get("category") != "Info"})
BRANCHES_ENTRY = next((item for item in KB if item.get("type") == "branches"), None)
BRANCHES = BRANCHES_ENTRY.get("items", []) if BRANCHES_ENTRY else []

# Category synonyms for better matching
CATEGORY_SYNONYMS = {
    "living": "living room",
    "living-room": "living room",
    "sitting": "living room",
    "lounge": "living room",
    "sofa": "living room",
    "couch": "living room",
    "decor": "home decor",
    "décor": "home decor",
    "home decor": "home decor",
    "office": "office",
    "bed": "bedroom",
    "bedroom": "bedroom",
    "dine": "dining",
    "dining": "dining",
    "outdoor": "outdoor",
    "garden": "outdoor",
}

# City aliases to find nearest branch when user mentions a city
CITY_ALIASES = {
    "nairobi": ["nairobi", "ciata", "kiambu"],
    "nakuru": ["nakuru", "nmall", "vicmark", "kenyatta", "government road"],
    "eldoret": ["eldoret", "rupa", "rupas", "rupas mall"],
    "meru": ["meru", "greencity", "green city"]
}

# Triggers and helpers
GREETINGS = ["hi", "hello", "hey", "habari", "mambo", "niaje", "good morning", "good afternoon", "good evening", "greetings"]
ABOUT_TRIGGERS = ["about", "who are you", "what is victory furniture", "victory furniture"]

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())

def token_set_ratio(a: str, b: str) -> float:
    set_a = set(re.findall(r"\w+", (a or "").lower()))
    set_b = set(re.findall(r"\w+", (b or "").lower()))
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union

def best_match(query: str, items: list, threshold: float = 0.62):
    query_norm = normalize(query)
    best = None
    best_score = 0.0
    for item in items:
        name = item.get("name","")
        cat  = item.get("category","")
        text = f"{name} {cat} {item.get('description','')}"
        s1 = SequenceMatcher(None, query_norm, name.lower()).ratio()
        s2 = token_set_ratio(query_norm, name)
        s3 = 0.35 * token_set_ratio(query_norm, text)
        score = max(s1, s2) + s3
        if score > best_score:
            best_score = score
            best = item
    if best and best_score >= threshold:
        return best, best_score
    return None, 0.0

def products_in_category(cat_name: str):
    cat_norm = normalize(cat_name)
    for key, canonical in CATEGORY_SYNONYMS.items():
        if key in cat_norm:
            cat_norm = canonical
            break
    return [p for p in PRODUCTS if normalize(p.get("category","")) == cat_norm]

def friendly_link(name: str, url: str) -> str:
    return f"<a href='{url}' target='_blank' rel='noopener'>{name}</a>"

def greeting_response():
    return ("Hi there! 👋 Welcome to Victory Furniture. "
            "Tell me what you’re shopping for—dining sets, bedroom pieces, decor, or outdoor comfort—and I’ll show you great options.")

def about_response():
    about = next((x for x in KB if (x.get("type") == "info" or x.get("category") == "Info")), None)
    if about:
        return (f"{about.get('description','')} "
                f"Learn more here: {friendly_link(about.get('name','About Us'), about.get('url','/'))}")
    return "We’re Victory Furniture—bringing style, comfort, and value to every room in your home."

def suggest_categories():
    cats = sorted({(item.get("category") or '').title() for item in KB if item.get("category") and item.get("category") != "Info"})
    return "You can browse by category: " + ", ".join(cats) + "."

def locations_list():
    return (
        "<b>Nakuru</b><br>"
        "📍 Nmall Plaza, Kenyatta Avenue — 📞 0729856769<br>"
        "📍 Vicmark Plaza, Government Road — 📞 0748578515<br><br>"
        "<b>Nairobi</b><br>"
        "📍 Ciata Mall, Kiambu Road — 📞 0707681684<br><br>"
        "<b>Eldoret</b><br>"
        "📍 Rupas Mall — 📞 0702198186<br><br>"
        "<b>Meru</b><br>"
        "📍 Greencity Mall — 📞 0748578516<br><br>"
        "<b>Social Media</b><br>"
        "🌐 <a href='https://www.facebook.com/people/Victory-Furniture-Ke/61562878287913/' target='_blank'>Facebook</a><br>"
        "🌐 <a href='https://www.instagram.com/victory_furniture_ke/' target='_blank'>Instagram</a>"
    )


def location_for_query(q: str):
    qn = normalize(q)
    for city, aliases in CITY_ALIASES.items():
        for a in aliases:
            if a in qn:
                # find branch with matching city substring
                for b in BRANCHES:
                    if city in b['city'].lower() or city in b.get('place','').lower():
                        return b
    return None

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True) or {}
    user_msg = data.get("message","").strip()
    if not user_msg:
        return jsonify({"reply": greeting_response()})
    q = normalize(user_msg)

    # Greetings
    if any(g in q for g in GREETINGS):
        return jsonify({"reply": greeting_response()})

    # About
    if any(t in q for t in ABOUT_TRIGGERS) or "about us" in q:
        return jsonify({"reply": about_response()})

    # Ask for categories
    if "categories" in q or "category" in q or "show products" in q or "browse" in q:
        return jsonify({"reply": suggest_categories()})

    # Location requests (explicit)
    if any(k in q for k in ["shop", "location", "branch", "contact", "where", "find"]):
        specific = location_for_query(q)
        if specific:
            return jsonify({"reply": (
                f"Hmm… I’m not sure about that one yet, but our team in {specific['city']} can help. "
                f"Find them at {specific['place']} — call {specific['tel']}. They’ll be happy to assist!"
            )})
        else:
            # list all branches neatly
            return jsonify({"reply": (
                "I’m not too sure about that yet, but no worries — you can reach any of our branches below:\n\n"
                f"{locations_list()}"
            )})

    # Category products (direct-like queries)
    for key, canonical in CATEGORY_SYNONYMS.items():
        if key in q or canonical in q:
            prods = products_in_category(canonical)
            if prods:
                snippet = []
                for p in prods[:6]:
                    snippet.append(f"• {p['name']} — {friendly_link('View', p['url'])}")
                more = "" if len(prods) <= 6 else f" (+{len(prods)-6} more on our site)"
                return jsonify({"reply": f"Lovely choice! Here are popular picks in {canonical.title()}:\n" + "\n".join(snippet) + more})
            else:
                return jsonify({"reply": "That category looks empty right now—can I suggest Dining or Bedroom instead?"})

    # Product fuzzy search
    item, score = best_match(user_msg, [p for p in PRODUCTS if p.get("category") != "Info"])
    if item:
        price = item.get("price","")
        price_txt = f" Price: {price}." if price else ""
        reply = (f"You’ll love our **{item['name']}**. {item.get('description','')}"
                 f"{price_txt} See more: {friendly_link(item['name'], item['url'])}")
        return jsonify({"reply": reply})

    # Final friendly fallback (listed and easy-to-scan)
    return jsonify({"reply": (
        "I’m not completely sure about that yet — but I can help you in two ways:\n\n"
        "1️⃣ Browse products by category:\n"
        "• Dining\n• Bedroom\n• Home Decor\n• Outdoor\n• Office\n\n"
        "2️⃣ Reach one of our friendly branch teams:\n"
        f"{locations_list()}"
    )})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
