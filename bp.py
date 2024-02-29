import selenium_extract
from browserpilot.agents.gpt_selenium_agent import GPTSeleniumAgent

instructions = """Go to audescribe.de/contact
Fill Name with "John Doe"
Fill Email with "john.doe@outlook.de"
Fill Subject with "Test"
Fill Message with "Hello, this is a test message!"
Click on "Submit"
"""

agent = GPTSeleniumAgent(instructions, "/opt/homebrew/bin/chromedriver", debug=True)
agent.run()
