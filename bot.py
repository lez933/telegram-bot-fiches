from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import os

TOKEN = os.getenv("BOT_TOKEN")  # tu dois avoir ton token dans Render → Environment

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "👋 Bienvenue dans ton bot !\n\n"
        "Voici les commandes disponibles :\n"
        "/start - Afficher ce message\n"
        "/help - Aide\n"
    )
    await update.message.reply_text(message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ℹ️ Utilise /start pour voir les options disponibles.")

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    print("✅ Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
