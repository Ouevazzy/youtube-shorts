#!/usr/bin/env python3
"""
Pipeline automatique : YouTube Shorts tech/IA en français
Groq (script) → Pexels (vidéo portrait) → edge-tts (voix gratuite) → FFmpeg → YouTube
5 Shorts par jour, 100% gratuit
"""

import os
import json
import asyncio
import subprocess
import requests
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
import edge_tts

# ─── Configuration (GitHub Secrets) ───────────────────────────────────────────
GROQ_API_KEY          = os.environ["GROQ_API_KEY"]
PEXELS_API_KEY        = os.environ["PEXELS_API_KEY"]
YOUTUBE_CLIENT_ID     = os.environ["YOUTUBE_CLIENT_ID"]
YOUTUBE_CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
YOUTUBE_REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]

# Voix française masculine Microsoft Edge — gratuite et illimitée
VOICE = "fr-FR-HenriNeural"


# ─── Étape 1 : Générer le script avec Groq ────────────────────────────────────
def generate_script():
    print("📝 Génération du script avec Groq...")
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Tu es un créateur de YouTube Shorts viral spécialisé tech et IA. "
                        "Tu maîtrises l'art de l'accroche choc, du fait surprenant et du hook irrésistible. "
                        "Ton style est direct, percutant, dynamique — comme un mini-documentaire de 60 secondes."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        "Génère un script de YouTube Short en français sur un fait fascinant et peu connu lié à la tech ou l'IA. "
                        "Durée cible : 50-55 secondes à l'oral (environ 130-140 mots). "
                        "Structure obligatoire : "
                        "1) ACCROCHE (5 sec) : phrase choc qui donne envie de rester, "
                        "2) DÉVELOPPEMENT (35 sec) : le fait avec des exemples concrets et chiffres, "
                        "3) CONCLUSION (15 sec) : retournement ou fait encore plus surprenant + appel à l'action. "
                        "CONTRAINTES ABSOLUES : script en UN SEUL bloc de texte continu SANS retours à la ligne, "
                        "SANS guillemets doubles, uniquement virgules et points pour les pauses naturelles. "
                        "Choisis un sujet ORIGINAL — évite ChatGPT, robots, voitures autonomes, blockchain. "
                        "Exemples de bons sujets : algorithmes de recommandation, mémoire des ordinateurs, "
                        "bugs célèbres, histoire de l'internet, cryptographie, vision par ordinateur, etc. "
                        'Réponds UNIQUEMENT avec un JSON valide sans markdown ni backticks : '
                        '{"titre": "titre accrocheur max 50 caractères avec 1 emoji au début", '
                        '"sujet": "2-3 mots-clés anglais pour chercher une vidéo sur Pexels (ex: technology circuit, space science, data network)", '
                        '"script": "130-140 mots en un seul paragraphe sans retour à la ligne", '
                        '"description": "description YouTube 120 caractères avec emoji", '
                        '"tags": "8 tags séparés par virgules dont Shorts et Tech"}'
                    )
                }
            ],
            "response_format": {"type": "json_object"},
            "temperature": 1.0,
            "max_tokens": 1000
        }
    )
    resp.raise_for_status()
    data = json.loads(resp.json()["choices"][0]["message"]["content"])
    print(f"✅ Script généré : « {data['titre']} »")
    return data


# ─── Étape 2 : Trouver une vidéo Pexels (portrait de préférence) ──────────────
def get_pexels_video(sujet):
    print(f"🎬 Recherche vidéo Pexels : {sujet}")

    # Essai 1 : portrait natif (idéal pour Shorts)
    resp = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": PEXELS_API_KEY},
        params={"query": sujet, "per_page": 10, "orientation": "portrait", "size": "medium"}
    )
    resp.raise_for_status()
    videos = resp.json().get("videos", [])

    # Fallback : landscape (FFmpeg recadrera en vertical)
    if not videos:
        print("   Pas de portrait trouvé, fallback landscape...")
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": sujet, "per_page": 5, "orientation": "landscape", "size": "medium"}
        )
        resp.raise_for_status()
        videos = resp.json().get("videos", [])

    if not videos:
        raise RuntimeError(f"Aucune vidéo trouvée pour : {sujet}")

    # Prendre le meilleur fichier HD disponible
    for video in videos:
        files = sorted(
            [f for f in video["video_files"] if f.get("height", 0) >= 480],
            key=lambda x: x.get("height", 0), reverse=True
        )
        if files:
            f = files[0]
            print(f"✅ Vidéo trouvée ({f['width']}x{f['height']})")
            return f["link"]

    url = videos[0]["video_files"][0]["link"]
    print("✅ Vidéo trouvée (qualité standard)")
    return url


# ─── Étape 3 : Télécharger un fichier ─────────────────────────────────────────
def download_file(url, output_path):
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)
    size = Path(output_path).stat().st_size
    print(f"✅ Téléchargé : {output_path} ({size / 1024 / 1024:.1f} MB)")


# ─── Étape 4 : Générer la voix off avec edge-tts (gratuit, illimité) ──────────
async def _tts_async(script: str):
    communicate = edge_tts.Communicate(script, VOICE, rate="+5%")
    await communicate.save("audio.mp3")

def generate_tts(script):
    print("🎙️ Génération voix off edge-tts (fr-FR-HenriNeural)...")
    asyncio.run(_tts_async(script))
    size = Path("audio.mp3").stat().st_size
    print(f"✅ Audio généré : {size / 1024:.0f} KB")


# ─── Étape 5 : Assembler en format Short 1080x1920 ────────────────────────────
def assemble_video():
    print("🎞️ Assemblage FFmpeg (Short vertical 1080x1920)...")

    # Durée exacte de l'audio
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", "audio.mp3"],
        capture_output=True, text=True, check=True
    )
    duration = float(probe.stdout.strip())
    duration = min(duration, 59.0)  # YouTube Shorts : max 59 secondes
    print(f"   Durée : {duration:.1f}s")

    # Filtre universel portrait : scale pour couvrir 1080x1920, crop centré
    # Fonctionne pour les vidéos portrait ET landscape
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920:(iw-1080)/2:(ih-1920)/2"
    )

    result = subprocess.run([
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", "video.mp4",
        "-i", "audio.mp3",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-vf", vf,
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        "-movflags", "+faststart",
        "output.mp4"
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(result.stderr[-2000:])
        raise RuntimeError("FFmpeg a échoué")

    size = Path("output.mp4").stat().st_size
    print(f"✅ Short assemblé : {size / 1024 / 1024:.1f} MB, {duration:.0f}s")
    return duration


# ─── Étape 6 : Upload YouTube Shorts ──────────────────────────────────────────
def upload_to_youtube(titre, description, tags):
    print("📤 Upload YouTube Shorts...")

    # Obtenir un access token frais via le refresh token
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": YOUTUBE_CLIENT_ID,
        "client_secret": YOUTUBE_CLIENT_SECRET,
        "refresh_token": YOUTUBE_REFRESH_TOKEN,
        "grant_type": "refresh_token"
    })
    r.raise_for_status()
    access_token = r.json()["access_token"]

    creds = Credentials(token=access_token)
    youtube = build("youtube", "v3", credentials=creds)

    tags_list = [t.strip() for t in tags.split(",") if t.strip()]
    if "Shorts" not in tags_list:
        tags_list.append("Shorts")

    # YouTube détecte automatiquement les Shorts : format vertical + durée ≤ 60s
    media = MediaFileUpload("output.mp4", mimetype="video/mp4", resumable=True, chunksize=5 * 1024 * 1024)
    body = {
        "snippet": {
            "title": titre[:100],
            "description": f"{description}\n\n#Shorts #Tech #IA #Intelligence_Artificielle",
            "tags": tags_list,
            "categoryId": "28",
            "defaultLanguage": "fr",
            "defaultAudioLanguage": "fr"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True
        }
    }

    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"   Upload : {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"✅ Short publié : https://youtube.com/shorts/{video_id}")
    return video_id


# ─── Pipeline principal ────────────────────────────────────────────────────────
def main():
    print("🚀 Pipeline YouTube Shorts — Démarrage\n")

    content = generate_script()

    video_url = get_pexels_video(content["sujet"])
    download_file(video_url, "video.mp4")

    generate_tts(content["script"])

    duration = assemble_video()

    video_id = upload_to_youtube(content["titre"], content["description"], content["tags"])

    print(f"\n🎉 Short publié avec succès !")
    print(f"   Titre  : {content['titre']}")
    print(f"   Durée  : {duration:.0f}s")
    print(f"   URL    : https://youtube.com/shorts/{video_id}")


if __name__ == "__main__":
    main()
