import sys
import os
import openai
import click
from browserpilot.agents.gpt_selenium_agent import GPTSeleniumAgent
from browserpilot.agents.goal_agent import GoalAgent

# Set OpenAI API key.
openai.api_key = os.environ["OPENAI_API_KEY"]

# Set up multiple command CLI.
@click.group()
def cli():
    pass


@cli.command()
@click.argument("instructions")
@click.option("--chromedriver_path", default="./chromedriver", help="chromedriver path")
@click.option("--model", default="gpt-3.5-turbo", help="which model?")
@click.option("--memory_file", default=None, help="Memory file.")
@click.option("--debug", is_flag=True, help="Enable debugging.")
@click.option("--output", default=None, help="Instruction output file.")
def selenium(instructions, chromedriver_path, model, memory_file, debug, output):
    with open(instructions, "r") as instructions:
        agent = GPTSeleniumAgent(
            instructions,
            chromedriver_path,
            instruction_output_file=output,
            model_for_instructions=model,
            memory_file=memory_file,
            debug=debug,
            retry=True,
        )
        agent.run()

"""🤫
@cli.command()
@click.option("--instructions", default=None, help="Instructions file.")
@click.option("--memory_file", is_flag=True, help="Enable memory.")
def goal(instructions, memory_file):
    agent = GoalAgent(
        instructions,
        "./chromedriver",
        memory_file=memory_file,
        debug=True,
    )
    agent.run()
"""

if __name__ == "__main__":
    cli()
