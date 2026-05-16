#!/usr/bin/env python3
"""
Script one-time pour obtenir le YouTube refresh_token.
Lance ce script UNE SEULE FOIS sur ton Mac, copie le refresh_token,
puis mets-le dans les secrets GitHub.
"""

import json
import requests

# ─── Remplis ces 2 valeurs (depuis Google Cloud Console) ──────────────────────
CLIENT_ID     = "COLLE_ICI_TON_CLIENT_ID"
CLIENT_SECRET = "COLLE_ICI_TON_CLIENT_SECRET"
# ──────────────────────────────────────────────────────────────────────────────

SCOPE = "https://www.googleapis.com/auth/youtube.upload"

# Étape 1 : Obtenir un device code
r = requests.post("https://oauth2.googleapis.com/device/code", data={
    "client_id": CLIENT_ID,
    "scope": SCOPE
})
r.raise_for_status()
data = r.json()

print("\n" + "═" * 60)
print("1. Ouvre ce lien dans ton navigateur :")
print(f"   {data['verification_url']}")
print(f"\n2. Entre ce code : {data['user_code']}")
print("═" * 60)
input("\n3. Appuie sur Entrée APRÈS avoir autorisé dans le navigateur...")

# Étape 2 : Échanger contre les tokens
r2 = requests.post("https://oauth2.googleapis.com/token", data={
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "device_code": data["device_code"],
    "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
})

if r2.status_code != 200:
    print(f"❌ Erreur : {r2.text}")
    exit(1)

tokens = r2.json()
refresh_token = tokens.get("refresh_token")

if not refresh_token:
    print("❌ Pas de refresh_token reçu. Réessaie depuis le début.")
    exit(1)

print("\n✅ Succès ! Voici ton refresh_token à copier dans GitHub Secrets :\n")
print("─" * 60)
print(refresh_token)
print("─" * 60)
print("\nNom du secret GitHub : YOUTUBE_REFRESH_TOKEN")
