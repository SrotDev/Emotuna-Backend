import os
import django
import sys
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from ingestion.agent_workflow import agent_generate_reply


sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'emotuna.settings')
django.setup()
load_dotenv()


TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
RL_LOG_PATH = os.path.join(os.path.dirname(__file__), 'rl_feedback_log.csv')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I'm your AI auto-reply bot.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    print(f"User message:\n{user_message}\n")
    ai_reply = agent_generate_reply(user_message)
    print(f"\nAI-generated reply:\n{ai_reply}\n")
    score = int(input("Score the reply (0-100): "))
    edited_reply = input("Edit the reply if needed (leave blank to keep as is): ")
    final_reply = edited_reply if edited_reply.strip() else ai_reply

    # Log the interaction for RL (append to a file for now)
    with open(RL_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f'"{user_message}","{ai_reply}",{score},"{final_reply}"\n')

    await update.message.reply_text(final_reply)

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()