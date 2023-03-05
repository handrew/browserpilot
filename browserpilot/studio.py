import yaml
import traceback
from .agents.compilers.instruction_compiler import InstructionCompiler
from .agents.gpt_selenium_agent import GPTSeleniumAgent

COMMANDS = {
    "exit": "Exits the Studio.",
    "run last": "Replay last compiled routine.",
    "compile": "Compiles the routine.",
    "run": "Compiles and runs the routine.",
    "clear": "Clears the routine.",
    "help": "Shows this message.",
    "list": "Shows the routine so far.",
    "delete": "Deletes the last line.",
    "save": "Saves the routine to a yaml file.",
}


class Studio:
    """Command line interface to help users create BrowserPilot routines line
    by line."""

    def __init__(self, instructions_to_load=None, chromedriver_path=None):
        """Initializes the Studio."""
        assert chromedriver_path is not None, "Must provide chromedriver_path."
        self.chromedriver_path = chromedriver_path
        self._lines = []
        self._compiled_cache = {}  # Instruction strings => compiled output.
        self._last_compiled_output = None

        if instructions_to_load is not None:
            if not instructions_to_load.endswith(".yaml"):
                # Split by newline.
                self._lines = instructions_to_load.split("\n")
            else:
                with open(instructions_to_load, "r") as f:
                    instructions = yaml.safe_load(f)
                    self._lines = instructions["instructions"]
                    if "compiled" in instructions:
                        self._last_compiled_output = instructions

    def __print_instructions(self):
        print("See the below instructions for how to use the Studio.")
        for command, description in COMMANDS.items():
            print(
                "  '{command}': {description}".format(
                    command=command, description=description
                )
            )
        print()
        print("Otherwise, just type in your routine in plain English, line by line.")
        print()
        if self._lines:
            print("Current routine:")
            self._print_lines()

    def _print_lines(self):
        """Prints the lines of the routine."""
        for i, line in enumerate(self._lines):
            print("{i}: {line}".format(i=i, line=line))

    def _format_lines_for_compiler(self):
        """Formats the lines of the routine for the compiler."""
        return "\n".join(self._lines)

    def _format_last_compiled_output_for_agent(self):
        """Formats the last compiled output for the agent."""
        # Rename "action_output" key to "compiled" in the dict.
        if self._last_compiled_output is None:
            print("No compiled output to run.")
            return
        output = self._last_compiled_output.copy()
        output["compiled"] = output["action_output"]
        output["instructions"] = output["instruction"].split("\n")
        output["compiled"] = output["compiled"].split("\n")
        del output["instruction"]
        del output["action_output"]

        # Save as temp yaml file.
        with open("_temp.yaml", "w") as f:
            f.write(yaml.dump(output))
        return "_temp.yaml"

    def save(self, filename):
        """Saves the routine to a yaml file with field "instructions"."""
        if not filename.endswith(".yaml"):
            filename = filename + ".yaml"
        with open(filename, "w") as f:
            f.write(yaml.dump({"instructions": self._lines}))
        print("Saved to {filename}.".format(filename=filename))

    def _compile_instructions(self):
        print("Compiling instructions...")
        lines = self._format_lines_for_compiler()
        if lines in self._compiled_cache:
            print("Using cached compiled instructions.")
            results = self._compiled_cache[lines]
        else:
            compiler = InstructionCompiler(lines)
            results = compiler.step()

        print("Compiled instructions:")
        self._last_compiled_output = results
        self._compiled_cache[lines] = results
        compiled = results["action_output"].split("\n")
        return compiled

    def run(self):
        """Runs the Studio."""
        print("Welcome to the BrowserPilot Studio!\n")
        self.__print_instructions()
        while True:
            line = input("> ")
            line_lower = line.lower().strip()
            if line_lower == "exit" or line_lower == "quit":
                print("Exiting the Studio.")
                # Remove temp file.
                import os

                if os.path.exists("_temp.yaml"):
                    os.remove("_temp.yaml")
                break
            elif line_lower == "run last":
                self._print_lines()
                filename = self._format_last_compiled_output_for_agent()
                with open(filename, "r") as f:
                    agent = GPTSeleniumAgent(f, chromedriver_path=self.chromedriver_path)
                try:
                    agent.run()
                except:
                    print("There was an error!")
                    traceback.print_exc()

            elif line_lower == "compile":
                self._print_lines()
                compiled = self._compile_instructions()
                for i, line in enumerate(compiled):
                    print("{i}: {line}".format(i=i, line=line))
            elif line_lower == "run":
                self._print_lines()
                compiled = self._compile_instructions()
                for i, line in enumerate(compiled):
                    print("{i}: {line}".format(i=i, line=line))
                filename = self._format_last_compiled_output_for_agent()

                with open(filename, "r") as f:
                    agent = GPTSeleniumAgent(f, chromedriver_path=self.chromedriver_path)
                
                try:
                    agent.run()
                except:
                    print("There was an error!")
                    traceback.print_exc()
            elif line_lower == "clear":
                self._lines = []
            elif line_lower == "help":
                self.__print_instructions()
            elif line_lower == "list":
                self._print_lines()
            elif line_lower == "delete":
                print("Deleting last line: ".format(self._lines[-1]))
                self._lines = self._lines[:-1]
                self._print_lines()
            elif line_lower == "save":
                filename = input("> Enter the filename: ")
                self.save(filename)
            else:
                self._lines.append(line)
                print("Line added.")
            print()
