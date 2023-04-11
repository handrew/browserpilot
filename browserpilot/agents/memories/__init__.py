"""Memory for agents."""
import os
from llama_index import GPTSimpleVectorIndex, GPTListIndex
from llama_index import Document, LLMPredictor, ServiceContext
from langchain.chat_models import ChatOpenAI

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# https://gpt-index.readthedocs.io/en/latest/guides/index_guide.html
INDEX_TYPES = {
    # Good for retrieval, because of top_k and embeddings.
    "simple": GPTSimpleVectorIndex,
    # Good for aggregate summaries, but slow.
    "list": GPTListIndex,
}

LLM_PREDICTOR_TYPES = {
    "gpt-3.5-turbo": ChatOpenAI,
}

# Not sure if we need this level of granularity, but leaving it here for now.
# https://gpt-index.readthedocs.io/en/latest/guides/usage_pattern.html
SYNTHESIS_TYPES = {
    "default": "default",
    "compact": "compact",
    "summarize": "tree_summarize",
}


class Memory:
    def __init__(self, memory_file=None, index_type="simple", llm_predictor="gpt-3.5-turbo", synthesis_type="default"):
        assert synthesis_type in SYNTHESIS_TYPES, f"Invalid synthesis type: {synthesis_type}"
        assert index_type in INDEX_TYPES, f"Invalid index type: {index_type}"
        assert llm_predictor in LLM_PREDICTOR_TYPES, f"Invalid LLM predictor: {llm_predictor}"

        self.texts = []
        llm_kwargs = {"temperature": 0, "model_name": "gpt-3.5-turbo"}
        predictor_constructor = LLM_PREDICTOR_TYPES[llm_predictor]
        llm = LLMPredictor(llm=predictor_constructor(**llm_kwargs))
        service_context = ServiceContext.from_defaults(llm_predictor=llm)

        if memory_file and os.path.exists(memory_file):
            logger.info("Loading memory from disk.")
            self.index = INDEX_TYPES[index_type].load_from_disk(memory_file, service_context=service_context)
        else:
            self.index = INDEX_TYPES[index_type].from_documents([], service_context=service_context)
        self.llm_predictor = llm_predictor
        self.synthesis_type = SYNTHESIS_TYPES[synthesis_type]

    def query(self, prompt):
        return self.index.query(
            prompt, response_mode=self.synthesis_type
        )

    def add(self, text):
        if text in self.texts:
            logger.info("Skipping duplicate text.")
            return
        self.texts.append(text)
        self.index.insert(Document(text))

    def save(self, path):
        self.index.save_to_disk(path)