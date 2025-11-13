import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Commande /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Bonjour ! Envoie-moi un fichier texte et je vais le sauvegarder pour toi.")

# Quand un fichier est reçu
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if document:
        file = await document.get_file()
        file_path = f"./{document.file_name}"
        await file.download_to_drive(file_path)
        await update.message.reply_text(f"✅ Fichier enregistré sous {file_path}")

# Commande /list : montre les fichiers enregistrés
async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = [f for f in os.listdir('.') if os.path.isfile(f)]
    if files:
        await update.message.reply_text("📂 Fichiers disponibles :\n" + "\n".join(files))
    else:
        await update.message.reply_text("Aucun fichier trouvé.")

# Commande /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commandes disponibles :\n"
        "/start - Démarrer le bot\n"
        "/help - Afficher cette aide\n"
        "/list - Voir les fichiers enregistrés\n"
    )

# Lancement du bot
def main():
    if not BOT_TOKEN:
        print("❌ Erreur : BOT_TOKEN manquant dans les variables d'environnement.")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("list", list_files))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    print("✅ Bot en ligne et prêt à recevoir des fichiers.")
    app.run_polling()

if __name__ == "__main__":
    main()
