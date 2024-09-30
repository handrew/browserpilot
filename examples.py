import click

from browserpilot.agents.gpt_selenium_agent import GPTSeleniumAgent


# Set up multiple command CLI.
@click.group()
def cli():
    pass


@cli.command()
@click.argument("instructions")
@click.option("--chromedriver_path", default="./chromedriver", help="chromedriver path")
@click.option("--model", default="gpt-4o-mini", help="which model?")
@click.option("--memory_folder", default=None, help="Memory folder.")
@click.option("--debug", is_flag=True, help="Enable debugging.")
@click.option("--output", default=None, help="Instruction output file.")
def selenium(instructions, chromedriver_path, model, memory_folder, debug, output):
    with open(instructions, "r") as instructions:
        agent = GPTSeleniumAgent(
            instructions,
            chromedriver_path,
            instruction_output_file=output,
            model_for_instructions=model,
            model_for_responses=model,
            memory_folder=memory_folder,
            debug=debug,
            retry=True,
        )
        agent.run()

"""🤫
@cli.command()
@click.option("--instructions", default=None, help="Instructions file.")
@click.option("--memory_folder", is_flag=True, help="Enable memory.")
def goal(instructions, memory_folder):
    agent = GoalAgent(
        instructions,
        "./chromedriver",
        memory_folder=memory_folder,
        debug=True,
    )
    agent.run()
"""

if __name__ == "__main__":
    cli()
