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
                    embedding_shape INT,
                    reply_message TEXT,
                    reply_embedding BLOB,
                    reply_embedding_shape INT
                )
            ''')
        self.conn.commit()

    def insert_embedding(self, id, user_id, message, embedding, reply_message=None, reply_embedding=None):
        # Store numpy array as bytes and shape
        emb_bytes = embedding.tobytes() if embedding is not None else None
        emb_shape = embedding.shape[0] if embedding is not None else None
        reply_emb_bytes = reply_embedding.tobytes() if reply_embedding is not None else None
        reply_emb_shape = reply_embedding.shape[0] if reply_embedding is not None else None
        with self.conn.cursor() as cursor:
            cursor.execute(
                'REPLACE INTO message_embeddings (id, user_id, message, embedding, embedding_shape, reply_message, reply_embedding, reply_embedding_shape) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
                (id, user_id, message, emb_bytes, emb_shape, reply_message, reply_emb_bytes, reply_emb_shape)
            )
        self.conn.commit()

    def get_embedding(self, id):
        with self.conn.cursor() as cursor:
            cursor.execute('SELECT embedding, embedding_shape FROM message_embeddings WHERE id=%s', (id,))
            row = cursor.fetchone()
            if row and row[0] is not None and row[1] is not None:
                return np.frombuffer(row[0], dtype=np.float32)[:row[1]]
            return None

    def close(self):
        self.conn.close()
