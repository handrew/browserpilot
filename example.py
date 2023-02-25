import sys
import os
import openai
from browserpilot.agents.gpt_selenium_agent import GPTSeleniumAgent

# Set OpenAI API key.
openai.api_key = os.environ["OPENAI_API_KEY"]


with open(sys.argv[1], "r") as instructions:
    agent = GPTSeleniumAgent(
        instructions,
        "./chromedriver",
        # instruction_output_file=sys.argv[1],
        debug=True,
    )
    agent.run()
