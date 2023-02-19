"""GPT Selenium Agent abstraction."""
import pdb
import os
import re
import sys
import time
import openai
import traceback
import html2text
from bs4 import BeautifulSoup
from bs4.element import NavigableString
from bs4.element import Tag
from gpt_index import Document, GPTSimpleVectorIndex
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.relative_locator import locate_with
from .compilers.instruction_compiler import InstructionCompiler

NO_RESPONSE_TOKEN = "<NONE>"  # To denote that empty response from model.


class GPTSeleniumAgent:
    def __init__(
        self,
        instructions,
        chromedriver_path,
        user_data_dir="user_data",
        headless=False,
        debug=False,
        instruction_output_file=None,
    ):
        """Initialize the agent."""
        # Helpful instance variables.
        assert instruction_output_file is None or instruction_output_file.endswith(
            ".yaml"
        ), "Instruction output file must be a YAML file or None."
        self.instruction_output_file = instruction_output_file
        self.debug = debug

        # Set up the driver.
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument(f"user-data-dir={user_data_dir}")
        self.headless = headless
        if headless:
            chrome_options.add_argument("--headless")

        # Instantiate Service with the path to the chromedriver and the options.
        service = Service(chromedriver_path)
        self.driver = webdriver.Chrome(service=service, options=chrome_options)

        # Fire up the compiler.
        self.instruction_compiler = InstructionCompiler(instructions=instructions)

    """Functions meant for the client to call."""

    def __run_compiled_instructions(self, instructions):
        """Runs Python code previously compiled by InstructionCompiler."""
        ldict = {"env": self}
        self._check_danger(instructions)
        exec(instructions, globals(), ldict)

    def __step_through_instructions(self):
        """In contrast to `__run_compiled_instructions`, this function will
        step through the instructions queue one at a time, calling the LLM for
        each instruction."""
        ldict = {"env": self}
        while self.instruction_compiler.instructions_queue:
            # `step` will try the instruction for the first time.
            step = self.instruction_compiler.step()

            instruction = step["instruction"]
            action = step["action_output"]
            print(
                "Instruction: {instruction}\n\nAction: {action}\n".format(
                    instruction=instruction, action=action
                )
            )

            action = action.replace("```", "")
            self._check_danger(action)

            # Attempt evals.
            attempts = 0
            while attempts < 3:
                attempts = attempts + 1
                try:
                    exec(action, globals(), ldict)
                    break
                except:
                    stack_trace = "\n".join(traceback.format_exc().split("\n")[3:])
                    print(stack_trace)
                    print("Failed to execute action. Stack trace above. Retrying.")

                    if self.debug:
                        pdb.set_trace()

                    step = self.instruction_compiler.retry(stack_trace)
                    instruction = step["instruction"]
                    action = step["action_output"].replace("```", "")
                    print("RETRYING...")
                    print(
                        "Instruction: {instruction}\nAction: {action}\n".format(
                            instruction=instruction, action=action
                        )
                    )

        if self.instruction_output_file:
            self.instruction_compiler.save_compiled_instructions(
                self.instruction_output_file
            )

    def run(self):
        """Run the agent."""
        should_use_compiled = self.instruction_compiler.use_compiled
        compiled = self.instruction_compiler.compiled_instructions
        if should_use_compiled and compiled:
            print("Found cached instructions. Running...")
            instructions = self.instruction_compiler.compiled_instructions
            instructions = "\n".join(instructions).replace("```", "")
            self.__run_compiled_instructions(instructions)
        else:
            print("No cached instructions found. Running...")
            self.__step_through_instructions()

    """Functions exposed to the agent via the text prompt."""

    def wait(self, seconds):
        time.sleep(seconds)

    def get(self, url):
        if not url.startswith("http"):
            url = "http://" + url
        self.driver.get(url)
        time.sleep(3)

    def scroll(self, direction):
        if direction == "up":
            # Do the python equivalent of the following JavaScript:
            # "(document.scrollingElement || document.body).scrollTop = (document.scrollingElement || document.body).scrollTop - window.innerHeight;"
            self.driver.execute_script("window.scrollBy(0, -window.innerHeight);")
        elif direction == "down":
            # Do the python equivalent of the following JavaScript:
            # "(document.scrollingElement || document.body).scrollTop = (document.scrollingElement || document.body).scrollTop + window.innerHeight;"
            self.driver.execute_script("window.scrollBy(0, window.innerHeight);")

    def find_nearest_textbox(self, element):
        try:
            textbox = self.driver.find_element(
                locate_with(By.XPATH, "//div[@role = 'textbox']").near(element)
            )
        except:
            textbox = self.driver.find_element(
                locate_with(By.TAG_NAME, "input").near(element)
            )
        return textbox

    def find_nearest_text(self, element):
        try:
            textbox = self.driver.find_element(
                locate_with(By.XPATH, "//*[text() != '']").near(element)
            )
        except:
            return ""
        return textbox.text

    def find_nearest(self, e, xpath):
        try:
            return self.driver.find_element(locate_with(By.XPATH, xpath).near(e))
        except:
            return self.driver.find_element(locate_with(By.XPATH, xpath).below(e))

    def send_keys(self, keys):
        ActionChains(self.driver).pause(1).send_keys(keys).pause(1).perform()

    def click(self, element):
        ActionChains(self.driver).pause(1).move_to_element(element).pause(1).click(
            element
        ).perform()

    def retrieve_information(self, prompt, entire_page=False):
        """Retrieves information using using GPT-Index embeddings from a page."""
        # First, we get the HTML of the page and use html2text to convert it
        # to text.
        if entire_page:
            html = self.driver.page_source
            text = html2text.html2text(html)
        else:
            # Only the paragraph elements.
            soup = BeautifulSoup(self.driver.page_source, "lxml")
            text = "\n".join([p.text for p in soup.find_all("p")])

        # Then we use GPT Index to summarize the text.
        doc = Document(text)
        index = GPTSimpleVectorIndex([doc])
        resp = index.query(prompt)
        return resp.response.strip()

    def get_llm_response(self, prompt, temperature=0.7, model="text-davinci-003"):
        try:
            response = openai.Completion.create(
                model=model,
                prompt=prompt,
                temperature=temperature,
                max_tokens=512,
                top_p=1,
                frequency_penalty=0,
                presence_penalty=0,
                best_of=3,
            )

            # Next, we extract the response that was generated by the API.
            text = response["choices"][0]["text"]
            # Finally, we return the response.
            return text
        except openai.error.RateLimitError as exc:
            print(
                "Rate limit error: {exc}. Sleeping for 10 seconds.".format(exc=str(exc))
            )
            time.sleep(5)
            return self.get_llm_response(prompt, model)

    def ask_llm_to_find_element(self, element_description):
        """Clean the HTML from self.driver, ask GPT-Index to find the element,
        and return Selenium code to access it. Return a WebElement."""
        soup = self._clean_html()
        # Get all of the elements, and for each element, if there are
        # children, then remove them.
        elements = soup.find_all()
        [ele.clear() if ele.contents else ele for ele in elements if ele.contents]
        # Then remove any elements that do not have attributes, e.g., <p></p>.
        elements = [ele for ele in elements if ele.attrs]

        # Create a list of documents of each element prettified.
        docs = [Document(element.prettify()) for element in elements]

        # Set up the index and query it.
        index = GPTSimpleVectorIndex(docs)
        query = "Find element that matches description: {element_description}. If no element matches the description, then return {no_resp_token}.".format(
            element_description=element_description, no_resp_token=NO_RESPONSE_TOKEN
        )
        resp = index.query(query)
        resp = resp.response.strip()
        if NO_RESPONSE_TOKEN in resp:
            print("GPT-Index could not find element. Returning None.")
            return None

        print("Asked GPT-Index to find element. Response: {resp}".format(resp=resp))
        # Get the argument to the find_element_by_xpath function.
        prompt = self.instruction_compiler.prompt_to_find_element.format(
            cleaned_html=resp
        )
        response = self.get_llm_response(prompt, temperature=0).strip().replace('"', "")
        return self.driver.find_element(by="xpath", value=response)

    """Helper functions"""

    def _check_danger(self, action_str):
        """Check that the action is not dangerous. If so, just quit."""
        if self._is_potentially_dangerous(action_str):
            print("Action is potentially dangerous. Exiting.")
            print("Action: {action}".format(action=action_str))
            sys.exit(1)

    def _is_potentially_dangerous(self, code_str):
        """Isaac Asimov is rolling over in his grave."""
        # Check that the code doesn't try any funny business with the importing.
        if "import " in code_str:
            return True

        # Check that the code doesn't use any of the following libraries.
        blacklisted_libraries = ["shutil", "requests", "urllib"]  # "os", "sys".
        for library in blacklisted_libraries:
            if library in code_str:
                return True

        # # Check that the code doesn't use any of the following functions.
        # blacklisted_functions = ["open", "exec", "eval", "input", "print", "write"]
        # for function in blacklisted_functions:
        #     if function in code_str:
        #         return True

        return False

    def _clean_html(self):
        """Clean HTML to remove blacklisted elements and attributes."""
        blacklisted_elements = set(
            [
                "head",
                "title",
                "meta",
                "iframe",
                "script",
                "style",
                "path",
                "svg",
                "br",
                "::marker",
            ]
        )
        blacklisted_attributes = set(
            ["style", "ping", "src", "item*", "aria*", "js*", "data-*"]
        )

        # Get the HTML tag for the entire page, convert into BeautifulSoup.
        html = self.driver.find_element(By.TAG_NAME, "html")
        html_string = html.get_attribute("outerHTML")
        soup = BeautifulSoup(html_string, "lxml")

        # Remove blacklisted items and attributes in it.
        for blacklisted in blacklisted_elements:
            for tag in soup.find_all(blacklisted):
                tag.decompose()

        # Set up a helper function to delete the blacklisted attributes from
        # a tag, as long as the attribute name matches the regex.
        def remove_blacklisted_attributes(tag, blacklisted_attributes):
            for attr in tag.attrs.copy():
                for pattern in blacklisted_attributes:
                    if re.match(pattern, attr):
                        del tag[attr]

        for tag in soup.find_all(True):
            remove_blacklisted_attributes(tag, blacklisted_attributes)

        return soup
