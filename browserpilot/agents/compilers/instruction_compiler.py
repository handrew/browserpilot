"""InstructionCompiler class."""
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

# Designated tokens.
BEGIN_FUNCTION_TOKEN = "BEGIN_FUNCTION"
END_FUNCTION_TOKEN = "END_FUNCTION"
RUN_FUNCTION_TOKEN = "RUN_FUNCTION"
INJECT_FUNCTION_TOKEN = "INJECT_FUNCTION"

# Suffixes to add to the base prompt.
STACK_TRACE_SUFFIX = "\n\nThe code above failed. See stack trace: "
RETRY_SUFFIX = "\n\nPlease try again keeping in mind the above stack trace. Only write code.\n\nOUTPUT: ```python"

# Prompts! The best part :).
BASE_PROMPT = """You have an instance `env` with methods:
- `env.driver`, the Selenium webdriver.
- `env.get(url)` goes to url.
- `env.find_elements(by='class name', value=None)` finds and returns list `WebElement`. The argument `by` is a string that specifies the locator strategy. The argument `value` is a string that specifies the locator value. `by` is usually `xpath` and `value` is the xpath of the element.
- `env.find_element(by='class name', value=None)` is like `env.find_elements()` but only returns the first element.
- `env.find_nearest(e, xpath)` can be used to locate a WebElement that matches the xpath near WebElement e. 
- `env.send_keys(element, text)` sends `text` to element. Be mindful of special keys, like "enter" (use Keys.ENTER) and "tab" (use Keys.TAB).
- `env.click(element)` clicks the WebElement. Use this instead of `element.click()`.
- `env.wait(seconds)` waits for `seconds`.
- `env.scroll(direction, iframe=None)` scrolls. Switches to `iframe` if given. `direction` can be "up", "down", "left", or "right". 
- `env.get_llm_response(text)` asks AI about a string `text`.
- `env.query_memory(prompt)` asks AI to query its memory of ALL the web pages it has browsed so far. Invoked with something like "Query memory".
- `env.retrieve_information(prompt, entire_page=False)` returns a string, information from a page given a prompt. Use prompt="Summarize:" for summaries. Uses all the text if entire_page=True and only visible text if False. Invoked with commands like "retrieve", "find in the page", or similar.
- `env.ask_llm_to_find_element(description)` asks AI to find an WebElement that matches the description. It returns None if it cannot find an element that matches the description, so you must check for that.
- `env.screenshot(element, filename)` takes a screenshot of the element and saves it to `filename`.
- `env.save(text, filename)` saves the string `text` to a file `filename`.
- `env.get_text_from_page(entire_page)` returns the free text from the page. If entire_page is True, it returns all the text from HTML doc. If False, returns only visible text.

Guidelines for using GPTWebElement:
1. `element.text` returns the text of the element.
2. `element.get_attribute(attr)` returns the value of the attribute of the element. If the attribute does not exist, it returns ''.
3. `element.find_elements(by='id', value=None)` is similar to `env.find_elements()` except that it only searches the children of the element and does not search iframes.
4. `env.is_element_visible_in_viewport(element)` returns if the element is visible in the viewport.
5. Do NOT use `element.send_keys(text)` or `element.click()`. Use `env.send_keys(text)` and `env.click(element)` instead.

In xpaths, to get the text of an element, do NOT use `text()`. Use `normalize-space()` instead.
The xpath for an element whose text is "text" is "//*[normalize-space() = 'text']". The xpath for an element that contains text is "//*[contains(normalize-space(), 'text')]".
The xpath of a text box is usually "//input|//div[@role = 'textarea']|//div[@role = 'textbox']".
The xpath for a button is usually "//button|//div[@role = 'button']", but it may sometimes also be an anchor.

Your code must obey the following constraints:
1. Respect case sensitivity in the instructions.
2. Does not call any functions besides those given above and those defined by the base language spec.
3. Has correct indentation.
4. Only write code. Do not write comments.
5. Only do what I instructed you to do.

INSTRUCTIONS:
{instructions}

OUTPUT: ```python"""

PROMPT_TO_FIND_ELEMENT = """Given the HTML below, write the `value` argument to the Python Selenium function `env.find_elements(by='xpath', value=value)` to precisely locate the element.

Do not use any other method besides `env.find_elements`. Again, write only the *string argument for `value`* to the function.

HTML: {cleaned_html}

OUTPUT:"""


class InstructionCompiler:
    def __init__(
        self,
        instructions=None,
        base_prompt=BASE_PROMPT,
        model="text-davinci-003",
        use_compiled=True,
    ):
        """Initialize the compiler. The compiler handles the sequencing of
        each set of instructions which are injected into the base prompt.

        The primary entrypoint is step(). At each step, the compiler will take
        the current instruction and inject it into the base prompt, asking
        the language model to get the next action. Once it has the next action,
        it will inject the action into the base prompt, asking the language
        model to get the output for that action.

        It returns a dict containing the instruction, action, and action output.

        Args:
            instructions (str): Instructions to compile.
            base_prompt (str): The base prompt to use. Defaults to BASE_PROMPT.
            use_compiled (bool): Whether to use the compiled instructions, if
                any.
        """
        # Assert that none of the parameters are None and that the
        # instructions are either of type string or file buffer.
        assert instructions is not None
        assert base_prompt is not None
        assert (
            isinstance(instructions, str)
            or isinstance(instructions, io.TextIOWrapper)
            or isinstance(instructions, dict)
        )

        # Instance variables.
        self.model = model
        self.base_prompt = BASE_PROMPT
        self.prompt_to_find_element = PROMPT_TO_FIND_ELEMENT
        self.use_compiled = use_compiled
        self.api_cache = {}  # Instruction string to API response.
        self.functions = {}  # Set in _parse_instructions_into_queue.
        self.finished_instructions = []
        self.history = []  # Keep track of the history of actions.

        # Set the instructions.
        self.instructions = instructions  # Overriden in set_instructions.
        self.compiled_instructions = []  # Overriden if available.
        self.instructions_queue = []  # Overriden in set_instructions.
        self.set_instructions(instructions)

    def set_instructions(self, instructions: Union[str, dict, io.TextIOWrapper]):
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
            # instructions. Be sure to pre-load the `history` and
            # `finished_instructions` instance variables for `retry`.
            if "compiled" in self.instructions:
                self.compiled_instructions: List = self.instructions["compiled"]
                self.history.append(
                    {
                        "instruction": self.instructions,
                        "action_output": "\n".join(self.compiled_instructions),
                    }
                )
                self.finished_instructions.append(instructions_str)
        else:
            raise ValueError("Instructions must be either a string or a dict.")

        self.instructions_queue = self._parse_instructions_into_queue(instructions_str)

    def _load_instructions(
        self, instructions: Union[str, dict, io.TextIOWrapper]
    ) -> Union[Dict, str]:
        """Load the instructions. If it ends with .yaml or .json, load that."""
        # If it's a string, just return it.
        if isinstance(instructions, str):
            return instructions
        # If it's just a dict, then check that it has the key "instructions".
        # Then, return it.
        elif isinstance(instructions, dict):
            assert "instructions" in instructions, "No instructions found."
            return instructions

        # Otherwise, load the file.
        # Try it as a yaml first.
        try:
            instructions = yaml.safe_load(instructions)
        except yaml.YAMLError as exc:
            try:
                instructions = json.load(instructions)
            except json.JSONDecodeError as exc:
                raise Exception("Error parsing instructions. Requires JSON or YAML.")

        assert "instructions" in instructions, "No instructions found."
        return instructions

    def _parse_instructions_into_queue(self, instructions) -> List:
        """Parse the instructions into a list of instructions."""

        # First pass queue reads all of the functions and removes them.
        # Second pass queue injects those functions for the INJECT_FUNCTION.
        # Third pass queue is what collates the blocks that are fed into the
        # LLM.
        # Final queue is what is returned.
        self.functions = {}
        first_pass_queue = instructions.split("\n")
        second_pass_queue = []
        third_pass_queue = []
        final_queue = []

        # First, parse all the functions, which are denoted by a line that
        # starts with "BEGIN_FUNCTION name" and ends with "END_FUNCTION".
        # Load them into self.functions, the dict of function name to function
        # body.
        # Start with a first pass over the queue to find all the functions.
        # For anything that is not a function, just add it to the second pass
        # queue.
        while first_pass_queue:
            line = first_pass_queue.pop(0)
            if line.startswith("# "):
                continue  # Skip comments.

            if line.startswith(BEGIN_FUNCTION_TOKEN):
                function_name = line.split(" ")[-1]
                function_body = ""
                while first_pass_queue:
                    line = first_pass_queue.pop(0)
                    if line.startswith(END_FUNCTION_TOKEN):
                        break
                    function_body += line + "\n"
                self.functions[function_name] = function_body
            else:
                second_pass_queue.append(line)

        # Second pass, inject the functions into the queue.
        while second_pass_queue:
            line = second_pass_queue.pop(0)
            if line.startswith(INJECT_FUNCTION_TOKEN):
                # Add in the instructions from the function cache.
                # NOTE! The distinction between INJECT_FUNCTION and
                # RUN_FUNCTION is that RUN_FUNCTION will add the function
                # as a block, whereas INJECT_FUNCTION will inject the function
                # as part of the surrounding block.
                function_name = line.split(" ")[-1]
                function_body = self.functions[function_name]
                function_lines = [line for line in function_body.split("\n") if line]
                function_lines.extend(second_pass_queue)
                second_pass_queue = function_lines
            else:
                third_pass_queue.append(line)

        # Then parse the rest of the instructions. Every contiguous set of
        # lines that do not start with "RUN FUNCTION" should be collated
        # into a single block. For any line that starts with
        # "RUN_FUNCTION name", then replace it with the respective function
        # body from the dict.
        while third_pass_queue:
            line = third_pass_queue.pop(0)
            if not line:
                continue

            if line.startswith(RUN_FUNCTION_TOKEN):
                function_name = line.split(" ")[-1]
                function_body = self.functions[function_name]
                final_queue.append(function_body)
            else:
                # Otherwise, just add all contiguous lines that do not start with
                # RUN_FUNCTION.
                instruction_block = line + "\n"
                while third_pass_queue:
                    line = third_pass_queue.pop(0)
                    if line.startswith(RUN_FUNCTION_TOKEN):
                        # Add it back to the queue and stop constructing this
                        # block.
                        third_pass_queue.insert(0, line)
                        break
                    else:
                        instruction_block += line + "\n"
                final_queue.append(instruction_block)

        return final_queue

    def get_completion(
        self, prompt, model=None, temperature=0, max_tokens=1024, use_cache=True
    ):
        """Wrapper over OpenAI's completion API."""
        if model is None:
            model = self.model

        # Check if it's in the cache already.
        if use_cache and prompt in self.api_cache:
            logger.info("Found prompt in API cache. Saving you money...")
            text = self.api_cache[prompt]
            return text

        try:
            if "gpt-3.5-turbo" in model:
                response = openai.ChatCompletion.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    top_p=1,
                    frequency_penalty=0,
                    presence_penalty=0,
                    temperature=temperature,
                    stop=["```"],
                )
                text = response["choices"][0]["message"]["content"]
            else:
                response = openai.Completion.create(
                    model=model,
                    prompt=prompt,
                    max_tokens=max_tokens,
                    top_p=1,
                    frequency_penalty=0,
                    presence_penalty=0,
                    best_of=1,
                    temperature=temperature,
                    stop=["```"],
                )
                text = response["choices"][0]["text"]
        except (
            openai.error.RateLimitError,
            openai.error.APIError,
            openai.error.Timeout,
            openai.error.APIConnectionError,
        ) as exc:
            logger.info(
                "OpenAI error. Likely a rate limit error, API error, or timeout: {exc}. Sleeping for a few seconds.".format(
                    exc=str(exc)
                )
            )
            time.sleep(5)
            text = self.get_completion(
                prompt, temperature=temperature, max_tokens=max_tokens, model=model
            )

        # Add to cache.
        self.api_cache[prompt] = text

        return text

    def get_action_output(self, instructions):
        """Get the action output for the given instructions."""
        prompt = self.base_prompt.format(instructions=instructions)
        completion = self.get_completion(prompt).strip()
        action_output = completion.strip()
        return {
            "instruction": instructions,
            "action_output": action_output,
        }

    def step(self):
        """Run the compiler."""
        # For each instruction, give the base prompt the current instruction.
        # Then, get the completion for that instruction.
        instructions = self.instructions_queue.pop(0)
        if instructions.strip():
            instructions = instructions.strip()
            action_info = self.get_action_output(instructions)
            self.history.append(action_info)

            # Optimistically count the instruction as finished.
            self.finished_instructions.append(instructions)
            return action_info

    def retry(self, stack_trace_str):
        """Revert the compiler to the previous state and run the instruction again."""
        logger.info("Retrying...")
        # Pop off the last instruction and add it back to the queue.
        last_instructions = self.finished_instructions.pop()

        # Get the last action to append to the prompt.
        last_action = self.history.pop()

        # Append the failure suffixes to the prompt.
        prompt = self.base_prompt.format(instructions=last_instructions)
        prompt = prompt + "\n" + last_action["action_output"]
        prompt = prompt + STACK_TRACE_SUFFIX + " " + stack_trace_str
        prompt = prompt + RETRY_SUFFIX

        # Get the action output.
        action_info = self.get_action_output(prompt)
        self.history.append(action_info)

        # Optimistically count the instruction as finished.
        self.finished_instructions.append(last_instructions)
        return action_info

    def save_compiled_instructions(self, filename):
        """Save the compiled instructions to a file."""
        assert filename.endswith(".yaml") or filename.endswith(
            ".json"
        ), "Filename must end with .yaml or .json."
        instructions = []
        for item in self.history:
            instructions.extend(item["instruction"].split("\n"))

        compiled_instructions = []
        for item in self.history:
            compiled_instructions.extend(item["action_output"].split("\n"))

        self.instructions.update(
            {
                "instructions": instructions,
                "compiled": compiled_instructions,
            }
        )
        to_dump = self.instructions
        with open(filename, "w") as f:
            if filename.endswith(".json"):
                json.dump(to_dump, f, indent=4)
            elif filename.endswith(".yaml"):
                yaml.dump(to_dump, f)


if __name__ == "__main__":
    import pprint

    pp = pprint.PrettyPrinter(indent=4)

    with open("prompts/examples/buffalo_wikipedia.txt", "r") as f:
        instructions = f.read()

    compiler = InstructionCompiler(instructions=instructions)

    while compiler.instructions_queue:
        action_info = compiler.step()
        pp.pprint(action_info)
