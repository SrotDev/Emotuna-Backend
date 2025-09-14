
import os
import sys
from dotenv import load_dotenv

# Setup Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'emotuna.settings')
import django
django.setup()

from agent_dump.tidb_vector_utils import TiDBVectorDB
from sklearn.feature_extraction.text import TfidfVectorizer
import numpy as np
from openai import OpenAI

# --- Embedding logic ---
_vectorizer = TfidfVectorizer()
_fit_corpus = None

def refresh_vectorizer_corpus():
    """Refresh the vectorizer with all messages in the DB."""
    global _fit_corpus
    from chat.models import ChatMessage
    _fit_corpus = [msg.message for msg in ChatMessage.objects.all() if msg.message]
    if not _fit_corpus:
        _fit_corpus = ["dummy"]
    _vectorizer.fit(_fit_corpus)

def get_embedding(text):
    global _fit_corpus
    # Fit vectorizer if not already fit
    if _fit_corpus is None:
        refresh_vectorizer_corpus()
    return _vectorizer.transform([text]).toarray()[0]



# --- Kimi API setup ---
KIMI_KEY = os.getenv('KIMI_KEY')
KIMI_BASE_URL = 'https://api.moonshot.ai/v1'
KIMI_MODEL = 'kimi-k2-0905-preview'

if not KIMI_KEY:
    raise RuntimeError("KIMI_KEY not set in environment variables.")

client = OpenAI(
    api_key=KIMI_KEY,
    base_url=KIMI_BASE_URL,
)



def cosine_similarity(a, b):
    # Ensure both vectors are the same shape
    min_len = min(a.shape[0], b.shape[0])
    a = a[:min_len]
    b = b[:min_len]
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-8
    return float(np.dot(a, b) / denom)


def find_similar_messages(query, username, top_n=3):
    """Find top-N similar messages for a user."""
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
        # emb_shape may be stored as int, tuple, or string; ensure int
        if isinstance(emb_shape, (tuple, list)):
            emb_len = emb_shape[0]
        else:
            try:
                emb_len = int(emb_shape)
            except Exception:
                continue
        emb = np.frombuffer(emb_bytes, dtype=np.float32)[:emb_len]
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
    try:
        completion = client.chat.completions.create(
            model=KIMI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.6,
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"[Kimi API error: {e}]"


def agent_generate_reply(new_message, username):
    """Generate a reply in the user's style using similar messages as context."""
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
