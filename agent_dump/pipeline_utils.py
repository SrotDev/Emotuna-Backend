
import os
import sys
from dotenv import load_dotenv
load_dotenv()

# Setup Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'emotuna.settings')
import django
django.setup()

from chat.models import ChatMessage
from agent_dump.tidb_vector_utils import TiDBVectorDB
from sklearn.feature_extraction.text import TfidfVectorizer
import numpy as np
import requests



def classify_new_message(msg):
    """
    Classify a single ChatMessage instance (update emotion, sentiment, etc. in-place and save).
    Accepts either a ChatMessage instance or a message ID.
    """
    HF_API_KEY = os.getenv('HF_API_KEY')
    if not HF_API_KEY:
        raise RuntimeError("HF_API_KEY not set in environment variables.")
    HF_API_URL = 'https://api-inference.huggingface.co/models/'
    CLASSIFICATION_MODEL = 'facebook/bart-large-mnli'
    SENTIMENT_MODEL = 'cardiffnlp/twitter-roberta-base-sentiment-latest'
    TOXICITY_MODEL = 'unitary/toxic-bert'
    HEADERS = {"Authorization": f"Bearer {HF_API_KEY}"}

    def query_hf(model, payload):
        try:
            response = requests.post(HF_API_URL + model, headers=HEADERS, json=payload, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"[HF API error for {model}]: {e}")
            return {}

    def classify_message(message):
        labels = ["important", "toxic", "nsfw", "joy", "anger", "sadness", "fear", "surprise", "neutral"]
        result = query_hf(CLASSIFICATION_MODEL, {"inputs": message, "parameters": {"candidate_labels": labels}})
        scores = {lbl: 0 for lbl in labels}
        if 'labels' in result and 'scores' in result:
            for lbl, score in zip(result['labels'], result['scores']):
                scores[lbl] = score
        return scores

    def detect_sentiment(message):
        result = query_hf(SENTIMENT_MODEL, {"inputs": message})
        if isinstance(result, list):
            result = result[0]
        if isinstance(result, list):
            result = result[0]
        return result.get('label', None)

    def detect_toxicity(message):
        result = query_hf(TOXICITY_MODEL, {"inputs": message})
        try:
            toxic_score = next((x['score'] for x in result[0] if x['label'] == 'toxic'), 0)
            return toxic_score > 0.5
        except Exception:
            return False

    # Accept either a ChatMessage instance or an ID
    if isinstance(msg, int):
        msg = ChatMessage.objects.get(id=msg)
    print(f"Classifying: {msg.message}")
    scores = classify_message(msg.message)
    msg.is_important = scores.get('important', 0) > 0.5
    msg.is_toxic = scores.get('toxic', 0) > 0.5 or detect_toxicity(msg.message)
    msg.is_nsfw = scores.get('nsfw', 0) > 0.5
    # Set emotion to the label with the highest score among emotion labels
    emotion_labels = ["joy", "anger", "sadness", "fear", "surprise", "neutral"]
    msg.emotion = max(emotion_labels, key=lambda lbl: scores.get(lbl, 0)) if any(scores.get(lbl, 0) > 0 for lbl in emotion_labels) else None
    msg.sentiment = detect_sentiment(msg.message)
    msg.save()
    print(f'Classification complete for message id={msg.id}.')





def embed_new_message(msg):
    """
    Embed a single ChatMessage instance (or ID) and store in TiDB.
    Uses a TfidfVectorizer fit on all messages and replies (for consistent vector space).
    """
    db = TiDBVectorDB()
    db.create_table()
    # Accept either a ChatMessage instance or an ID
    if isinstance(msg, int):
        msg = ChatMessage.objects.get(id=msg)
    # Fit vectorizer only on messages and replies for the current user
    user_id = msg.user_id if hasattr(msg, 'user_id') else msg.user.id
    messages = list(ChatMessage.objects.filter(user_id=user_id))
    texts = [m.message for m in messages if m.message]
    reply_texts = [m.reply_message for m in messages if m.reply_message]
    fit_corpus = texts + reply_texts if reply_texts else texts
    if not fit_corpus:
        print('No messages to embed.')
        db.close()
        return
    vectorizer = TfidfVectorizer()
    vectorizer.fit(fit_corpus)
    emb = vectorizer.transform([msg.message]).toarray()[0] if msg.message else None
    reply_emb = vectorizer.transform([msg.reply_message]).toarray()[0] if msg.reply_message else None
    db.insert_embedding(
        str(msg.id),
        msg.user_id,
        msg.message,
        emb.astype(np.float32) if emb is not None else None,
        msg.reply_message,
        reply_emb.astype(np.float32) if reply_emb is not None else None
    )
    db.close()
    print(f'Embedding stored in TiDB for message id={msg.id}.')
