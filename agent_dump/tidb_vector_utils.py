import os
import pymysql
import numpy as np

class TiDBVectorDB:
    def __init__(self):
        self.conn = pymysql.connect(
            host=os.getenv('TIDB_HOST'),
            user=os.getenv('TIDB_USER'),
            password=os.getenv('TIDB_PASSWORD'),
            database=os.getenv('TIDB_DATABASE'),
            port=int(os.getenv('TIDB_PORT', 4000)),
            ssl={'ssl': {}}
        )

    def create_table(self):
        with self.conn.cursor() as cursor:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS message_embeddings (
                    id VARCHAR(64) PRIMARY KEY,
                    user_id INT,
                    message TEXT,
                    embedding BLOB,
                    reply_message TEXT,
                    reply_embedding BLOB
                )
            ''')
        self.conn.commit()

    def insert_embedding(self, id, user_id, message, embedding, reply_message=None, reply_embedding=None):
        # Store numpy array as bytes
        emb_bytes = embedding.tobytes() if embedding is not None else None
        reply_emb_bytes = reply_embedding.tobytes() if reply_embedding is not None else None
        with self.conn.cursor() as cursor:
            cursor.execute(
                'REPLACE INTO message_embeddings (id, user_id, message, embedding, reply_message, reply_embedding) VALUES (%s, %s, %s, %s, %s, %s)',
                (id, user_id, message, emb_bytes, reply_message, reply_emb_bytes)
            )
        self.conn.commit()

    def get_embedding(self, id):
        with self.conn.cursor() as cursor:
            cursor.execute('SELECT embedding FROM message_embeddings WHERE id=%s', (id,))
            row = cursor.fetchone()
            if row:
                return np.frombuffer(row[0], dtype=np.float32)
            return None

    def close(self):
        self.conn.close()
