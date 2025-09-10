import os
import django
import sys
from dotenv import load_dotenv
from ingestion.tidb_vector_utils import TiDBVectorDB
from sentence_transformers import SentenceTransformer
import numpy as np


sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'emotuna.settings')
django.setup()
load_dotenv()


# Load the same model used for embedding
model = SentenceTransformer('all-MiniLM-L6-v2')

def cosine_similarity(a, b):
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    return np.dot(a, b)

def find_similar_messages(query, top_n=3):
    db = TiDBVectorDB()
    db.create_table()
    query_emb = model.encode(query, show_progress_bar=False, convert_to_numpy=True).astype(np.float32)
    # Fetch all embeddings and related data
    with db.conn.cursor() as cursor:
        cursor.execute('SELECT id, message, embedding, reply_message FROM message_embeddings')
        rows = cursor.fetchall()
    similarities = []
    for row in rows:
        msg_id, msg_text, emb_bytes, reply_text = row
        if emb_bytes is None:
            continue
        emb = np.frombuffer(emb_bytes, dtype=np.float32)
        sim = cosine_similarity(query_emb, emb)
        similarities.append((sim, msg_text, reply_text))
    similarities.sort(reverse=True, key=lambda x: x[0])
    db.close()
    return similarities[:top_n]

def main():
    query = input('Enter a new message: ')
    results = find_similar_messages(query)
    print('\nTop similar messages and replies:')
    for sim, msg, reply in results:
        print(f"\nSimilarity: {sim:.3f}")
        print(f"Message: {msg}")
        print(f"Reply: {reply}")

if __name__ == "__main__":
    main()
