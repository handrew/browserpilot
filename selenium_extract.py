from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.remote.webelement import WebElement

   
def find_label(e):
    # Check if the element is nested inside a label
    nested_label = e.find_elements(By.XPATH, "ancestor::label")
    if nested_label:
        return nested_label[0]

    # Check for a preceding sibling label
    sibling_label = e.find_elements(By.XPATH, "preceding-sibling::label")
    if sibling_label:
        return sibling_label[0]

    # Check for a label that uses the 'for' attribute to link to this element
    id = e.get_attribute('id')
    if id:
        for_label = e.find_elements(By.XPATH, f"//label[@for='{id}']")
        if for_label:
            return for_label[0]

    return None

def get_action_elements(driver: webdriver.Firefox) -> list[WebElement]:
    elements = []
    driver.get("https://audescribe.de/contact")

    interactive_selectors = [
        'a', 'button',
        'input:not([type="hidden"])', 
        'select', 'textarea',
        '[tabindex]:not([tabindex="-1"])', 
        '[role="button"]'
    ]

    interactive_elements = []
    for selector in interactive_selectors:
        interactive_elements.extend(driver.find_elements(By.CSS_SELECTOR, selector))

    for element in interactive_elements:
        if element.text:
            print(f"Element: {element.tag_name} | Text: {element.text}")
            elements.append(element)

    # get all form elements
    forms = driver.find_elements(By.TAG_NAME, "form")
    # printa ll nested form elements
    for form in forms:
        el = form.find_elements(By.TAG_NAME, "input") + form.find_elements(By.TAG_NAME, "select") + form.find_elements(By.TAG_NAME, "textarea")
        for e in el:
            text = e.text or e.get_attribute("aria-label") or e.get_attribute("value") or e.get_attribute("placeholder")
            if text:
                print(f"Element: {e.tag_name} | Text: {text}")
                elements.append(e)
                continue
            label = find_label(e)
            if label:
                print(f"Element: {e.tag_name} | Label: {label.text}")
                elements.append(e)


if __name__ == "__main__":
    options = Options()
    service = FirefoxService()

    options.headless = True
    driver = webdriver.Firefox(service=service, options=options)

    driver.quit()

