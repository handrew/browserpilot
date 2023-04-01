import sys
import click
from browserpilot.studio import Studio

# Set up CLI.
@click.command()
@click.argument("instructions")
@click.option(
    "--model",
    "-m",
    default="gpt-3.5-turbo",
    help="Model to use.",
)
def main(instructions, model):
    """Runs the Studio."""
    studio = Studio(
        instructions_to_load=instructions, model=model, chromedriver_path="./chromedriver"
    )
    studio.run()


if __name__ == "__main__":
    main()
