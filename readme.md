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
TODO

## Contributing

TODO