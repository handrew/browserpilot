import time
import openai
import yaml
import io
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

"""Set up all the prompt variables."""

# Designated tokens.
BEGIN_FUNCTION_TOKEN = "BEGIN_FUNCTION"
END_FUNCTION_TOKEN = "END_FUNCTION"
RUN_FUNCTION_TOKEN = "RUN_FUNCTION"
INJECT_FUNCTION_TOKEN = "INJECT_FUNCTION"

# Suffixes to add to the base prompt.
STACK_TRACE_SUFFIX = "\n\nSTACK TRACE: "
RETRY_SUFFIX = "\n\nAttempting again.\n\nOUTPUT: "

# Prompts! The best part :).
BASE_PROMPT = """You have an instance `env` with the following methods:
- `env.driver` is the Selenium webdriver.
- `env.find_elements(by='id', value=None)` which finds and returns list of `GPTWebElement`, which has two instance vars: `WebElement` (from Selenium) and `iframe` (to denote which iframe it came from). The argument `by` is a string that specifies the locator strategy. The argument `value` is a string that specifies the locator value. `by` is usually `xpath` and `value` is the xpath of the element.
- `env.find_element(by='id', value=None)` is similar to `env.find_elements()` except that it only returns the first element.
- `env.find_nearest(e, xpath)` can only be used to locate an GPTWebElement that matches the xpath near GPTWebElement e. 
- `env.send_keys(element, text)` sends `text` to element. If element is None, then it just sends the text as keys. string ENTER is Keys.ENTER
- `env.get(url)` goes to url.
- `env.click(element)` clicks the GPTWebElement.
- `env.wait(seconds)` waits for `seconds` seconds.
- `env.scroll(direction)` scrolls the page. `direction` is either "up" or "down".
- `env.get_llm_response(text)` that asks AI about a string `text`.
- `env.retrieve_information(prompt, entire_page=False)` returns a string, information a page given a prompt. Use prompt="Summarize:" for summaries. Uses all the text if entire_page=True and only text in paragraphs if False. To save tokens, use entire_page=False. Invoked with commands like "retrieve", "find in the page", or similar.
- `env.ask_llm_to_find_element(description)` that asks AI to find an GPTWebElement that matches the description. It returns None if it cannot find an element that matches the description, so you must check for that.
- `env.save(text, filename)` saves the string `text` to a file `filename`.
- `env.get_text_from_page(entire_page)` returns the text from the page. If entire_page is True, it returns all the text. If entire_page is False, it returns only the text in paragraphs.

GPTWebElement has functions:
1. `element.text` returns the text of the element.
2. `element.get_attribute(attr)` returns the value of the attribute of the element. If the attribute does not exist, it returns ''.
3. `element.find_elements(by='id', value=None)` is similar to `env.find_elements()` except that it only searches the children of the element and does not search iframes.
4. `element.is_displayed()` returns if the element is visible.
5. Do NOT use `element.send_keys(text)` or `element.click()`. Use `env.send_keys(text)` and `env.click(element)` instead.

The xpath of a text box is usually "//div[@role = 'textarea']|//div[@role = 'textbox']|//input".
The xpath of text is usually "//*[string-length(text()) > 0]".
The xpath for a button is usually "//button|//div[@role = 'button']", but it may sometimes also be an anchor.
The xpath for an element whose text is "text" is "//*[text() = 'text']".

Your code must obey the following constraints:
1. Respect case sensitivity in the instructions.
2. Does not call any functions besides those given above and those defined by the base language spec.
3. Has correct indentation.
4. Only write code.
5. Only do what I instructed you to do.

INSTRUCTIONS:
{instructions}

OUTPUT: ```python"""

PROMPT_TO_FIND_ELEMENT = """Given the HTML below, write the `value` argument to the Python Selenium function `env.find_elements(by='xpath', value=value)` to precisely locate the element.

Do not use any other method besides `env.find_elements`. Again, write only the *string argument for `value`* to the function.

HTML: {cleaned_html}

OUTPUT:"""


class InstructionCompiler:
    def __init__(self, instructions=None, base_prompt=BASE_PROMPT, use_compiled=True):
        """Initialize the compiler. The compiler handles the sequencing of
        each set of newline-delimited instructions which are injected into
        the base prompt.

        The primary entrypoint is step(). At each step, the compiler will take
        the current instruction and inject it into the base prompt, asking
        the language model to get the next action. Once it has the next action,
        it will inject the action into the base prompt, asking the language
        model to get the output for that action.

        It returns a dict containing the instruction, action, and action output.

        Args:
            instructions (str): The newline-delimited instructions to compile.
            base_prompt (str): The base prompt to use. Defaults to BASE_PROMPT.
            use_compiled (bool): Whether to use the compiled instructions, if
                any.
        """
        # Assert that none of the parameters are None and that the
        # instructions are either of type string or file buffer.
        assert instructions is not None
        assert base_prompt is not None
        assert isinstance(instructions, str) or isinstance(
            instructions, io.TextIOWrapper
        )

        # Instance variables.
        self.base_prompt = BASE_PROMPT
        self.prompt_to_find_element = PROMPT_TO_FIND_ELEMENT
        self.use_compiled = use_compiled
        self.instructions = instructions
        self.api_cache = {}  # Instruction string to API response.

        # If the instructions are a file buffer, then read it as a yaml.
        self.compiled_instructions = []
        if isinstance(instructions, io.TextIOWrapper):
            try:
                instructions_dict = yaml.safe_load(instructions)
            except yaml.YAMLError as exc:
                raise Exception("Error parsing: %s" % instructions)
            # Assert that the dict has the key "instructions".
            assert "instructions" in instructions_dict, "No instructions found."
            # Join the instructions into a string by newline.
            instructions = "\n".join(instructions_dict["instructions"])

            # If the dict has the key "compiled", then load the compiled
            # instructions.
            if "compiled" in instructions_dict:
                self.compiled_instructions = instructions_dict["compiled"]

        # Keep track of the instructions that we have left and the ones that
        # we have completed.
        self.functions = {}
        self.instructions_queue = self._parse_instructions_into_queue(instructions)
        self.finished_instructions = []
        self.history = []  # Keep track of the history of actions.

    def _parse_instructions_into_queue(self, instructions):
        """Parse the instructions into a list of instructions."""

        # First pass queue reads all of the functions and removes them
        # from the string. Second pass queue is what collates the blocks
        # that are fed into the LLM.
        first_pass_queue = instructions.split("\n")
        second_pass_queue = []
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

        # Then parse the rest of the instructions. Every contiguous set of
        # lines that do not start with "RUN FUNCTION" should be collated
        # into a single block. For any line that starts with
        # "RUN_FUNCTION name", then replace it with the respective function
        # body from the dict.
        while second_pass_queue:
            line = second_pass_queue.pop(0)
            if not line:
                continue

            if line.startswith(RUN_FUNCTION_TOKEN):
                function_name = line.split(" ")[-1]
                function_body = self.functions[function_name]
                final_queue.append(function_body)
            elif line.startswith(INJECT_FUNCTION_TOKEN):
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
                # Otherwise, just add all contiguous lines that do not start with
                # RUN_FUNCTION.
                instruction_block = line + "\n"
                while second_pass_queue:
                    line = second_pass_queue.pop(0)
                    if line.startswith(RUN_FUNCTION_TOKEN):
                        # Add it back to the queue and stop constructing this
                        # block.
                        second_pass_queue.insert(0, line)
                        break
                    else:
                        instruction_block += line + "\n"
                final_queue.append(instruction_block)

        return final_queue

    def get_completion(self, prompt, temperature=0, model="text-davinci-003", use_cache=True):
        """Wrapper over OpenAI's completion API."""
        # Check if it's in the cache already.
        if use_cache and prompt in self.api_cache:
            logger.info("Found prompt in API cache. Saving you money...")
            text = self.api_cache[prompt]
            return text

        try:
            response = openai.Completion.create(
                model=model,
                prompt=prompt,
                max_tokens=512,
                top_p=1,
                frequency_penalty=0,
                presence_penalty=0,
                best_of=1,
                temperature=temperature,
                stop=["```"]
            )
            text = response["choices"][0]["text"]
        except openai.error.RateLimitError as exc:
            logger.info("Rate limit error: {exc}. Sleeping for a few seconds.".format(exc=str(exc)))
            time.sleep(5)
            text = self.get_completion(prompt, temperature, model)

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
        assert filename.endswith(".yaml"), "Filename must end with .yaml."
        instructions = []
        for item in self.history:
            instructions.extend(item["instruction"].split("\n"))

        compiled_instructions = []
        for item in self.history:
            compiled_instructions.extend(item["action_output"].split("\n"))

        with open(filename, "w") as f:
            yaml.dump(
                {
                    "instructions": instructions,
                    "compiled": compiled_instructions,
                },
                f,
            )


if __name__ == "__main__":
    import pprint

    pp = pprint.PrettyPrinter(indent=4)

    with open("prompts/examples/buffalo_wikipedia.txt", "r") as f:
        instructions = f.read()

    compiler = InstructionCompiler(instructions=instructions)

    while compiler.instructions_queue:
        action_info = compiler.step()
        pp.pprint(action_info)
