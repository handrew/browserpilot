"""Memory for agents."""
from llama_index import Document, GPTSimpleVectorIndex
from llama_index.langchain_helpers.chatgpt import ChatGPTLLMPredictor

# https://gpt-index.readthedocs.io/en/latest/guides/index_guide.html
INDEX_TYPES = {
    "simple": GPTSimpleVectorIndex,
}

LLM_PREDICTOR_TYPES = {
    "chatgpt": ChatGPTLLMPredictor,
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
        self.synthesis_type = synthesis_type
    
    def query(self, prompt):
        # llm_predictor = LLM_PREDICTOR_TYPES[self.llm_predictor]()
        return self.index.query(prompt)

    def add(self, text):
        self.texts.append(text)
        self.index.insert(Document(text))
