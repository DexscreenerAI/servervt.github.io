#!/usr/bin/env python3
"""
🔥 VINTED SNIPER - API Server v2
Avec meilleure gestion des erreurs et anti-détection
"""

import os
import re
import time
import json
import gzip
import logging
import requests
from flask import Flask, jsonify, request, make_response

try:
    import brotli
    BROTLI_AVAILABLE = True
except ImportError:
    BROTLI_AVAILABLE = False

# ============================================
# CONFIGURATION
# ============================================

app = Flask(__name__)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Session HTTP persistante
session = requests.Session()

# Headers réalistes pour éviter la détection
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
    "Sec-Ch-Ua": '"Chromium";v="123", "Not(A:Brand";v="24", "Google Chrome";v="123"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Referer": "https://www.vinted.fr/",
    "Origin": "https://www.vinted.fr",
}

# Cache
_cache = {}
_cache_ttl = 120  # 2 minutes

# ============================================
# CORS - Middleware manuel
# ============================================

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Max-Age'] = '3600'
    return response

@app.before_request
def handle_preflight():
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        return response

# ============================================
# VINTED SESSION
# ============================================

def init_vinted_session():
    """Initialise la session avec les cookies Vinted"""
    try:
        logger.info("🔄 Initialisation session Vinted...")
        
        # Clear previous cookies
        session.cookies.clear()
        
        # Requête initiale pour obtenir les cookies
        resp = session.get(
            "https://www.vinted.fr",
            headers={
                "User-Agent": HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9",
            },
            timeout=15,
            allow_redirects=True
        )
        
        logger.info(f"📄 Page d'accueil: status={resp.status_code}, length={len(resp.text)}")
        
        # Extraire le CSRF token si présent
        csrf_match = re.search(r'"csrf_token":"([^"]+)"', resp.text)
        if csrf_match:
            csrf_token = csrf_match.group(1)
            session.headers.update({"X-CSRF-Token": csrf_token})
            logger.info(f"✅ CSRF token récupéré")
        
        logger.info(f"✅ Session initialisée - Cookies: {list(session.cookies.keys())}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Erreur init session: {e}")
        return False


def ensure_session():
    """S'assure que la session est valide"""
    if not session.cookies or len(session.cookies) < 3:
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
        "version": "2.0.0",
        "status": "running",
        "endpoints": {
            "/api/search": "GET - Rechercher des articles",
            "/health": "GET - Status du serveur"
        }
    })


@app.route('/health')
def health():
    """Health check"""
    return jsonify({
        "status": "ok",
        "cookies": len(session.cookies),
        "timestamp": int(time.time())
    })


@app.route('/api/search')
def search():
    """Recherche d'articles Vinted"""
    
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({"error": "Paramètre 'q' requis", "items": []}), 400
    
    # Construire les paramètres
    params = {
        "search_text": query,
        "order": request.args.get('order', 'newest_first'),
        "per_page": min(int(request.args.get('per_page', 48)), 96),
        "page": 1,
    }
    
    # Paramètres optionnels
    optional_params = ['price_from', 'price_to', 'catalog_ids', 'status_ids', 'brand_ids', 'size_ids']
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
        logger.info(f"🔍 Recherche: {query} | Params: {params}")
        
        # Attendre un peu pour éviter le rate limiting
        time.sleep(0.5)
        
        resp = session.get(
            "https://www.vinted.fr/api/v2/catalog/items",
            params=params,
            headers=HEADERS,
            timeout=20
        )
        
        logger.info(f"📡 Réponse Vinted: status={resp.status_code}, content-type={resp.headers.get('content-type', 'unknown')}")
        
        # Si erreur 401 ou 403, renouveler la session
        if resp.status_code in [401, 403]:
            logger.warning("🔄 Session expirée, renouvellement...")
            session.cookies.clear()
            init_vinted_session()
            time.sleep(1)
            resp = session.get(
                "https://www.vinted.fr/api/v2/catalog/items",
                params=params,
                headers=HEADERS,
                timeout=20
            )
        
        # Vérifier si la réponse est du JSON
        content_type = resp.headers.get('content-type', '')
        if 'application/json' not in content_type:
            logger.error(f"❌ Réponse non-JSON: {content_type}")
            logger.error(f"❌ Contenu (500 premiers chars): {resp.text[:500]}")
            
            # Vinted nous bloque probablement, réessayer avec nouvelle session
            session.cookies.clear()
            init_vinted_session()
            
            return jsonify({
                "error": "Vinted a bloqué la requête temporairement. Réessaie dans quelques secondes.",
                "items": [],
                "retry": True
            }), 503
        
        if resp.status_code != 200:
            logger.error(f"❌ Erreur Vinted: {resp.status_code}")
            return jsonify({
                "error": f"Erreur Vinted ({resp.status_code})",
                "items": []
            }), resp.status_code
        
        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            # Essayer de décoder manuellement si compressé
            logger.warning(f"⚠️ JSON decode failed, trying manual decode...")
            logger.warning(f"Content-Encoding: {resp.headers.get('content-encoding', 'none')}")
            
            decoded = False
            
            # Essayer brotli
            if BROTLI_AVAILABLE and not decoded:
                try:
                    decompressed = brotli.decompress(resp.content)
                    data = json.loads(decompressed)
                    logger.info("✅ Décompression brotli réussie")
                    decoded = True
                except:
                    pass
            
            # Essayer gzip
            if not decoded:
                try:
                    decompressed = gzip.decompress(resp.content)
                    data = json.loads(decompressed)
                    logger.info("✅ Décompression gzip réussie")
                    decoded = True
                except:
                    pass
            
            if not decoded:
                logger.error(f"❌ JSON invalide: {e}")
                logger.error(f"❌ Contenu brut (100 bytes): {resp.content[:100]}")
                return jsonify({
                    "error": "Réponse invalide de Vinted",
                    "items": []
                }), 502
        
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


# ============================================
# STARTUP
# ============================================

# Initialiser la session au démarrage
init_vinted_session()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    
    logger.info(f"🚀 Démarrage sur port {port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
