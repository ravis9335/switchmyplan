import json
import numpy as np
import openai
openai.api_key = ("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")
import faiss
import logging
from flask import Blueprint, request, jsonify


# Set up a module-level logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# Create a Flask blueprint for knowledge base endpoints
kb_blueprint = Blueprint('kb', __name__)


def load_kb_chunks(path="kb_chunks.json"):
    """
    Load knowledge base chunks from a JSON file.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            chunks = json.load(f)
        logger.info(f"Loaded {len(chunks)} KB chunks from {path}.")
        return chunks
    except Exception as e:
        logger.error(f"Error loading KB chunks: {e}")
        return []


def init_faiss_index(chunks):
    """
    Create a FAISS index from KB chunks using OpenAI embeddings.
    """
    texts = [chunk["text"] for chunk in chunks]
    try:
        response = openai.Embedding.create(input=texts, model="text-embedding-ada-002")
        embeddings = [item["embedding"] for item in response["data"]]
        embeddings = np.array(embeddings, dtype=np.float32)
    except Exception as e:
        logger.error(f"Error generating embeddings: {e}")
        raise e
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatL2(dimension)
    index.add(embeddings)
    logger.info(f"FAISS index created with {index.ntotal} vectors.")
    return index


# Load KB chunks and build the index on module initialization
kb_chunks = load_kb_chunks()
kb_index = init_faiss_index(kb_chunks) if kb_chunks else None


def search_kb(query, top_k=3):
    """
    Search the KB index for the top_k most similar chunks to the query.
    Returns the concatenated text of those chunks.
    """
    if not kb_index:
        logger.error("KB index is not initialized.")
        return ""
    try:
        response = openai.Embedding.create(input=[query], model="text-embedding-ada-002")
        query_embedding = response["data"][0]["embedding"]
        query_embedding = np.array([query_embedding], dtype=np.float32)
        distances, indices = kb_index.search(query_embedding, top_k)
        retrieved_texts = []
        for idx in indices[0]:
            if idx < len(kb_chunks):
                retrieved_texts.append(kb_chunks[idx]["text"])
        return "\n\n".join(retrieved_texts)
    except Exception as e:
        logger.error(f"Error in search_kb: {e}")
        return ""


@kb_blueprint.route('/ask_kb', methods=['POST'])
def ask_kb():
    """
    Endpoint to answer a user question based solely on the provided KB context.
    Expects a JSON payload with a "question" field.
    """
    data = request.get_json(force=True)
    user_question = data.get("question", "").strip()

    if not user_question:
        return jsonify({"answer": "Please provide a question."}), 400

    # Retrieve context from the KB based on the user query
    context_text = search_kb(user_question, top_k=3)

    # Construct the prompt ensuring the model uses ONLY the provided context
    prompt = f"""
You are a mobile sales advisor. Answer the following question using ONLY the context provided.
If the answer is not contained within the context, say "I don't have enough information."

Context:
{context_text}

Question: {user_question}
Answer:"""

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system",
                 "content": "You are a helpful mobile sales advisor who uses only the provided context to answer questions."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=150
        )
        answer = response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Error generating answer from OpenAI: {e}")
        answer = "There was an error processing your request. Please try again later."

    return jsonify({"answer": answer})

if __name__ == "__main__":
    from flask import Flask
    import openai

    # Set your OpenAI API key
    openai.api_key = (
        "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")

    app = Flask(__name__)
    app.register_blueprint(kb_blueprint)

    app.run(debug=True, port=5001)