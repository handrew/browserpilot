"""Memory for agents."""
from llama_index import GPTSimpleVectorIndex, GPTListIndex
from llama_index import Document, LLMPredictor
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
    "chatgpt": ChatOpenAI,
}

# Not sure if we need this level of granularity, but leaving it here for now.
# https://gpt-index.readthedocs.io/en/latest/guides/usage_pattern.html
SYNTHESIS_TYPES = {
    "default": "default",
    "compact": "compact",
    "summarize": "tree_summarize",
}


class Memory:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        index_type = kwargs.get("index_type", "simple")
        llm_predictor = kwargs.get("llm_predictor", "chatgpt")
        synthesis_type = kwargs.get("synthesis_type", "default")
        assert synthesis_type in SYNTHESIS_TYPES
        assert index_type in INDEX_TYPES
        assert llm_predictor in LLM_PREDICTOR_TYPES

        self.texts = []
        self.index = INDEX_TYPES[index_type]([])
        self.llm_predictor = llm_predictor
        self.synthesis_type = SYNTHESIS_TYPES[synthesis_type]

    def query(self, prompt):
        kwargs = {"temperature": 0, "model_name": "gpt-3.5-turbo"}
        predictor_constructor = LLM_PREDICTOR_TYPES[self.llm_predictor]
        llm = predictor_constructor(**kwargs)
        llm_predictor = LLMPredictor(llm=llm)
        return self.index.query(
            prompt, llm_predictor=llm_predictor, response_mode=self.synthesis_type
        )

    def add(self, text):
        if text in self.texts:
            logger.info("Skipping duplicate text.")
            return
        self.texts.append(text)
        self.index.insert(Document(text))
