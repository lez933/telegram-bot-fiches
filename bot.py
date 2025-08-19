from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os

TOKEN = os.getenv("BOT_TOKEN")  # Render → Environment → ajoute BOT_TOKEN = ton token

# Commande /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "📋 **Tableau de Configurations** 📋\n\n"
        "╔══════════════════════╗\n"
        "║  Commande   │ Action ║\n"
        "╠══════════════════════╣\n"
        "║ /start      │ Accueil║\n"
        "║ /help       │ Aide   ║\n"
        "║ /config     │ Voir cfg║\n"
        "║ /about      │ Infos  ║\n"
        "╚══════════════════════╝\n"
    )
    await update.message.reply_text(message, parse_mode="Markdown")

# Commande /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ℹ️ Utilise /start pour voir le tableau des commandes.")

# Commande /config
async def config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg_text = (
        "⚙️ **Configuration actuelle :**\n"
        "- Mode: Production\n"
        "- Logs: Activés\n"
        "- Version: v1.0"
    )
    await update.message.reply_text(cfg_text, parse_mode="Markdown")

# Commande /about
async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot développé pour gérer et afficher les configurations.")

# Lancement du bot
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("config", config))
    app.add_handler(CommandHandler("about", about))

    print("✅ Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
