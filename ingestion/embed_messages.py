import os
import django
import sys
from dotenv import load_dotenv
from chat.models import ChatMessage
from ingestion.tidb_vector_utils import TiDBVectorDB
from sentence_transformers import SentenceTransformer
import numpy as np


sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'emotuna.settings')
django.setup()
load_dotenv()


# Load a sentence transformer model (CPU is fine for small data)
model = SentenceTransformer('all-MiniLM-L6-v2')

def main():
    db = TiDBVectorDB()
    db.create_table()
    messages = ChatMessage.objects.all()
    for msg in messages:
        print(f"Embedding: {msg.id} | {msg.message}")
        emb = model.encode(msg.message, show_progress_bar=False, convert_to_numpy=True)
        reply_emb = None
        if msg.reply_message:
            print(f"Embedding reply: {msg.reply_message}")
            reply_emb = model.encode(msg.reply_message, show_progress_bar=False, convert_to_numpy=True)
        db.insert_embedding(
            str(msg.id),
            msg.user_id,
            msg.message,
            emb.astype(np.float32),
            msg.reply_message,
            reply_emb.astype(np.float32) if reply_emb is not None else None
        )
    db.close()
    print("Embeddings stored in TiDB.")

if __name__ == "__main__":
    main()
