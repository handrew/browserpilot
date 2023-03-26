"""GPT Selenium Agent abstraction."""
import pdb
import os
import re
import sys
import time
import traceback
import html2text
from bs4 import BeautifulSoup
from bs4.element import NavigableString
from bs4.element import Tag
from llama_index import Document, GPTSimpleVectorIndex, LLMPredictor
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.relative_locator import locate_with
from langchain.chat_models import ChatOpenAI
from .compilers.instruction_compiler import InstructionCompiler
from .memories import Memory

TIME_BETWEEN_ACTIONS = 0.1

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NO_RESPONSE_TOKEN = "<NONE>"  # To denote that empty response from model.
CHATGPT_KWARGS = kwargs = {"temperature": 0, "model_name": "gpt-3.5-turbo"}


class GPTWebElement(webdriver.remote.webelement.WebElement):
    """Wrapper over Selenium's WebElement with an additional iframe ivar for
    recordkeeping."""

    def __init__(self, web_ele, iframe=None):
        # Initialize this object using web_ele.
        super().__init__(web_ele._parent, web_ele._id)
        self.__dict__.update(web_ele.__dict__)
        self.iframe = iframe


class GPTSeleniumAgent:
    def __init__(
        self,
        instructions,
        chromedriver_path,
        chrome_options={},
        user_data_dir="user_data",
        headless=False,
        retry=False,
        model_for_instructions="text-davinci-003",
        model_for_responses="gpt-3.5-turbo",
        enable_memory=False,
        debug=False,
        debug_html_folder="",
        instruction_output_file=None,
        close_after_completion=True,
    ):
        """Initialize the agent.

        Args:
            instructions (list): List of instructions to run or
                io.TextIOWrapper of a YAML file containing instructions.
            chromedriver_path (str): Path to the chromedriver executable.
            chrome_options (dict): Dictionary of options to pass to the
                ChromeDriver.
            model_for_instructions (str): OpenAI model to use for generating
                instructions.
            model_for_responses (str): OpenAI model to use for generating
                responses from `get_llm_response`.
            user_data_dir (str): Path to the user data directory created by
                Selenium.
            headless (bool): Whether to run the browser in headless mode.
            retry (bool): Whether to retry failed actions.
            debug (bool): Whether to start an interactive debug session if
                there is an Exception thrown.
            debug_html_folder (str): Path to the folder where debug HTML files
                should be saved.
            instruction_output_file (str): Path to the YAML file where the
                instructions should be saved.
            close_after_completion (bool): Whether to close the browser after
                the instructions have been executed.
        """
        """Helpful instance variables."""
        assert (
            instruction_output_file is None
            or instruction_output_file.endswith(".yaml")
            or instruction_output_file.endswith(".json")
        ), "Instruction output file must be a YAML or JSON file or None."
        self.model_for_instructions = model_for_instructions
        self.model_for_responses = model_for_responses
        self.instruction_output_file = instruction_output_file
        self.should_retry = retry
        self.debug = debug
        self.debug_html_folder = debug_html_folder
        self.enable_memory = enable_memory
        self.close_after_completion = close_after_completion

        """Fire up the compiler."""
        self.instruction_compiler = InstructionCompiler(
            instructions=instructions,
            model=self.model_for_instructions,
        )

        """Set up the memory."""
        self.memory = None
        if self.enable_memory:
            logger.info("Enabling memory.")
            self.memory = Memory()

        """Set up the driver."""
        _chrome_options = webdriver.ChromeOptions()
        _chrome_options.add_argument(f"user-data-dir={user_data_dir}")
        self.headless = headless
        if headless:
            _chrome_options.add_argument("--headless")
        for option in chrome_options:
            _chrome_options.add_argument(f"{option}={chrome_options[option]}")

        # Instantiate Service with the path to the chromedriver and the options.
        service = Service(chromedriver_path)
        self.driver = webdriver.Chrome(service=service, options=_chrome_options)

    """Helper functions"""

    def _check_danger(self, action_str):
        """Check that the action is not dangerous. If so, just quit."""
        if self._is_potentially_dangerous(action_str):
            logger.warning("Action is potentially dangerous. Exiting.")
            logger.warning("Action: {action}".format(action=action_str))
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

    def _remove_blacklisted_elements_and_attributes(self) -> BeautifulSoup:
        """Clean HTML to remove blacklisted elements and attributes. Returns
        BeautifulSoup object."""
        blacklisted_elements = set(
            [
                "head",
                "title",
                "meta",
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

    def __get_html_elements_for_llm(self):
        """Returns list of BeautifulSoup elements for use in GPT Index.

        First removes blacklisted elements and attributes, then removes any
        children of elements. Finally, removes any elements with no attrs.
        """
        soup = self._remove_blacklisted_elements_and_attributes()
        # Remove children of elements that have children.
        elements = soup.find_all()
        [ele.clear() if ele.contents else ele for ele in elements if ele.contents]
        # Then remove any elements that do not have attributes, e.g., <p></p>.
        elements = [ele for ele in elements if ele.attrs]
        return elements

    def __run_compiled_instructions(self, instructions):
        """Runs Python code previously compiled by InstructionCompiler."""
        ldict = {"env": self}
        self._check_danger(instructions)
        try:
            exec(instructions, globals(), ldict)
        except:
            self.__handle_agent_exception(instructions)

        if self.close_after_completion:
            self.driver.quit()

    def __print_instruction_and_action(self, instruction, action):
        """Logging the instruction and action."""
        info_str = "\nInstruction: {instruction}\n".format(instruction=instruction)
        info_str = info_str + "\nAction: {action}\n".format(action=action)
        logger.info(info_str)

    def __get_relevant_part_of_stack_trace(self):
        """Get the relevant part of the stack trace."""
        original_stack_trace = traceback.format_exc()
        stack_trace = original_stack_trace.split("\n")[3:5]
        stack_trace = "\n".join(stack_trace)
        # Get the name of this class (GPTSeleniumAgent) and
        # replace it with "env".
        class_name = self.__class__.__name__
        stack_trace = stack_trace.replace(class_name, "env")
        # Get the number after the word "line " in the stack trace.
        line_num = int(
            stack_trace.split("line ")[1].split(",")[0].strip()
        )
        return {"stack_trace": stack_trace, "line_num": line_num}

    def __save_html_snapshot(self):
        """Helpful for debugging."""
        # Check if the folder exists, and if not, create it.
        if not os.path.exists(self.debug_html_folder):
            os.makedirs(self.debug_html_folder)

        # Save an HTML of the entire page.
        debug_name = "debug.html"
        debug_name = os.path.join(self.debug_html_folder, debug_name)

        html = self.driver.page_source
        with open(debug_name, "w+") as f:
            f.write(html)

        # Save a screenshot of the entire page.
        screenshot_name = "debug.png"
        screenshot_name = os.path.join(self.debug_html_folder, screenshot_name)
        self.driver.save_screenshot(screenshot_name)

        # Save screenshots and HTML from each iframe.
        iframes = self.driver.find_elements(by=By.TAG_NAME, value="iframe")
        for i, iframe in enumerate(iframes):
            screenshot_name = "debug_{iframe_num}.png".format(iframe_num=i)
            screenshot_name = os.path.join(self.debug_html_folder, screenshot_name)
            # iframe.screenshot(screenshot_name)
            iframe_debug_name = "debug_{iframe_num}.html".format(iframe_num=i)
            iframe_debug_name = os.path.join(self.debug_html_folder, iframe_debug_name)
            with open(iframe_debug_name, "w+") as f:
                self.driver.switch_to.frame(iframe)
                f.write(self.driver.page_source)
            self.driver.switch_to.default_content()
        self.driver.switch_to.default_content()

    def __handle_agent_exception(self, action):
        """To be used in a try/except block to handle exceptions."""
        stack_trace_result = self.__get_relevant_part_of_stack_trace()
        stack_trace = stack_trace_result["stack_trace"]
        line_num = stack_trace_result["line_num"]
        line_num = stack_trace_result["line_num"]
        problem_instruction = "\nFailed on line: {line}\n".format(
            line=action.split("\n")[line_num - 1]
        )
        logger.info("\n\n" + stack_trace)
        logger.info(problem_instruction)

        if self.debug:
            if self.debug_html_folder:
                self.__save_html_snapshot()

            logger.info(traceback.print_exc())
            logger.info(
                "Starting interactive debugger. Type `env` for the Agent object."
            )
            env = self  # For the interactive debugger.
            pdb.set_trace()

        if self.should_retry:
            step = self.instruction_compiler.retry(problem_instruction + stack_trace)
            instruction = step["instruction"]
            action = step["action_output"].replace("```", "")
            logger.info("RETRYING...")
            self.__print_instruction_and_action(instruction, action)
        else:
            raise Exception("Failed to execute instruction.")

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
            self.__print_instruction_and_action(instruction, action)

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
                    action = self.__handle_agent_exception(action)

        if self.instruction_output_file:
            self.instruction_compiler.save_compiled_instructions(
                self.instruction_output_file
            )

        if self.close_after_completion:
            self.driver.quit()

    def __switch_to_element_iframe(func):
        """Decorator function to switch to the iframe of the element."""

        def wrapper(*args):
            self = args[0]
            element = args[1]
            if isinstance(element, GPTWebElement) and (element is not None):
                iframe = element.iframe
                if iframe is not None:
                    self.driver.switch_to.frame(iframe)
                result = func(*args)
                self.driver.switch_to.default_content()
            else:
                result = func(*args)

            return result

        return wrapper

    """Functions meant for the client to call."""

    def set_instructions(self, instructions):
        """Reset the instructions to `instructions`."""
        self.instruction_compiler.set_instructions(instructions)

    def run(self):
        """Run the agent."""
        should_use_compiled = self.instruction_compiler.use_compiled
        compiled = self.instruction_compiler.compiled_instructions
        if should_use_compiled and compiled:
            logger.info("Found cached instructions. Running...")
            instructions = self.instruction_compiler.compiled_instructions
            instructions = "\n".join(instructions).replace("```", "")
            self.__run_compiled_instructions(instructions)
        else:
            logger.info("No cached instructions found. Running...")
            self.__step_through_instructions()

    """Functions exposed to the agent via the text prompt."""

    def wait(self, seconds):
        time.sleep(seconds)

    def get(self, url):
        if not url.startswith("http"):
            url = "http://" + url
        self.driver.get(url)
        time.sleep(2)
        if self.enable_memory:
            # Get all the visible text from the page and add it to the memory.
            text = self.get_text_from_page(entire_page=False)
            self.memory.add(text)

    @__switch_to_element_iframe
    def is_element_visible_in_viewport(self, element: GPTWebElement) -> bool:
        is_visible = self.driver.execute_script(
            "var elem = arguments[0],                 "
            "  box = elem.getBoundingClientRect(),    "
            "  cx = box.left + box.width / 2,         "
            "  cy = box.top + box.height / 2,         "
            "  e = document.elementFromPoint(cx, cy); "
            "for (; e; e = e.parentElement) {         "
            "  if (e === elem)                        "
            "    return true;                         "
            "}                                        "
            "return false;                            ",
            element,
        )
        return is_visible

    def scroll(self, direction=None, iframe=None):
        assert direction in ["up", "down", "left", "right"]
        assert (iframe is None) or isinstance(iframe, GPTWebElement)
        if iframe is not None:
            # Switch to the iframe of the element.
            if iframe is not None:
                self.driver.switch_to.frame(iframe)

        if direction == "up":
            # Do the python equivalent of the following JavaScript:
            # "(document.scrollingElement || document.body).scrollTop = (document.scrollingElement || document.body).scrollTop - window.innerHeight;"
            self.driver.execute_script("window.scrollBy(0, -window.innerHeight);")
        elif direction == "down":
            # Do the python equivalent of the following JavaScript:
            # "(document.scrollingElement || document.body).scrollTop = (document.scrollingElement || document.body).scrollTop + window.innerHeight;"
            self.driver.execute_script("window.scrollBy(0, window.innerHeight);")
        elif direction == "left":
            self.driver.execute_script("window.scrollBy(-window.innerWidth, 0);")
        elif direction == "right":
            self.driver.execute_script("window.scrollBy(window.innerWidth, 0);")

        # Switch back to the default frame.
        self.driver.switch_to.default_content()

    def find_element(self, by="id", value=None):
        return self.find_elements(by, value)[0]

    def find_elements(self, by="id", value=None):
        """Wrapper over `driver.find_elements` which also scans iframes.

        First, it finds all elements on the page that match the given
        `by` and `value`. Then, it finds all iframes on the page and
        switches to each one. It then finds all elements on the page
        that match the given `by` and `value`. It then switches back
        to the original frame and repeats the process for each iframe.

        Finally, it returns the list of all elements found on the page
        and in all iframes. Returns a list of GPTWebElement objects.
        """
        elements = self.driver.find_elements(by, value)
        elements = [GPTWebElement(element) for element in elements]
        iframes = self.driver.find_elements(by=By.TAG_NAME, value="iframe")
        logger.info("Found {num} iframes.".format(num=len(iframes)))
        for iframe in iframes:
            self.driver.switch_to.frame(iframe)
            iframe_elements = self.driver.find_elements(by, value)
            iframe_elements = [
                GPTWebElement(element, iframe=iframe) for element in iframe_elements
            ]
            elements.extend(iframe_elements)
            self.driver.switch_to.default_content()
        return elements

    @__switch_to_element_iframe
    def find_nearest_textbox(self, element: GPTWebElement):
        try:
            textbox = self.driver.find_element(
                locate_with(By.XPATH, "//div[@role = 'textbox']").near(element)
            )
        except:
            textbox = self.driver.find_element(
                locate_with(By.TAG_NAME, "input").near(element)
            )

        textbox_element = GPTWebElement(textbox, iframe=element.iframe)
        return textbox_element

    @__switch_to_element_iframe
    def find_nearest_text(self, element: GPTWebElement):
        try:
            textbox = self.driver.find_element(
                locate_with(By.XPATH, "//*[text() != '']").near(element)
            )
        except:
            return ""

        return textbox.text

    @__switch_to_element_iframe
    def find_nearest(self, element: GPTWebElement, xpath=None):
        try:
            nearest_elem = self.driver.find_element(
                locate_with(By.XPATH, xpath).near(element)
            )
        except:
            nearest_elem = self.driver.find_element(
                locate_with(By.XPATH, xpath).below(element)
            )

        nearest_element = GPTWebElement(nearest_elem, iframe=element.iframe)
        return nearest_element

    @__switch_to_element_iframe
    def send_keys(self, element: GPTWebElement, keys):
        element.send_keys(keys)

    @__switch_to_element_iframe
    def click(self, element: GPTWebElement):
        wait_time = TIME_BETWEEN_ACTIONS

        url_before_click = self.driver.current_url
        ActionChains(self.driver).pause(wait_time).move_to_element(element).pause(
            wait_time
        ).click(element).perform()
        url_after_click = self.driver.current_url

        # If the URL changed, then add the page to memory.
        if self.enable_memory and (url_before_click != url_after_click):
            time.sleep(wait_time)
            # Get all the visible text from the page and add it to the memory.
            text = self.get_text_from_page(entire_page=False)
            self.memory.add(text)

    def get_text_from_page(self, entire_page=False):
        """Returns the text from the page."""
        # First, we get the HTML of the page and use html2text to convert it
        # to text.
        if entire_page:
            html = self.driver.page_source
            text = html2text.html2text(html)
        else:
            text = self.driver.find_element(by=By.TAG_NAME, value="body").text

        # Check for iframes too.
        iframes = self.driver.find_elements(by=By.TAG_NAME, value="iframe")
        for iframe in iframes:
            self.driver.switch_to.frame(iframe)
            if entire_page:
                html = self.driver.page_source
                text = text + "\n" + html2text.html2text(html)
            else:
                visible_text = self.driver.find_element(
                    by=By.TAG_NAME, value="body"
                ).text
                text = text + "\n" + visible_text
            self.driver.switch_to.default_content()

        return text

    def retrieve_information(self, prompt, entire_page=False):
        """Retrieves information using using GPT-Index embeddings from a page."""
        text = self.get_text_from_page(entire_page=entire_page)
        index = GPTSimpleVectorIndex([Document(text)])
        logger.info(
            'Retrieving information from web page with prompt: "{prompt}"'.format(
                prompt=prompt
            )
        )
        resp = index.query(
            prompt, llm_predictor=LLMPredictor(llm=ChatOpenAI(**CHATGPT_KWARGS))
        )
        return resp.response.strip()

    def get_llm_response(self, prompt, temperature=0.7, model=None):
        if model is None:
            model = self.model_for_responses

        return self.instruction_compiler.get_completion(
            prompt,
            model=model,
            max_tokens=2048,  # Let it be expressive!
            temperature=temperature,
        )

    def query_memory(self, prompt):
        """Queries the memory of the LLM."""
        if self.enable_memory:
            resp = self.memory.query(prompt)
            return resp
        logger.error("Memory is disabled.")

    def ask_llm_to_find_element(self, element_description):
        """Clean the HTML from self.driver, ask GPT-Index to find the element,
        and return Selenium code to access it. Return a GPTWebElement."""

        # Set up a dict that maps an element string to its object and its
        # source iframe. Shape looks like:
        # element_string => {"iframe": iframe, "element": element_obj}.
        elements_tagged_by_iframe = {}

        # First, get and clean elements from the main page.
        elements = self.__get_html_elements_for_llm()
        elements_tagged_by_iframe.update(
            {ele.prettify(): {"iframe": None, "element": ele} for ele in elements}
        )
        # Then do it for the iframes.
        iframes = self.driver.find_elements(by=By.TAG_NAME, value="iframe")
        for iframe in iframes:
            self.driver.switch_to.frame(iframe)
            elements = self.__get_html_elements_for_llm()
            elements_tagged_by_iframe.update(
                {ele.prettify(): {"iframe": iframe, "element": ele} for ele in elements}
            )

        # Create the docs and a dict of doc_id to element, which will help
        # us find the element that GPT Index returns.
        docs = [Document(element.prettify()) for element in elements]
        doc_id_to_element = {doc.get_doc_id(): doc.get_text() for doc in docs}

        # Construct and query index.
        index = GPTSimpleVectorIndex(docs)
        query = "Find element that matches description: {element_description}. If no element matches, return {no_resp_token}.".format(
            element_description=element_description, no_resp_token=NO_RESPONSE_TOKEN
        )
        query = (
            query + " Please be as succinct as possible, with no additional commentary."
        )
        resp = index.query(
            query, llm_predictor=LLMPredictor(llm=ChatOpenAI(**CHATGPT_KWARGS))
        )
        doc_id = resp.source_nodes[0].doc_id

        resp_text = resp.response.strip()
        if NO_RESPONSE_TOKEN in resp_text:
            logger.info("GPT-Index could not find element. Returning None.")
            return None

        logger.info(
            "Asked GPT-Index to find element. Response: {resp}".format(resp=resp_text)
        )

        # Find the iframe that the element is from.
        found_element = doc_id_to_element[doc_id]
        iframe_of_element = elements_tagged_by_iframe[found_element]["iframe"]

        # Get the argument to the find_element_by_xpath function.
        prompt = self.instruction_compiler.prompt_to_find_element.format(
            cleaned_html=found_element
        )
        llm_output = (
            self.get_llm_response(prompt, temperature=0).strip().replace('"', "")
        )

        # Switch to the iframe that the element is in.
        if iframe_of_element is not None:
            self.driver.switch_to.frame(iframe_of_element)
        element = self.driver.find_element(by="xpath", value=llm_output)
        # Switch back to default_content.
        self.driver.switch_to.default_content()

        return GPTWebElement(element, iframe=iframe_of_element)

    def save(self, text, filename):
        """Save the text to a file."""
        with open(filename, "w") as f:
            f.write(text)

    def screenshot(self, element: GPTWebElement, filename):
        """Take a screenshot of the element."""
        with open(filename, "wb") as f:
            # Check the width and height of the element and make sure it's
            # above 0.
            width = element.size["width"]
            height = element.size["height"]
            if width == 0 or height == 0:
                logger.info(
                    "Skipping screenshot of file {}: element with width or height 0.".format(
                        filename
                    )
                )
                return
            f.write(element.screenshot_as_png)
