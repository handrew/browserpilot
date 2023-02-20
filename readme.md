# 🛫 BrowserPilot

An intelligent web browsing agent controlled by natural language.

![demo](assets/demo_buffalo.gif)

Language is the most natural interface through which humans give and receive instructions. Instead of writing bespoke automation or scraping code which is brittle to changes, creating and adding agents should be as simple as writing plain English.

## 🏗️ Installation

1. Clone this repo.
2. `pip install -r requirements.txt`
3. Download Chromedriver (latest stable release) from [here](https://sites.google.com/chromium.org/driver/) and place it in the same folder as this file. Unzip.
4. In Finder, right click the unpacked chromedriver and click "Open". This will remove the restrictive default permissions and allow Python to access it.
5. Create an environment variable in your favorite manner setting OPENAI_API_KEY to your API key.


## 🦭 Usage
### 🗺️ API
The form factor is fairly simple (see below).

```python
from agents.gpt_selenium_agent import GPTSeleniumAgent

instructions = """Go to Google.com
Find all text boxes.
Find the first visible text box.
Click on the first visible text box.
Type in "buffalo buffalo buffalo buffalo buffalo" and press enter.
Wait 2 seconds.
Find all anchor elements that link to Wikipedia.
Click on the first one.
Wait for 10 seconds."""

agent = GPTSeleniumAgent(instructions, "/path/to/chromedriver")
agent.run()
```

The harder (but funner) part is writing the natural language prompts.


### 📑 Writing Prompts

It helps if you are familiar with how Selenium works and programming in general. This is because this project uses GPT-3 to translate natural language into code, so you should be as precise as you can. In this way, it is more like writing code with Copilot than it is talking to a friend; for instance, it helps to refer to things as text boxes (vs. "search box") or "button which says 'Log in'" rather than "the login button". Sometimes, it will also not pick up on specific words that are important, so it helps to break them out into separate lines. Instead of "find all the visible text boxes", you do "find all the text boxes" and then "find the first visible text box".

You can look at some examples in `prompts/examples` to get started.

Create "functions" by enclosing instructions in ```BEGIN_FUNCTION func_name``` and ```END_FUNCTION```, and then call them by starting a line with ```RUN_FUNCTION```. Below is an example:

```
BEGIN_FUNCTION search_buffalo
Go to Google.com
Find all text boxes.
Find the first visible text box.
Click on the first visible text box.
Type in "buffalo buffalo buffalo buffalo buffalo" and press enter.
Wait 2 seconds.
Get all anchors on the page that contain the word "buffalo".
Click on the first link.
END_FUNCTION

RUN_FUNCTION search_buffalo
Wait for 10 seconds.
```

You may also choose to create a yaml file with a list of instructions. In general, it needs to have an `instructions` field, and optionally a `compiled` field which has the processed code. See [buffalo wikipedia example](prompts/examples/buffalo_wikipedia.yaml). 

You may pass a `instruction_output_file` to the constructor of GPTSeleniumAgent which will output a yaml file with the compiled instructions from GPT-3, to avoid having to pay API costs. 

## ✋🏼 Contributing
There are two ways I envision folks contributing.

- **Adding to the Prompt Library**: Read "Writing Prompts" above and simply make a pull request to add something to `prompts/`! At some point, I will figure out a protocol for folder naming conventions and the evaluation of submitted code (for security, accuracy, etc). This would be a particularly attractive option for those who aren't as familiar with coding.
- **Contributing code**: I am happy to take suggestions! The main way to add to the repository is to extend the capabilities of the agent, or to create new agents entirely. The best way to do this is to familiarize yourself with "Architecture and Prompt Patterns" above, and to (a) expand the list of capabilities in the base prompt in `InstructionCompiler` and (b) write the corresponding method in `GPTSeleniumAgent`. 

## ⛩️ Architecture and Prompt Patterns

This repo was inspired by the work of [Yihui He](https://github.com/yihui-he/ActGPT), [Adept.ai](https://adept.ai/), and [Nat Friedman](https://github.com/nat/natbot). In particular, the basic abstractions and prompts used were built off of Yihui's hackathon code. The idea to preprocess HTML and use GPT-3 to intelligently pick elements out is from Nat. 

- The prompts used can be found in [instruction compiler](agents/compilers/instruction_compiler.py). The base prompt describes in plain English a set of actions that the browsing agent can take, some general conventions on how to write code, and some constraints on its behavior. **These actions correspond one-for-one with methods in `GPTSeleniumAgent`**. Those actions, to-date, include:
    - `env.driver.find_elements(by='id', value=None)` which finds and returns list of WebElement.
    - `env.find_nearest(e, xpath)` can only be used to locate an element that matches the xpath near element e. 
    - `env.send_keys(text)` is only used to type in string `text`. 
    - `env.get(url)` goes to url.
    - `env.click(element)` clicks the element.
    - `env.wait(seconds)` waits for `seconds` seconds.
    - `env.scroll(direction)` scrolls the page.
    - `env.get_llm_response(text)` that asks AI about a string `text`.
    - `env.retrieve_information(prompt, entire_page=False)` that retrieves information using GPT-Index embeddings from a page given a prompt.
    - `env.ask_llm_to_find_element(description)` that asks AI to find an element that matches the description.
    - `env.save(text, filename)` saves the string `text` to a file `filename`.
    - `env.get_text_from_page(entire_page)` returns the text from the page.
- The rest of the code is basically middleware which exposes a Selenium object to GPT-3. **For each action mentioned in the base prompt, there is a corresponding method in GPTSeleniumAgent.**
    - An `InstructionCompiler` is used to parse user input into semantically cogent blocks of actions.


## 🚧 TODOs and Future Work
- [ ] 🧩 Variable templating?
- [ ] 🔭 Better intermediate prompt observability (maybe introduce a class which is a proxy for all LLM calls?) 
- [ ] 🎯 Get the specific point in the stack trace that something failed, and start executing from there.
- [ ] 🥞 Better stack trace virtualization to make it easier to debug.

### 🎉 Finished
- [x] GPTSeleniumAgent should be able to load prompts and cached successful runs in the form of yaml files. InstructionCompiler should be able to save instructions to yaml.
- [x] 💭 Add a summarization capability to the agent.
- [x] Demo/test something where it has to ask the LLM to synthesize something it reads online.
- [x] 🚨 Figured out how to feed the content of the HTML page into the GPT-3 context window and have it reliably pick out specific elements from it, that would be great!
