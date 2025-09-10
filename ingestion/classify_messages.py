import os
import django
import sys
import requests
from dotenv import load_dotenv
from chat.models import ChatMessage


sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'emotuna.settings')
django.setup()
load_dotenv()


HF_API_KEY = os.getenv('HF_API_KEY')
HF_API_URL = 'https://api-inference.huggingface.co/models/'

# Models to use
CLASSIFICATION_MODEL = 'facebook/bart-large-mnli'  # For zero-shot classification
SENTIMENT_MODEL = 'siebert/sentiment-roberta-large-english'  # For sentiment
TOXICITY_MODEL = 'unitary/toxic-bert'  # For toxicity

HEADERS = {"Authorization": f"Bearer {HF_API_KEY}"}

def query_hf(model, payload):
    response = requests.post(HF_API_URL + model, headers=HEADERS, json=payload)
    response.raise_for_status()
    return response.json()

def classify_message(message):
    # Zero-shot classification
    labels = ["generic", "important", "toxic", "nsfw", "constructive criticism", "positive", "negative"]
    result = query_hf(CLASSIFICATION_MODEL, {"inputs": message, "parameters": {"candidate_labels": labels}})
    scores = {lbl: 0 for lbl in labels}
    for lbl, score in zip(result['labels'], result['scores']):
        scores[lbl] = score
    return scores

def detect_sentiment(message):
    result = query_hf(SENTIMENT_MODEL, {"inputs": message})
    print(result)
    # Handle double-nested list structure
    if isinstance(result, list):
        result = result[0]
    if isinstance(result, list):
        result = result[0]
    return result['label']

def detect_toxicity(message):
    result = query_hf(TOXICITY_MODEL, {"inputs": message})
    # Returns list of dicts with 'label' and 'score'
    toxic_score = next((x['score'] for x in result[0] if x['label'] == 'toxic'), 0)
    return toxic_score > 0.5

def main():
    messages = ChatMessage.objects.all()
    for msg in messages:
        print(f"Processing incoming: {msg.message}")
        scores_in = classify_message(msg.message)
        msg.is_important = scores_in['important'] > 0.5
        msg.is_toxic = scores_in['toxic'] > 0.5 or detect_toxicity(msg.message)
        msg.emotion = detect_sentiment(msg.message)
        if msg.reply_message:
            print(f"Processing reply: {msg.reply_message}")
            scores_reply = classify_message(msg.reply_message)
            msg.reply_is_important = scores_reply['important'] > 0.5
            msg.reply_is_toxic = scores_reply['toxic'] > 0.5 or detect_toxicity(msg.reply_message)
            msg.reply_emotion = detect_sentiment(msg.reply_message)
        msg.save()
    print("Classification complete.")

if __name__ == "__main__":
    main()
