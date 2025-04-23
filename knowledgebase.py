import faiss
import openai
import numpy as np

EMBEDDING_MODEL = "text-embedding-ada-002"  # or any supported model from OpenAI
index = None  # global FAISS index
kb_data = None  # store the raw text chunks

def init_kb(knowledge_chunks):
    global kb_data, index
    kb_data = knowledge_chunks

    # Step 1: get embeddings for each chunk
    texts = [chunk["text"] for chunk in kb_data]
    response = openai.Embedding.create(
        input=texts, model=EMBEDDING_MODEL
    )
    embeddings = [r["embedding"] for r in response["data"]]
    embeddings = np.array(embeddings, dtype=np.float32)

    # Step 2: build a Faiss index
    dimension = len(embeddings[0])
    index = faiss.IndexFlatL2(dimension)
    index.add(embeddings)

def search_kb(query, top_k=3):
    # embed the query
    q_embed = openai.Embedding.create(
        input=[query], model=EMBEDDING_MODEL
    )["data"][0]["embedding"]
    q_embed = np.array([q_embed], dtype=np.float32)

    # search
    distances, indices = index.search(q_embed, top_k)
    results = []
    for dist, idx in zip(distances[0], indices[0]):
        chunk = kb_data[idx]
        results.append({"distance": float(dist), "chunk": chunk["text"], "id": chunk["id"]})
    return results