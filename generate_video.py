#!/usr/bin/env python3
"""
Pipeline automatique : YouTube Shorts tech/IA en français
HackerNews → Groq (script) → Pexels (multi-clips) → Edge-TTS (voix neuronale)
→ Sous-titres incrustés → FFmpeg → YouTube
5 Shorts/jour, 100% gratuit, anti-doublons.
"""

import os
import json
import math
import random
import asyncio
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import edge_tts
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

# ─── Configuration (GitHub Secrets) ───────────────────────────────────────────
GROQ_API_KEY          = os.environ["GROQ_API_KEY"]
PEXELS_API_KEY        = os.environ["PEXELS_API_KEY"]
YOUTUBE_CLIENT_ID     = os.environ["YOUTUBE_CLIENT_ID"]
YOUTUBE_CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
YOUTUBE_REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]

# ─── Constantes ───────────────────────────────────────────────────────────────
HISTORY_FILE = Path("history.json")
HISTORY_LOOKBACK = 60   # Vérifie les 60 derniers Shorts pour éviter doublons
CLIP_DURATION = 5.5     # Secondes par clip de fond
MAX_CLIPS = 12          # Maximum de clips Pexels à télécharger

# Voix Edge-TTS françaises (alternance pour variété)
VOICES = [
    "fr-FR-DeniseNeural",  # Femme, naturelle, dynamique
    "fr-FR-HenriNeural",   # Homme, énergique
    "fr-FR-EloiseNeural",  # Femme, jeune
]


# ─── Utilitaires : retry HTTP avec backoff ────────────────────────────────────
def request_with_retry(method, url, max_attempts=3, **kwargs):
    """Appel HTTP avec retry exponentiel sur erreurs réseau/5xx."""
    last_exc = None
    for attempt in range(max_attempts):
        try:
            r = requests.request(method, url, timeout=kwargs.pop("timeout", 30), **kwargs)
            if r.status_code >= 500:
                raise requests.HTTPError(f"Server error {r.status_code}")
            r.raise_for_status()
            return r
        except (requests.RequestException, requests.HTTPError) as e:
            last_exc = e
            wait = 2 ** attempt
            print(f"   ⚠️ Tentative {attempt+1}/{max_attempts} échouée ({e}), retry dans {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"Échec après {max_attempts} tentatives : {last_exc}")


# ─── Historique : anti-doublons ───────────────────────────────────────────────
def load_history():
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_history(entry):
    history = load_history()
    history.append(entry)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📚 Historique mis à jour : {len(history)} Shorts enregistrés")


def recent_topics_list():
    """Renvoie une chaîne avec les titres récents pour le prompt anti-doublons."""
    history = load_history()
    recents = history[-HISTORY_LOOKBACK:]
    if not recents:
        return ""
    return "\n".join(f"- {h.get('titre', '')}" for h in recents)


# ─── Étape 0 : Actualité tech HackerNews ──────────────────────────────────────
def get_tech_news():
    print("📰 Récupération HackerNews...")
    try:
        ids = request_with_retry("GET",
            "https://hacker-news.firebaseio.com/v0/topstories.json"
        ).json()[:40]

        titres = []
        for story_id in random.sample(ids, min(20, len(ids))):
            try:
                item = requests.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                    timeout=5
                ).json()
                if item and item.get("title") and item.get("score", 0) >= 50:
                    titres.append(f"- {item['title']} (score: {item['score']})")
            except Exception:
                continue

        if titres:
            print(f"✅ {len(titres)} actualités récupérées")
            return "\n".join(titres[:15])
    except Exception as e:
        print(f"⚠️ HackerNews inaccessible ({e})")
    return None


# ─── Étape 1 : Génération du script via Groq ──────────────────────────────────
def generate_script():
    print("📝 Génération du script (Groq)...")
    news = get_tech_news()
    deja_traites = recent_topics_list()

    anti_doublon = ""
    if deja_traites:
        anti_doublon = (
            "\n\n⚠️ SUJETS DÉJÀ TRAITÉS RÉCEMMENT — INTERDIT DE LES REPRENDRE :\n"
            f"{deja_traites}\n"
            "Choisis OBLIGATOIREMENT un angle complètement différent.\n"
        )

    if news:
        sujet_instructions = (
            "Voici les actualités tech les plus populaires du moment sur HackerNews :\n"
            f"{news}\n\n"
            "Choisis l'actualité la plus VIRALE et SURPRENANTE pour un public francophone. "
            "Adapte-la en expliquant le contexte, en gardant un angle 'wow factor'. "
        )
    else:
        sujet_instructions = (
            "Choisis un sujet tech ou IA original — "
            "évite ChatGPT, robots, voitures autonomes, blockchain. "
        )

    sujet_instructions += anti_doublon

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Tu es un créateur de YouTube Shorts viral spécialisé tech et IA. "
                    "Ton style : direct, percutant, dynamique. "
                    "Tu parles toujours en français."
                )
            },
            {
                "role": "user",
                "content": (
                    f"{sujet_instructions}"
                    "Génère un script de YouTube Short en français. "
                    "Durée cible : 45-55 secondes (≈ 120-140 mots). "
                    "Structure : 1) ACCROCHE choc (5 sec), "
                    "2) DÉVELOPPEMENT avec exemples et chiffres (35 sec), "
                    "3) CONCLUSION + appel à l'action (10-15 sec). "
                    "Texte en UN SEUL bloc continu SANS retours à la ligne, "
                    "SANS guillemets doubles, uniquement virgules et points. "
                    'Réponds UNIQUEMENT avec un JSON valide : '
                    '{"titre": "titre 50 caractères max avec 1 emoji au début et #Shorts à la fin", '
                    '"sujet": "2-3 mots-clés anglais pour Pexels (ex: technology circuit)", '
                    '"sujets_alt": "3 autres requêtes anglaises Pexels séparées par virgules pour avoir des clips variés", '
                    '"script": "120-140 mots en un paragraphe sans retour à la ligne", '
                    '"description": "description longue 400-500 caractères avec mots-clés SEO et emojis", '
                    '"tags": "10 tags séparés par virgules dont Shorts et Tech"}'
                )
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.7,
        "max_tokens": 1200
    }

    r = request_with_retry("POST",
        "https://api.groq.com/openai/v1/chat/completions",
        max_attempts=3,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=60
    )
    data = json.loads(r.json()["choices"][0]["message"]["content"])
    print(f"✅ Script généré : « {data['titre']} »")
    return data


# ─── Étape 2 : Récupérer plusieurs clips Pexels variés ────────────────────────
def search_pexels(query, per_page=5):
    """Une recherche Pexels (portrait prioritaire, fallback landscape)."""
    for orientation in ("portrait", "landscape"):
        try:
            r = request_with_retry("GET",
                "https://api.pexels.com/videos/search",
                max_attempts=2,
                headers={"Authorization": PEXELS_API_KEY},
                params={"query": query, "per_page": per_page,
                        "orientation": orientation, "size": "medium"},
                timeout=20
            )
            videos = r.json().get("videos", [])
            if videos:
                return videos, orientation
        except Exception as e:
            print(f"   ⚠️ Pexels {orientation} '{query}': {e}")
    return [], None


def collect_clip_urls(content, target_count):
    """Récupère plusieurs vidéos Pexels variées."""
    queries = [content["sujet"]]
    if content.get("sujets_alt"):
        queries += [q.strip() for q in content["sujets_alt"].split(",") if q.strip()]
    queries += ["technology", "abstract data", "futuristic"]  # Fallbacks génériques

    urls_seen = set()
    clip_urls = []
    for q in queries:
        if len(clip_urls) >= target_count:
            break
        videos, _ = search_pexels(q, per_page=8)
        for video in videos:
            if len(clip_urls) >= target_count:
                break
            files = sorted(
                [f for f in video["video_files"] if f.get("height", 0) >= 480],
                key=lambda x: x.get("height", 0), reverse=True
            )
            if not files:
                continue
            link = files[0]["link"]
            if link in urls_seen:
                continue
            urls_seen.add(link)
            clip_urls.append(link)

    if not clip_urls:
        raise RuntimeError("Aucun clip Pexels disponible.")
    print(f"✅ {len(clip_urls)} clips trouvés")
    return clip_urls


def download_file(url, output_path):
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)


# ─── Étape 3 : Voix off Edge-TTS (neuronale, gratuite) ────────────────────────
async def _edge_tts_async(text, voice, output):
    communicate = edge_tts.Communicate(text, voice, rate="+5%")
    await communicate.save(output)


def generate_tts(script):
    voice = random.choice(VOICES)
    print(f"🎙️ Voix neuronale Edge-TTS ({voice})...")
    asyncio.run(_edge_tts_async(script, voice, "audio.mp3"))
    size = Path("audio.mp3").stat().st_size
    print(f"✅ Audio généré : {size / 1024:.0f} KB")


# ─── Étape 4 : Génération SRT depuis le script ────────────────────────────────
def format_srt_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def generate_srt(script, audio_duration, words_per_caption=3):
    """Découpe le script en sous-titres courts, durées proportionnelles."""
    words = script.replace("\n", " ").split()
    chunks = [" ".join(words[i:i + words_per_caption])
              for i in range(0, len(words), words_per_caption)]

    total_chars = sum(len(c) for c in chunks) or 1
    cumul = 0.0
    lines = []
    for idx, chunk in enumerate(chunks, start=1):
        share = len(chunk) / total_chars
        dur = max(0.6, share * audio_duration)
        start = cumul
        end = min(cumul + dur, audio_duration)
        cumul = end
        lines.append(f"{idx}\n{format_srt_time(start)} --> {format_srt_time(end)}\n{chunk}\n")

    Path("subs.srt").write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ Sous-titres générés ({len(chunks)} blocs)")


# ─── Étape 5 : Assemblage FFmpeg (multi-clips + sous-titres burn-in) ──────────
def get_duration(path):
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True
    )
    return float(probe.stdout.strip())


def normalize_clip(src, dst, duration):
    """Recadre un clip en 1080x1920, force durée fixe, supprime l'audio."""
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920:(iw-1080)/2:(ih-1920)/2,"
        "fps=30,setsar=1"
    )
    subprocess.run([
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", str(src),
        "-an",
        "-t", f"{duration:.2f}",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        str(dst)
    ], check=True, capture_output=True)


def assemble_video(num_clips_downloaded):
    print("🎞️ Assemblage FFmpeg (multi-clips + sous-titres)...")

    audio_duration = min(get_duration("audio.mp3"), 59.0)
    print(f"   Durée audio : {audio_duration:.1f}s")

    # Combien de segments ? Chaque segment ≈ CLIP_DURATION
    n_segments = max(1, math.ceil(audio_duration / CLIP_DURATION))
    seg_duration = audio_duration / n_segments
    print(f"   {n_segments} segments × {seg_duration:.2f}s")

    # Normaliser chaque segment (loop sur clips dispos)
    seg_paths = []
    for i in range(n_segments):
        clip_src = f"clip_{i % num_clips_downloaded:02d}.mp4"
        dst = f"seg_{i:02d}.mp4"
        normalize_clip(clip_src, dst, seg_duration)
        seg_paths.append(dst)

    # Concat list
    with open("concat.txt", "w") as f:
        for p in seg_paths:
            f.write(f"file '{p}'\n")

    # Concaténation vidéo silencieuse
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", "concat.txt", "-c", "copy", "concat.mp4"
    ], check=True, capture_output=True)

    # Style sous-titres ASS (gros, blancs, contour noir épais, centrés bas)
    sub_style = (
        "FontName=Arial,FontSize=18,Bold=1,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        "BorderStyle=1,Outline=4,Shadow=1,"
        "Alignment=2,MarginV=180"
    )
    vf_subs = f"subtitles=subs.srt:force_style='{sub_style}'"

    # Mux final : vidéo concat + audio + sous-titres burn-in
    result = subprocess.run([
        "ffmpeg", "-y",
        "-i", "concat.mp4",
        "-i", "audio.mp3",
        "-vf", vf_subs,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{audio_duration:.2f}",
        "-movflags", "+faststart",
        "-shortest",
        "output.mp4"
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(result.stderr[-2000:])
        raise RuntimeError("FFmpeg a échoué")

    size = Path("output.mp4").stat().st_size
    print(f"✅ Short assemblé : {size / 1024 / 1024:.1f} MB, {audio_duration:.0f}s")
    return audio_duration


# ─── Étape 6 : Upload YouTube Shorts ──────────────────────────────────────────
def upload_to_youtube(titre, description, tags):
    print("📤 Upload YouTube...")

    r = request_with_retry("POST",
        "https://oauth2.googleapis.com/token",
        max_attempts=3,
        data={
            "client_id": YOUTUBE_CLIENT_ID,
            "client_secret": YOUTUBE_CLIENT_SECRET,
            "refresh_token": YOUTUBE_REFRESH_TOKEN,
            "grant_type": "refresh_token"
        }
    )
    access_token = r.json()["access_token"]

    creds = Credentials(token=access_token)
    youtube = build("youtube", "v3", credentials=creds)

    tags_list = [t.strip() for t in tags.split(",") if t.strip()]
    for t in ("Shorts", "Tech", "IA"):
        if t not in tags_list:
            tags_list.append(t)

    # Garantir #Shorts dans le titre (boost détection)
    titre_final = titre if "#Shorts" in titre else f"{titre} #Shorts"
    titre_final = titre_final[:100]

    # Description longue avec SEO
    description_full = (
        f"{description}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 Plus de Shorts tech et IA chaque jour !\n"
        "👍 Like et abonne-toi pour ne rien rater.\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "#Shorts #Tech #IA #IntelligenceArtificielle #Innovation #Technologie "
        "#Futur #Sciences #Numerique #Digital"
    )

    media = MediaFileUpload("output.mp4", mimetype="video/mp4",
                            resumable=True, chunksize=5 * 1024 * 1024)
    body = {
        "snippet": {
            "title": titre_final,
            "description": description_full,
            "tags": tags_list,
            "categoryId": "28",  # Science & Technology
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

    # Multi-clips Pexels
    clip_urls = collect_clip_urls(content, target_count=MAX_CLIPS)
    for i, url in enumerate(clip_urls):
        download_file(url, f"clip_{i:02d}.mp4")
    print(f"✅ {len(clip_urls)} clips téléchargés")

    # Voix neuronale
    generate_tts(content["script"])

    # Sous-titres
    audio_dur = min(get_duration("audio.mp3"), 59.0)
    generate_srt(content["script"], audio_dur)

    # Assemblage
    duration = assemble_video(len(clip_urls))

    # Upload
    video_id = upload_to_youtube(content["titre"], content["description"], content["tags"])

    # Historique
    save_history({
        "date": datetime.now(timezone.utc).isoformat(),
        "video_id": video_id,
        "titre": content["titre"],
        "sujet": content["sujet"],
        "duree": round(duration, 1),
        "url": f"https://youtube.com/shorts/{video_id}"
    })

    print(f"\n🎉 Short publié avec succès !")
    print(f"   Titre  : {content['titre']}")
    print(f"   Durée  : {duration:.0f}s")
    print(f"   URL    : https://youtube.com/shorts/{video_id}")


if __name__ == "__main__":
    main()
