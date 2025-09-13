import os
import csv
import json
import django
import sys
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'emotuna.settings')
django.setup()

from django.contrib.auth.models import User
from chat.models import Contact, ChatMessage
from agent_dump.tidb_vector_utils import TiDBVectorDB
from sklearn.feature_extraction.text import TfidfVectorizer
import numpy as np
import requests

# --- Import to DB ---
def import_sample_chats_to_db(username, csv_path=None):
    base_dir = os.path.join(os.path.dirname(__file__), username)
    if csv_path is None:
        csv_path = os.path.join(base_dir, 'sample_chats.csv')
    user, _ = User.objects.get_or_create(username=username, defaults={'password': 'testpass'})
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            contact_name = row['contact']
            contact, _ = Contact.objects.get_or_create(user=user, name=contact_name, defaults={'relationship_type': '', 'platform': 'imported'})
            # Robust timestamp parsing
            ts_raw = row['timestamp'].strip()
            try:
                ts_clean = ts_raw.split()[0] + ' ' + ts_raw.split()[1]  # take only date and time
                ts = datetime.strptime(ts_clean, '%Y-%m-%d %H:%M:%S')
            except Exception as e:
                print(f"[WARN] Skipping row with invalid timestamp '{ts_raw}': {e}")
                continue
            # Avoid duplicate messages (use message and timestamp)
            if not ChatMessage.objects.filter(user=user, contact=contact, message=row['message'], timestamp=ts).exists():
                try:
                    ChatMessage.objects.create(
                        user=user,
                        contact=contact,
                        timestamp=ts,
                        message=row.get('message'),
                        reply_message=row.get('reply_message'),
                        platform=row.get('platform', 'imported'),
                        emotion=row.get('emotion'),
                        sentiment=row.get('sentiment'),
                        is_toxic=(row.get('is_toxic', '').lower() == 'true'),
                        telegram_chat_id=row.get('telegram_chat_id') or None,
                        telegram_message_id=row.get('telegram_message_id') or None,
                        is_important=(row.get('is_important', '').lower() == 'true'),
                        is_nsfw=(row.get('is_nsfw', '').lower() == 'true'),
                        user_approved_reply=(row.get('user_approved_reply', '').lower() == 'true'),
                        reply_sent=(row.get('reply_sent', '').lower() == 'true'),
                        score=int(row['score']) if row.get('score') not in (None, '', 'null') else None,
                        ai_generated_message=row.get('ai_generated_message'),
                        # reply_message already set above
                    )
                except Exception as e:
                    print(f"[WARN] Could not import row: {e}")
    print('Import to DB complete.')

# --- Classify ---
def classify_new_messages():
    HF_API_KEY = os.getenv('HF_API_KEY')
    HF_API_URL = 'https://api-inference.huggingface.co/models/'
    CLASSIFICATION_MODEL = 'facebook/bart-large-mnli'
    SENTIMENT_MODEL = 'siebert/sentiment-roberta-large-english'
    TOXICITY_MODEL = 'unitary/toxic-bert'
    HEADERS = {"Authorization": f"Bearer {HF_API_KEY}"}
    def query_hf(model, payload):
        response = requests.post(HF_API_URL + model, headers=HEADERS, json=payload)
        response.raise_for_status()
        return response.json()
    def classify_message(message):
        labels = ["important", "toxic", "nsfw", "joy", "anger", "sadness", "fear", "surprise", "neutral"]
        result = query_hf(CLASSIFICATION_MODEL, {"inputs": message, "parameters": {"candidate_labels": labels}})
        scores = {lbl: 0 for lbl in labels}
        for lbl, score in zip(result['labels'], result['scores']):
            scores[lbl] = score
        return scores
    def detect_sentiment(message):
        result = query_hf(SENTIMENT_MODEL, {"inputs": message})
        if isinstance(result, list):
            result = result[0]
        if isinstance(result, list):
            result = result[0]
        return result['label']
    def detect_toxicity(message):
        result = query_hf(TOXICITY_MODEL, {"inputs": message})
        toxic_score = next((x['score'] for x in result[0] if x['label'] == 'toxic'), 0)
        return toxic_score > 0.5
    messages = ChatMessage.objects.filter(is_important=None)
    for msg in messages:
        print(f"Classifying: {msg.message}")
        scores = classify_message(msg.message)
        msg.is_important = scores['important'] > 0.5
        msg.is_toxic = scores['toxic'] > 0.5 or detect_toxicity(msg.message)
        msg.is_nsfw = scores['nsfw'] > 0.5
        # Set emotion to the label with the highest score among emotion labels
        emotion_labels = ["joy", "anger", "sadness", "fear", "surprise", "neutral"]
        msg.emotion = max(emotion_labels, key=lambda lbl: scores[lbl]) if any(scores[lbl] > 0 for lbl in emotion_labels) else None
        msg.sentiment = detect_sentiment(msg.message)
        msg.save()
    print('Classification complete.')

# --- Embed ---
def embed_new_messages():
    db = TiDBVectorDB()
    db.create_table()
    messages = list(ChatMessage.objects.all())
    texts = [msg.message for msg in messages if msg.message]
    reply_texts = [msg.reply_message for msg in messages if msg.reply_message]
    # Fit vectorizer on all messages and replies
    vectorizer = TfidfVectorizer()
    fit_corpus = texts + reply_texts if reply_texts else texts
    if not fit_corpus:
        print('No messages to embed.')
        db.close()
        return
    vectorizer.fit(fit_corpus)
    for msg in messages:
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
    print('Embeddings stored in TiDB.')


# Convert dpo_feedback_log.csv to sft_dataset.jsonl
def convert_dpo_feedback_to_sft(feedback_csv_path, sft_jsonl_path):
    """
    Convert dpo_feedback_log.csv to sft_dataset.jsonl.
    Each row in the CSV should be converted to a JSON object and written as a line in the output file.
    """
    if not os.path.exists(feedback_csv_path):
        raise FileNotFoundError(f"Feedback log not found: {feedback_csv_path}")
    with open(feedback_csv_path, 'r', encoding='utf-8') as csvfile, \
         open(sft_jsonl_path, 'w', encoding='utf-8') as jsonlfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            # Remove extra quotes from keys and values
            clean_row = {}
            for k, v in row.items():
                clean_key = k.strip().strip('"')
                if isinstance(v, str):
                    clean_val = v.strip().strip('"')
                else:
                    clean_val = v
                clean_row[clean_key] = clean_val
            json.dump(clean_row, jsonlfile, ensure_ascii=False)
            jsonlfile.write('\n')
