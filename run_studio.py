import sys
from browserpilot.studio import Studio

if len(sys.argv) >= 2:
    instructions = sys.argv[1]
else:
    instructions = None

studio = Studio(instructions_to_load=instructions, chromedriver_path="./chromedriver")
studio.run()
