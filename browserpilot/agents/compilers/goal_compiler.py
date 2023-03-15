"""GoalCompiler class."""
import time
import openai
import json
import yaml
import io
import logging
from typing import Dict, List, Union

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

"""Set up all the prompt variables."""

# Beginning prompt.
BEGINNING_PROMPT = """You are given a command to do a task using a web browser.

Let's reason step by step about what sequence of actions you have would to take in order to accomplish a task.

If no direction about which webpage to start on is given, you MUST (1) extract the relevant keywords from the command to search in Google and (2) begin with the lines

Go to google.com
Click on the first visible input element.
Type <keywords> and press enter.

where <keywords> are the extracted keywords.

If direction about the webpage is given, simply return "Go to <webpage>."

Return your answers directly, succinctly, and without prefaces or suffixes. Let's start with the first step ONLY. What is the first step for the following command? Don't narrate what you are doing in your answer.

{command}
"""

# If the above prompt routes you to Google, then this prompt is used.
# Prompt to click the right Google result.
PROMPT_TO_SELECT_GOOGLE_RESULT = """You are given a command to do a task using a web browser.

You are currently on a Google search result page with the following results:
{results}

Your command is: "{command}". Which result should you click on? Return the exact string of your choice, with no punctuation.

"""

# If the beginning prompt does not route you to Google, then this prompt is used.
# TODO
PROMPT_FOR_REST_OF_INSTRUCTIONS = """You are given a command to do a task using a web browser.

You are currently on the webpage {url}.

Your command is: "{command}". 

Your last action was: {last_action}.

You can ONLY do the following actions.
- Go to a url. 
- Click elements on an HTML page, like buttons, anchors, etc. 
- Type things and press keys like enter or tab.
- Wait for `n` seconds.
- Scroll the page.
- Break down the task further, and think about what to do next. 
- Find specific text on the page. 
- Take a screenshot of the page, or an element on the page. 
- Save some text to a file `filename`.

What is the next step? Give your answer as a list of newline delimited instructions without a preface.

"""


class GoalCompiler:
    def __init__(
        self,
        instructions=None,
        model="gpt-3.5-turbo",
    ):
        """Initialize the compiler. The compiler handles the sequencing of
        each set of instructions which are injected into the base prompt.

        

        Args:
            instructions (str): Instructions to compile.
            base_prompt (str): The base prompt to use. Defaults to BASE_PROMPT.
            use_compiled (bool): Whether to use the compiled instructions, if
                any.
        """
        # Instance variables.
        self.instructions = instructions
        self.model = model

        # Load instructions.
        # - Initialize self.instructions to be a dict with the key
        #   "instructions", and possibly "compiled" and "chrome_options".
        # - Initialize instructions_str for the queue.
        self.instructions = self._load_instructions(instructions)
        self.compiled_instructions = []
        if isinstance(self.instructions, str):
            instructions_str = self.instructions
            self.instructions = {
                "instructions": self.instructions.split("\n"),
            }
        elif isinstance(self.instructions, dict):
            instructions_str = "\n".join(self.instructions["instructions"])
            # If the dict has the key "compiled", then load the compiled
            # instructions.
            if "compiled" in self.instructions:
                self.compiled_instructions = self.instructions["compiled"]
        else:
            raise ValueError("Instructions must be either a string or a dict.")

        self.functions = {}  # Set in _parse_instructions_into_queue.
        self.instructions_queue = self._parse_instructions_into_queue(instructions_str)
        self.finished_instructions = []
        self.history = []  # Keep track of the history of actions.
