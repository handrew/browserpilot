"""Memory for agents."""
import os
from llama_index.core import GPTVectorStoreIndex, GPTListIndex
from llama_index.core import Document
from llama_index.core import StorageContext, load_index_from_storage
from langchain_openai import ChatOpenAI

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# https://gpt-index.readthedocs.io/en/latest/guides/index_guide.html
INDEX_TYPES = {
    # Good for retrieval, because of top_k and embeddings.
    "vector": GPTVectorStoreIndex,
    # Good for aggregate summaries, but slow.
    "list": GPTListIndex,
}


class Memory:
    def __init__(self, memory_folder=None, index_type="vector"):
        assert index_type in INDEX_TYPES, f"Invalid index type: {index_type}"

        self.texts = []

        if memory_folder and os.path.exists(memory_folder):
            logger.info("Loading memory from disk.")
            storage_context = StorageContext.from_defaults(persist_dir=memory_folder)
            self.index = load_index_from_storage(storage_context)
        else:
            self.index = INDEX_TYPES[index_type].from_documents([])

    def query(self, prompt, similarity_top_k=3):
        query_engine = self.index.as_query_engine(similarity_top_k=similarity_top_k)
        return query_engine.query(prompt)

    def add(self, text):
        if text in self.texts:
            logger.info("Skipping duplicate text.")
            return
        self.texts.append(text)
        self.index.insert(Document(text=text))

    def save(self, path):
        self.index.storage_context.persist(path)