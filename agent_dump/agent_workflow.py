import os
import django
import sys
from dotenv import load_dotenv
load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'emotuna.settings')
django.setup()

from agent_dump.tidb_vector_utils import TiDBVectorDB
from sklearn.feature_extraction.text import TfidfVectorizer
import numpy as np

from openai import OpenAI



# Use TfidfVectorizer for lightweight text embeddings
_vectorizer = TfidfVectorizer()
_fit_corpus = []

def get_embedding(text):
    global _fit_corpus
    # Fit vectorizer on the fly if needed (using all messages in DB)
    if not _fit_corpus:
        db = TiDBVectorDB()
        db.create_table()
        with db.conn.cursor() as cursor:
            cursor.execute('SELECT message FROM message_embeddings')
            _fit_corpus = [row[0] for row in cursor.fetchall() if row[0]]
        db.close()
        if not _fit_corpus:
            _fit_corpus = [text]
        _vectorizer.fit(_fit_corpus)
    return _vectorizer.transform([text]).toarray()[0]


# Kimi API key and base URL from .env
KIMI_KEY = os.getenv('KIMI_KEY')
KIMI_BASE_URL = 'https://api.moonshot.ai/v1'
KIMI_MODEL = 'kimi-k2-0905-preview'

client = OpenAI(
    api_key=KIMI_KEY,
    base_url=KIMI_BASE_URL,
)


def cosine_similarity(a, b):
    # Ensure both vectors are the same shape
    min_len = min(a.shape[0], b.shape[0])
    a = a[:min_len]
    b = b[:min_len]
    a = a / (np.linalg.norm(a) + 1e-8)
    b = b / (np.linalg.norm(b) + 1e-8)
    return np.dot(a, b)

def find_similar_messages(query, username, top_n=3):
    # Use user-specific DB or table if needed, or filter by user_id
    db = TiDBVectorDB()
    db.create_table()
    query_emb = get_embedding(query).astype(np.float32)
    with db.conn.cursor() as cursor:
        cursor.execute('SELECT id, user_id, message, embedding, embedding_shape, reply_message FROM message_embeddings')
        rows = cursor.fetchall()
    similarities = []
    for row in rows:
        msg_id, user_id, msg_text, emb_bytes, emb_shape, reply_text = row
        if emb_bytes is None or emb_shape is None:
            continue
        emb = np.frombuffer(emb_bytes, dtype=np.float32)[:emb_shape]
        # Optionally filter by user_id if you want strict per-user retrieval
        sim = cosine_similarity(query_emb, emb)
        similarities.append((sim, msg_text, reply_text))
    similarities.sort(reverse=True, key=lambda x: x[0])
    db.close()
    return similarities[:top_n]

def call_kimi_api(prompt):
    system_prompt = (
        "You are Kimi, an AI assistant provided by Moonshot AI. "
        "You are proficient in Chinese and English conversations. "
        "You provide users with safe, helpful, and accurate answers. "
        "You will reject any questions involving terrorism, racism, or explicit content. "
        "Moonshot AI is a proper noun and should not be translated."
    )
    completion = client.chat.completions.create(
        model=KIMI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        temperature=0.6,
    )
    return completion.choices[0].message.content

def agent_generate_reply(new_message, username):
    similar = find_similar_messages(new_message, username, top_n=3)
    context = ""
    for sim, msg, reply in similar:
        context += f"Past message: {msg}\nUser reply: {reply}\n"
    prompt = f"{context}\nNew message: {new_message}\nReply in the user's style:"
    ai_reply = call_kimi_api(prompt)
    return ai_reply

def main():
    username = input('Enter username: ')
    new_message = input('Enter a new message: ')
    reply = agent_generate_reply(new_message, username)
    print('\nAI-generated reply:')
    print(reply)

if __name__ == "__main__":
    main()
