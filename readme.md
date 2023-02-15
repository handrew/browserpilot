# LLM-Based Web Browsing Agent

This repo was inspired by the work of [Yihui He](https://github.com/yihui-he/ActGPT), [Adept.ai](https://adept.ai/), and [Nat Friedman](https://github.com/nat/natbot). In particular, the basic abstractions were built off of Yihui's hackathon code. The code to clean HTML outputs and fit them into an LLM's context window was taken from NatBot. Adept, of course, broke ground with their demo. 


## Architecture Description

TODO

The hope is that as much of this is abstracted away from the user as possible. Adding agents should be as simple as defining instructions in plain text, and then chaining together those subroutines. 


## Installation

1. `pip install -r requirements.txt`
2. Download Chromedriver (latest stable release) from [here](https://sites.google.com/chromium.org/driver/) and place it in the same folder as this file. Unzip.
3. In Finder, right click the unpacked chromedriver and click "Open". This will remove the restrictive default permissions and allow Python to access it.


## Usage
### API
The form factor is fairly simple (see below). The harder (but funner) part is writing the natural language prompts.

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

### Writing Prompts

It helps if you are familiar with how Selenium works and programming in general, because effectively I am using GPT-3 to translate natural language into code, so you should be as precise as you can. In this way, it is more like writing code with Copilot than it is talking to a friend; for instance, it helps to refer to things as text boxes (vs. "search box") or buttons which say "Log in" rather than "the login button". Sometimes, it will also not pick up on specific words that are important, so it helps to break them out into separate lines. Instead of "find all the visible text boxes", you do "find all the text boxes" and then "find the first visible text box".

You can look at some examples TODO to get started.

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

## Contributing

Read "Writing Prompts" above and simply make a pull request to add something to `prompts/`!

## TODO
In order of easiest to hardest.
- [ ] Finish the README
- [ ] Make gif
- [x] Add a loading feature which can take in prompts and cached successful runs.
    - [x] Make `use_compiled` actually work
    - [x] Add collation and output for InstructionCompiler to yaml
- [ ] Get the specific point in the stack trace that something failed, and start executing from there
- [ ] Better stack trace virtualization to make it easier to debug
- [ ] 🚨 If anyone can figure out how to feed the content of the HTML page into the GPT-3 context window and have it reliably pick out from it, that would be great!
