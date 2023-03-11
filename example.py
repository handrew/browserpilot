import sys
import os
import openai
import click
from browserpilot.agents.gpt_selenium_agent import GPTSeleniumAgent

# Set OpenAI API key.
openai.api_key = os.environ["OPENAI_API_KEY"]


@click.command()
@click.argument("instructions")
@click.option("--enable_memory", is_flag=True, help="Enable memory.")
def main(instructions, enable_memory):
    with open(instructions, "r") as instructions:
        agent = GPTSeleniumAgent(
            instructions,
            "./chromedriver",
            # instruction_output_file=sys.argv[1],
            enable_memory=enable_memory,
            debug=True,
        )
        agent.run()


if __name__ == "__main__":
    main()
