"""Memory for agents."""
import os
from llama_index import GPTVectorStoreIndex, GPTListIndex
from llama_index import Document, LLMPredictor, ServiceContext
from llama_index import StorageContext, load_index_from_storage
from langchain.chat_models import ChatOpenAI

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

LLM_PREDICTOR_TYPES = {
    "gpt-3.5-turbo": ChatOpenAI,
}


class Memory:
    def __init__(self, memory_folder=None, index_type="vector", llm_predictor="gpt-3.5-turbo"):
        assert index_type in INDEX_TYPES, f"Invalid index type: {index_type}"
        assert llm_predictor in LLM_PREDICTOR_TYPES, f"Invalid LLM predictor: {llm_predictor}"

        self.texts = []
        llm_kwargs = {"temperature": 0, "model_name": "gpt-3.5-turbo"}
        predictor_constructor = LLM_PREDICTOR_TYPES[llm_predictor]
        llm = LLMPredictor(llm=predictor_constructor(**llm_kwargs))
        service_context = ServiceContext.from_defaults(llm_predictor=llm)

        if memory_folder and os.path.exists(memory_folder):
            logger.info("Loading memory from disk.")
            storage_context = StorageContext.from_defaults(persist_dir='./storage')
            self.index = load_index_from_storage(storage_context)
        else:
            self.index = INDEX_TYPES[index_type].from_documents([], service_context=service_context)
        self.llm_predictor = llm_predictor

    def query(self, prompt, similarity_top_k=3):
        query_engine = self.index.as_query_engine(similarity_top_k=similarity_top_k)
        return query_engine.query(prompt)

    def add(self, text):
        if text in self.texts:
            logger.info("Skipping duplicate text.")
            return
        self.texts.append(text)
        self.index.insert(Document(text))

    def save(self, path):
        self.index.storage_context.persist(path)