#!/usr/bin/env python3
"""
🔥 VINTED SNIPER - API Server (Production Ready)
Déployable sur Railway, Render, Fly.io, etc.
"""

import os
import re
import time
import logging
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

# ============================================
# CONFIGURATION
# ============================================

app = Flask(__name__)

# CORS - Autoriser TOUTES les origines
CORS(app, origins="*", allow_headers=["Content-Type", "Authorization"], methods=["GET", "POST", "OPTIONS"])

# Ajouter les headers CORS manuellement aussi (double sécurité)
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    return response

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Session HTTP persistante
session = requests.Session()

# Headers pour simuler un navigateur
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

# Cache simple
_cache = {}
_cache_ttl = 60  # 1 minute

# ============================================
# VINTED SESSION
# ============================================

def init_vinted_session():
    """Initialise la session avec les cookies Vinted"""
    try:
        logger.info("🔄 Initialisation session Vinted...")
        
        # Requête initiale pour obtenir les cookies
        resp = session.get(
            "https://www.vinted.fr",
            headers=HEADERS,
            timeout=15
        )
        
        # Extraire le CSRF token si présent
        csrf_match = re.search(r'"csrf_token":"([^"]+)"', resp.text)
        if csrf_match:
            session.headers.update({"X-CSRF-Token": csrf_match.group(1)})
            logger.info("✅ CSRF token récupéré")
        
        logger.info(f"✅ Session initialisée - Cookies: {list(session.cookies.keys())}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Erreur init session: {e}")
        return False


def ensure_session():
    """S'assure que la session est valide"""
    if not session.cookies:
        return init_vinted_session()
    return True


# ============================================
# API ROUTES
# ============================================

@app.route('/')
def index():
    """Page d'accueil"""
    return jsonify({
        "name": "Vinted Sniper API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "/api/search": "GET - Rechercher des articles",
            "/api/item/<id>": "GET - Détails d'un article",
            "/api/brands": "GET - Rechercher des marques",
            "/health": "GET - Status du serveur"
        }
    })


@app.route('/health')
def health():
    """Health check pour Railway/monitoring"""
    return jsonify({
        "status": "ok",
        "cookies": len(session.cookies),
        "timestamp": int(time.time())
    })


@app.route('/api/search')
def search():
    """
    Recherche d'articles Vinted
    
    Params:
        q: mots-clés (obligatoire)
        price_from: prix min
        price_to: prix max
        catalog_ids: catégorie
        status_ids: état
        brand_ids: marque
        size_ids: taille
        order: tri (newest_first, price_low_to_high, price_high_to_low, relevance)
        per_page: nombre de résultats (max 96)
    """
    
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({"error": "Paramètre 'q' requis", "items": []}), 400
    
    # Construire les paramètres
    params = {
        "search_text": query,
        "order": request.args.get('order', 'newest_first'),
        "per_page": min(int(request.args.get('per_page', 48)), 96),
    }
    
    # Paramètres optionnels
    optional_params = ['price_from', 'price_to', 'catalog_ids', 'status_ids', 'brand_ids', 'size_ids', 'color_ids', 'material_ids']
    for param in optional_params:
        value = request.args.get(param)
        if value:
            params[param] = value
    
    # Check cache
    cache_key = str(sorted(params.items()))
    if cache_key in _cache:
        data, ts = _cache[cache_key]
        if time.time() - ts < _cache_ttl:
            logger.info(f"📦 Cache hit: {query}")
            return jsonify(data)
    
    # S'assurer de la session
    ensure_session()
    
    try:
        logger.info(f"🔍 Recherche: {query}")
        
        resp = session.get(
            "https://www.vinted.fr/api/v2/catalog/items",
            params=params,
            headers=HEADERS,
            timeout=20
        )
        
        # Si 401, renouveler la session
        if resp.status_code == 401:
            logger.warning("🔄 Session expirée, renouvellement...")
            session.cookies.clear()
            init_vinted_session()
            resp = session.get(
                "https://www.vinted.fr/api/v2/catalog/items",
                params=params,
                headers=HEADERS,
                timeout=20
            )
        
        if resp.status_code != 200:
            logger.error(f"❌ Erreur Vinted: {resp.status_code}")
            return jsonify({
                "error": f"Erreur Vinted ({resp.status_code})",
                "items": []
            }), resp.status_code
        
        data = resp.json()
        items = data.get("items", [])
        
        # Formater les résultats
        results = []
        for item in items:
            results.append({
                "id": item.get("id"),
                "title": item.get("title", ""),
                "price": item.get("price", "0"),
                "currency": item.get("currency", "EUR"),
                "brand": item.get("brand_title", ""),
                "size": item.get("size_title", ""),
                "status": item.get("status", ""),
                "photo_url": item.get("photo", {}).get("url", ""),
                "url": f"https://www.vinted.fr/items/{item.get('id')}",
                "user": {
                    "login": item.get("user", {}).get("login", ""),
                },
                "favourite_count": item.get("favourite_count", 0),
                "created_at": item.get("created_at_ts", 0),
            })
        
        response_data = {
            "items": results,
            "total": len(results),
            "query": query
        }
        
        # Mettre en cache
        _cache[cache_key] = (response_data, time.time())
        
        logger.info(f"✅ {len(results)} résultats pour: {query}")
        return jsonify(response_data)
    
    except requests.exceptions.Timeout:
        logger.error("⏱️ Timeout Vinted")
        return jsonify({"error": "Timeout", "items": []}), 504
    except Exception as e:
        logger.error(f"❌ Erreur: {e}")
        return jsonify({"error": str(e), "items": []}), 500


@app.route('/api/item/<int:item_id>')
def get_item(item_id):
    """Récupère les détails d'un article"""
    ensure_session()
    
    try:
        resp = session.get(
            f"https://www.vinted.fr/api/v2/items/{item_id}",
            headers=HEADERS,
            timeout=15
        )
        
        if resp.status_code != 200:
            return jsonify({"error": "Article non trouvé"}), 404
        
        return jsonify(resp.json())
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/brands')
def search_brands():
    """Recherche de marques"""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({"brands": []})
    
    ensure_session()
    
    try:
        resp = session.get(
            "https://www.vinted.fr/api/v2/brands",
            params={"keyword": query, "per_page": "20"},
            headers=HEADERS,
            timeout=10
        )
        
        if resp.status_code == 200:
            return jsonify({"brands": resp.json().get("brands", [])})
        
        return jsonify({"brands": []})
    
    except Exception as e:
        return jsonify({"error": str(e), "brands": []}), 500


# ============================================
# STARTUP
# ============================================

# Initialiser la session au démarrage
with app.app_context():
    init_vinted_session()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    
    logger.info(f"🚀 Démarrage sur port {port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
