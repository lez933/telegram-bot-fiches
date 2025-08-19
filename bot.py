import os
import json
import aiohttp
import asyncio
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# 🔑 Mets ton token ici
TOKEN = os.getenv("BOT_TOKEN", "TON_TOKEN_ICI")

# ===== Fonction de conversion JSON → fiches TXT =====
def json_to_fiches(data):
    fiches = []
    for i, item in enumerate(data, start=1):
        fiche = []
        fiche.append(f"FICHE {i}")
        fiche.append("-" * 60)

        fiche.append(f"Civilité: {item.get('civilite', '')}")
        fiche.append(f"Prénom: {item.get('prenom', item.get('first_name', ''))}")
        fiche.append(f"Nom: {item.get('nom', item.get('last_name', ''))}")
        fiche.append(f"Date de naissance: {item.get('date_naissance', item.get('dob', ''))}")
        fiche.append(f"Email: {item.get('email', '')}")
        fiche.append(f"Mobile: {item.get('mobile', item.get('phone', ''))}")
        fiche.append(f"Téléphone Fixe: {item.get('fixe', '')}")
        fiche.append(f"Adresse: {item.get('adresse', item.get('address', ''))}")
        fiche.append(f"Ville: {item.get('ville', item.get('city', ''))}")
        fiche.append(f"Code Postal: {item.get('cp', item.get('zipcode', ''))}")
        fiche.append(f"Région: {item.get('region', '')}")
        fiche.append(f"IBAN: {item.get('iban', '')}")
        fiche.append(f"BIC: {item.get('bic', '')}")
        fiche.append("-" * 60 + "\n")

        fiches.append("\n".join(fiche))

    return "\n".join(fiches)


# ===== Commande /start =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Envoie-moi un fichier .json (ou un lien avec /importurl) et je te renverrai un .txt formaté en fiches."
    )


# ===== Commande /importurl =====
async def importurl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Utilisation: /importurl <url>")
        return

    url = context.args[0]
    await update.message.reply_text("⬇️ Téléchargement du fichier en cours...")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    await update.message.reply_text("❌ Erreur de téléchargement.")
                    return
                content = await resp.text()

        data = json.loads(content)
        fiches_txt = json_to_fiches(data)

        # Sauvegarde temporaire
        filename = "fiches.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(fiches_txt)

        await update.message.reply_document(InputFile(filename))
        os.remove(filename)

    except Exception as e:
        await update.message.reply_text(f"⚠️ Erreur: {e}")


# ===== Gestion des fichiers envoyés =====
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    await update.message.reply_text("⬇️ Téléchargement du fichier en cours...")

    try:
        file_path = "uploaded.json"
        await file.download_to_drive(file_path)

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        fiches_txt = json_to_fiches(data)

        # Sauvegarde temporaire
        filename = "fiches.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(fiches_txt)

        await update.message.reply_document(InputFile(filename))
        os.remove(filename)
        os.remove(file_path)

    except Exception as e:
        await update.message.reply_text(f"⚠️ Erreur: {e}")


# ===== Main =====
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("importurl", importurl))
    app.add_handler(MessageHandler(filters.Document.FileExtension("json"), handle_file))

    print("🤖 Bot en ligne...")
    app.run_polling()


if __name__ == "__main__":
    main()
