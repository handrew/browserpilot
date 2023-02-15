import os
import time
import openai

"""Set the OpenAI API key."""
openai.api_key = os.environ["OPENAI_API_KEY"]

"""Set up all the prompt variables."""

# Designated tokens. 
NO_RESPONSE_TOKEN = "<NONE>"  # To denote that empty response from model.
RUN_PROMPT_TOKEN = "<RUN_PROMPT>"  # To denote command to run subroutine.

# Suffixes to add to the base prompt.
STACK_TRACE_SUFFIX = "\n\nSTACK TRACE: "
RETRY_SUFFIX = "\n\nAttempting again.\n\nOUTPUT: "

# Prompts! The best part :).
BASE_PROMPT = """You have an instance `env` with the following methods:
- `env.driver.find_elements(by='id', value=None)` which finds and returns list of WebElement. The argument `by` is a string that specifies the locator strategy. The argument `value` is a string that specifies the locator value. `by` is usually `xpath` and `value` is the xpath of the element.
- `env.find_nearest(e, xpath)` can only be used to locate an element that matches the xpath near element e. 
- `env.send_keys(text)` is only used to type in string `text`. string ENTER is Keys.ENTER
- `env.get(url)` goes to url.
- `env.get_llm_response(text)` that asks AI about a string `text`.
- `env.click(element)` clicks the element.
- `env.wait(seconds)` waits for `seconds` seconds.
- `env.scroll(direction)` scrolls the page. `direction` is either "up" or "down".

WebElement has functions:
1. `element.text` returns the text of the element.
2. `element.get_attribute(attr)` returns the value of the attribute of the element. If the attribute does not exist, it returns ''.
3. `element.find_elements(by='id', value=None)` it's the same as `env.driver.find_elements()` except that it only searches the children of the element.
4. `element.is_displayed()` returns if the element is visible.

The xpath of a text box is usually "//div[@role = 'textarea']|//div[@role = 'textbox']|//input".
The xpath of text is usually "//*[string-length(text()) > 0]".
The xpath for a button usually "//div[@role = 'button']|//button", but it may sometimes also be styled as an anchor.
The xpath for an element whose text is "text" is "//*[text() = 'text']".

Your code must obey the following constraints:
1. Respect the lowercase and uppercase letters in the instruction.
2. Does not call any functions besides those given above and those defined by the base language spec.
3. Has correct indentation.
4. Only write code.
5. Only do what I instructed you to do.

INSTRUCTIONS:
{instructions}

OUTPUT: ```python"""

PROMPT_TO_FIND_ELEMENT = """Given the HTML under the heading "== HTML ==", write one line of Selenium code that uses `env.driver.find_element` to precisely locate the element which is best described by the following description: {description}.

If there are no appropriate HTML elements found, please return "%s".

== HTML ==
{cleaned_html}

== OUTPUT ==
""" % NO_RESPONSE_TOKEN


class InstructionCompiler:
    def __init__(self, instructions=None, base_prompt=BASE_PROMPT, verbose=False):
        """Initialize the compiler. The compiler handles the sequencing of
        each set of newline-delimited instructions which are injected into
        the base prompt.

        The primary entrypoint is step(). At each step, the compiler will take
        the current instruction and inject it into the base prompt, asking
        the language model to get the next action. Once it has the next action,
        it will inject the action into the base prompt, asking the language
        model to get the output for that action.

        It returns a dict containing the instruction, action, and action output.
        """
        # Assert that none of the parameters are None.
        assert instructions is not None
        assert base_prompt is not None
        self.base_prompt = BASE_PROMPT
        self.prompt_to_find_element = PROMPT_TO_FIND_ELEMENT
        self.verbose = verbose
        self.instructions = instructions

        # Keep track of the instructions that we have left and the ones that
        # we have completed.
        self.functions = {}
        self.instructions_queue = self._parse_instructions_into_queue(instructions)
        self.finished_instructions = []
        self.history = []  # Keep track of the history of actions.

    def _parse_instructions_into_queue(self, instructions):
        """Parse the instructions into a list of instructions."""
        first_pass_queue = instructions.split("\n")
        second_pass_queue = []
        final_queue = []

        # First, parse all the functions, which are denoted by a line that
        # starts with "BEGIN_FUNCTION name" and ends with "# END_FUNCTION".
        # Load them into self.functions, the dict of function name to function
        # body.
        # Start with a first pass over the queue to find all the functions.
        # For anything that is not a function, just add it to the second pass
        # queue.
        while first_pass_queue:
            line = first_pass_queue.pop(0)
            if line.startswith("BEGIN_FUNCTION"):
                function_name = line.split(" ")[-1]
                function_body = ""
                while first_pass_queue:
                    line = first_pass_queue.pop(0)
                    if line.startswith("END_FUNCTION"):
                        break
                    function_body += line + "\n"
                self.functions[function_name] = function_body
            else:
                second_pass_queue.append(line)
        # Then parse the rest of the instructions. Every contiguous set of
        # lines that do not start with "RUN FUNCTION" should be collated
        # into a single block. For any line that starts with
        # "RUN FUNCTION name", then replace it with the respective function
        # body from the dict.
        while second_pass_queue:
            line = second_pass_queue.pop(0)
            if not line:
                continue

            if line.startswith("RUN_FUNCTION"):
                function_name = line.split(" ")[-1]
                function_body = self.functions[function_name]
                final_queue.append(function_body)
            else:
                # Otherwise, just add all contiguous lines that do not start with
                # "# RUN FUNCTION".
                instruction_block = line
                while second_pass_queue:
                    line = second_pass_queue.pop(0)
                    if line.startswith("RUN_FUNCTION"):
                        # Add it back to the queue.
                        second_pass_queue.insert(0, line)
                        break
                    instruction_block += line
                final_queue.append(instruction_block)

        return final_queue

    def get_completion(self, prompt, temperature=0, model="text-davinci-003"):
        """Wrapper over OpenAI's completion API."""
        try:
            response = openai.Completion.create(
                model=model,
                prompt=prompt,
                max_tokens=512,
                top_p=1,
                frequency_penalty=0,
                presence_penalty=0,
                best_of=3,
                temperature=temperature,
            )
            text = response["choices"][0]["text"]
        except openai.error.RateLimitError:
            print("Rate limit error. Sleeping for 10 seconds.")
            time.sleep(10)
            text = self.get_completion(prompt, temperature, model)
        return text

    def get_action_output(self, instructions):
        prompt = self.base_prompt.format(instructions=instructions)
        completion = self.get_completion(prompt).strip()
        action_output = completion.split("\n\n")[0].strip()
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
        prompt = prompt + last_action["action_output"]
        prompt = prompt + STACK_TRACE_SUFFIX + " " + stack_trace_str
        prompt = prompt + RETRY_SUFFIX

        # Get the action output.
        action_info = self.get_action_output(prompt)
        self.history.append(action_info)

        # Optimistically count the instruction as finished.
        self.finished_instructions.append(last_instructions)
        return action_info


if __name__ == "__main__":
    import pprint
    pp = pprint.PrettyPrinter(indent=4)
    
    with open("prompts/examples/buffalo_wikipedia.txt", "r") as f:
        instructions = f.read()

    compiler = InstructionCompiler(instructions=instructions)
    for item in compiler.instructions_queue:
        print(item)

    while compiler.instructions_queue:
        action_info = compiler.step()
        pp.pprint(action_info)
