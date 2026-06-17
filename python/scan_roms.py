#!/usr/bin/env python3
"""
scan_roms.py — Étape 1 du projet Jellyfin-Wii
Lit un dossier de ROMs Wii, interroge l'API IGDB,
et génère un fichier library.json avec toutes les métadonnées.
"""

import os       # Pour lire les fichiers et dossiers
import json     # Pour écrire le fichier JSON final
import requests # Pour faire des requêtes HTTP vers l'API IGDB
                # Doc : https://docs.python-requests.org/en/latest/
import re       # Pour nettoyer les noms de fichiers (regex)

# ============================================================
# CONFIGURATION — À modifier selon ton installation
# ============================================================

# Ton dossier de ROMs Wii (fichiers .iso ou .wbfs)
ROMS_FOLDER = "/media/matt/Jeux et divers/wii jeux/"

# clés depuis le .env
from dotenv import load_dotenv

load_dotenv() # Charge le fichier .env

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

# Fichier de sortie — le JSON avec toutes les métadonnées
OUTPUT_FILE = "./library.json"

# Extensions de fichiers ROM qu'on accepte
# .iso = image disque standard, .wbfs = format Wii spécifique
ROM_EXTENSIONS = [".iso", ".wbfs"]


# ============================================================
# ÉTAPE 1 — Obtenir un token d'accès Twitch
# ============================================================
# IGDB exige un token temporaire pour chaque session.
# Ce token dure environ 60 jours, puis il faut en redemander un.
# Doc Twitch OAuth : https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/

def get_twitch_token(client_id, client_secret):
    """
    Demande un token d'accès à Twitch.
    Retourne le token sous forme de string.
    """

    # L'URL du serveur d'authentification Twitch
    url = "https://id.twitch.tv/oauth2/token"

    # Les paramètres qu'on envoie (comme un formulaire)
    # grant_type="client_credentials" = on s'authentifie en tant qu'app (pas un user)
    params = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials"
    }

    # On envoie la requête POST (comme soumettre un formulaire)
    response = requests.post(url, params=params)

    # Si la requête a échoué (mauvaises clés, réseau...), on arrête tout
    # raise_for_status() lève une exception si le code HTTP n'est pas 200
    response.raise_for_status()

    # La réponse est en JSON, on extrait juste le token
    # Exemple de réponse : {"access_token": "abc123", "expires_in": 5183944, ...}
    token = response.json()["access_token"]

    print(f"[OK] Token Twitch obtenu : {token[:10]}...") # On affiche que le début pour pas exposer le token
    return token


# ============================================================
# ÉTAPE 2 — Lire le dossier de ROMs
# ============================================================

def scan_roms_folder(folder_path):
    """
    Parcourt le dossier et retourne la liste des ROMs trouvés.
    Chaque entrée est un dict avec le nom et le chemin du fichier.
    """

    roms = [] # Liste vide qu'on va remplir

    # os.listdir() retourne tous les fichiers d'un dossier
    # Doc : https://docs.python.org/3/library/os.html#os.listdir
    for filename in os.listdir(folder_path):

        # os.path.splitext() sépare le nom de l'extension
        # Ex: "Rayman.iso" → ("Rayman", ".iso")
        name, ext = os.path.splitext(filename)

        # On ignore les fichiers qui ne sont pas des ROMs
        if ext.lower() not in ROM_EXTENSIONS:
            continue # "continue" passe directement à l'itération suivante

        # On nettoie le nom pour la recherche IGDB
        # Les noms de fichiers ont souvent des underscores ou des points
        # Ex: "Rayman_Raving_Rabbids" → "Rayman Raving Rabbids"
        clean_name = clean_rom_name(filename)

        roms.append({
            "filename": filename,           # Nom complet du fichier
            "filepath": os.path.join(folder_path, filename), # Chemin absolu
            "search_name": clean_name,      # Nom nettoyé pour la recherche
        })

        print(f"[INFO] ROM trouvé : {filename} → recherche : '{clean_name}'")

    print(f"\n[INFO] Total : {len(roms)} ROM(s) trouvé(s)\n")
    return roms


# ============================================================
# ÉTAPE 3 — Chercher un jeu sur IGDB
# ============================================================
# Doc IGDB API : https://api-docs.igdb.com/
# IGDB utilise un langage de requête custom appelé "Apicalypse"
# C'est comme du SQL mais pour leur API

def search_game_on_igdb(game_name, client_id, token):
    """
    Cherche un jeu sur IGDB par son nom.
    Retourne les métadonnées du premier résultat, ou None si pas trouvé.
    """

    url = "https://api.igdb.com/v4/games"

    # Les headers HTTP identifient notre app auprès d'IGDB
    headers = {
        "Client-ID": client_id,          # Notre identifiant app Twitch
        "Authorization": f"Bearer {token}" # Le token qu'on a obtenu à l'étape 1
        # "Bearer" = type d'authentification standard (porteur du token)
    }

    # La requête Apicalypse — c'est le "body" qu'on envoie
    # fields = les colonnes qu'on veut récupérer (comme SELECT en SQL)
    # search = le nom du jeu à chercher
    # where = filtre : platform 5 = Nintendo Wii sur IGDB
    #   (liste des IDs de plateformes : https://api-docs.igdb.com/#platform)
    # limit = on veut juste le meilleur résultat
    query = f"""
        fields name, summary, cover.image_id, genres.name, 
               first_release_date, involved_companies.company.name,
               game_modes.name, rating;
        search "{game_name}";
        where platforms = (5);
        limit 1;
    """
    # Note : on pourrait enlever "where platforms = (5)" pour chercher sur toutes
    # les plateformes, mais on risque d'avoir des résultats d'autres consoles

    # On envoie la requête POST avec notre query dans le body
    response = requests.post(url, headers=headers, data=query)
    response.raise_for_status()

    results = response.json()

    # Si IGDB n'a rien trouvé, results sera une liste vide []
    if not results:
        print(f"  [WARN]  Aucun résultat pour '{game_name}'")
        return None

    # On prend le premier résultat (le plus pertinent selon IGDB)
    game = results[0]
    print(f"  [OK] Trouvé : {game['name']}")
    return game


# ============================================================
# ÉTAPE 4 — Construire l'URL de la cover
# ============================================================
# IGDB ne stocke pas les images directement dans la réponse JSON.
# Il donne juste un "image_id", et on construit l'URL nous-mêmes.
# Doc images IGDB : https://api-docs.igdb.com/#images

def build_cover_url(image_id, size="cover_big"):
    """
    Construit l'URL de la cover à partir de l'image_id IGDB.
    
    Tailles disponibles :
    - "cover_small"  : 90x128
    - "cover_big"    : 264x374  ← bon compromis qualité/poids
    - "720p"         : 1280x720
    - "1080p"        : 1920x1080
    """
    if not image_id:
        return None

    # Format de l'URL IGDB pour les images
    return f"https://images.igdb.com/igdb/image/upload/t_{size}/{image_id}.jpg"


# ============================================================
# ÉTAPE 5 — Assembler tout et générer le JSON
# ============================================================

def build_library(roms_folder, client_id, client_secret):
    """
    Fonction principale :
    1. Obtient le token Twitch
    2. Scanne le dossier de ROMs
    3. Cherche chaque jeu sur IGDB
    4. Écrit le fichier library.json
    """

    # --- Authentification ---
    print("[INFO] Authentification Twitch...")
    token = get_twitch_token(client_id, client_secret)

    # --- Scan des ROMs ---
    print(f"\n[INFO] Scan du dossier : {roms_folder}")
    roms = scan_roms_folder(roms_folder)

    if not roms:
        print("[ERROR] Aucun ROM trouvé. Vérifie le chemin ROMS_FOLDER.")
        return

    # --- Enrichissement IGDB ---
    library = [] # La liste finale qu'on va écrire en JSON

    print("[INFO] Recherche des métadonnées sur IGDB...\n")

    for rom in roms:
        print(f"[INFO] Traitement : {rom['filename']}")

        # On cherche le jeu sur IGDB
        game_data = search_game_on_igdb(rom["search_name"], client_id, token)

        if game_data:
            # On récupère l'image_id de la cover (peut ne pas exister)
            # .get() est plus sûr que [] — retourne None si la clé n'existe pas
            cover_image_id = game_data.get("cover", {}).get("image_id")

            # On assemble toutes les infos dans un dict propre
            entry = {
                # Infos du fichier local
                "filename": rom["filename"],
                "filepath": rom["filepath"],

                # Infos IGDB
                "igdb_id": game_data.get("id"),
                "title": game_data.get("name", rom["search_name"]),
                "summary": game_data.get("summary", "Aucune description disponible."),
                "cover_url": build_cover_url(cover_image_id),

                # Les genres sont une liste d'objets {"name": "..."}, on extrait juste les noms
                # C'est une "list comprehension" — équivalent d'une boucle for compacte
                "genres": [g["name"] for g in game_data.get("genres", [])],

                # Idem pour les modes de jeu (solo, multijoueur...)
                "game_modes": [m["name"] for m in game_data.get("game_modes", [])],

                # La date de sortie est un timestamp Unix (secondes depuis 1970)
                # On la garde brute pour l'instant, on la formattera plus tard
                "release_timestamp": game_data.get("first_release_date"),

                # Note IGDB sur 100
                "rating": round(game_data.get("rating", 0), 1),
            }
        else:
            # Jeu pas trouvé sur IGDB — on garde quand même une entrée minimale
            entry = {
                "filename": rom["filename"],
                "filepath": rom["filepath"],
                "igdb_id": None,
                "title": rom["search_name"],
                "summary": "Métadonnées non trouvées.",
                "cover_url": None,
                "genres": [],
                "game_modes": [],
                "release_timestamp": None,
                "rating": 0,
            }

        library.append(entry)
        print() # Ligne vide pour lisibilité

    # --- Écriture du JSON ---
    # json.dump() écrit un dict Python en JSON dans un fichier
    # indent=2 = indentation de 2 espaces pour que ce soit lisible
    # ensure_ascii=False = garde les accents et caractères spéciaux
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(library, f, indent=2, ensure_ascii=False)

    print(f"[OK] Bibliothèque générée : {OUTPUT_FILE}")
    print(f"   {len(library)} jeu(x) indexé(s)")

def clean_rom_name(filename):
    name, _ = os.path.splitext(filename)
    
    # Supprime tout ce qui est entre parenthèses : (USA) (En,Fr,Es) (Rev 2)
    name = re.sub(r'\(.*?\)', '', name)
    
    # Supprime tout ce qui est entre crochets : [PAL] [MULTi5] [WII GAME - ITA]
    name = re.sub(r'\[.*?\]', '', name)
    
    # Supprime les extensions résiduelles genre .nkit
    name = re.sub(r'\.nkit', '', name, flags=re.IGNORECASE)
    
    # Remplace underscores et points par des espaces
    name = name.replace('_', ' ').replace('.', ' ')
    
    # Supprime les espaces multiples
    name = re.sub(r'\s+', ' ', name).strip()
    
    return name


# ============================================================
# Point d'entrée du script
# ============================================================
# Ce bloc s'exécute SEULEMENT si on lance ce fichier directement
# (pas si on l'importe depuis un autre script)
# C'est une convention Python standard

if __name__ == "__main__":
    build_library(ROMS_FOLDER, TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET)
