"""GPT Selenium Agent abstraction."""
import pdb
import os
import re
import sys
import time
import openai
import traceback
from bs4 import BeautifulSoup
from bs4.element import NavigableString
from bs4.element import Tag
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.relative_locator import locate_with
from compilers.instruction_compiler import InstructionCompiler


class GPTSeleniumAgent:
    def __init__(
        self,
        instructions,
        chromedriver_path,
        user_data_dir="user_data",
        headless=False,
        debug=False,
    ):
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument(f"user-data-dir={user_data_dir}")
        self.debug = debug
        self.headless = headless
        if headless:
            chrome_options.add_argument("--headless")

        # Instantiate Service with the path to the chromedriver and the options.
        service = Service(chromedriver_path)
        self.driver = webdriver.Chrome(service=service, options=chrome_options)

        self.instruction_compiler = InstructionCompiler(
            instructions=instructions, verbose=True
        )

    """Functions meant for the client to call."""

    def run(self):
        while self.instruction_compiler.instructions_queue:
            # `step` will try the instruction for the first time.
            step = self.instruction_compiler.step()

            instruction = step["instruction"]
            action = step["action_output"]
            print(
                "Instruction: {instruction}\nAction: {action}\n".format(
                    instruction=instruction, action=action
                )
            )

            # Prepare for eval.
            ldict = {"env": self}
            action = action.replace("```", "")
            if self._is_potentially_dangerous(action):
                print("Action is potentially dangerous. Exiting.")
                print("Action: {action}".format(action=action))
                sys.exit(1)

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
                    action = step["action_output"]
                    print("RETRYING...")
                    print(
                        "Instruction: {instruction}\nAction: {action}\n".format(
                            instruction=instruction, action=action
                        )
                    )

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

    def get_llm_response(self, prompt, model="text-davinci-003"):
        if "write code" not in prompt:
            temperature = 0.7
            lines = prompt.splitlines()
            if len(lines) > 10:
                prompt = " ".join(lines)[:300]
        else:
            temperature = 0

        response = openai.Completion.create(
            model=model,
            prompt=prompt,
            temperature=temperature,
            max_tokens=512,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
            stop=["```"],
            best_of=3,
        )

        # Next, we extract the response that was generated by the API.
        text = response["choices"][0]["text"]
        # Finally, we return the response.
        return text

    def ask_llm_to_find_element(self, element_description):
        """Clean the HTML from self.driver, chunk it up, and send it to OpenAI."""
        raise NotImplementedError(
            "This function is implemented, but I would not yet recommend using it."
        )
        # Clean the HTML.
        soup = self._clean_html()
        html_chunks = self._chunk_html(soup)

        found_element = False
        for chunk in html_chunks:
            # Structure the prompt.
            prompt = self.instruction_compiler.prompt_to_find_element.format(
                description=element_description, html=chunk
            )
            # Ask large language model.
            response = self.get_llm_response(prompt).strip()
            if "<NONE>" in response:
                continue

            # If we get here, we've found the element.
            found_element = True
            break

        if not found_element:
            return None
        return response

    """Helper functions"""

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

    def _chunk_html(self, soup):
        """Chunk a BeautifulSoup element into 2048 character chunks for
        OpenAI. Make sure that it is HTML element aware."""
        chunks = []
        current_chunk = ""
        for element in soup.recursiveChildGenerator():
            if isinstance(element, NavigableString):
                if len(current_chunk) + len(element) > 2048:
                    chunks.append(current_chunk)
                    current_chunk = ""
                current_chunk += str(element)
            elif isinstance(element, Tag):
                if len(current_chunk) + len(str(element)) > 2048:
                    chunks.append(current_chunk)
                    current_chunk = ""
                current_chunk += str(element)
        chunks.append(current_chunk)
        return chunks


def main():
    openai.api_key = os.environ.get("OPENAI_API_KEY")

    # Load the instructions from `prompts/examples/nytimes_click_login.txt`.
    with open("prompts/examples/nytimes_click_login.txt", "r") as f:
        instructions = f.read()

    # Instantiate and run.
    env = GPTSeleniumAgent(instructions, "./chromedriver", debug=True)
    env.run()


if __name__ == "__main__":
    main()
