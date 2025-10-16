import pyautogui
import pytesseract
import cv2
import numpy as np
from PIL import Image
import time

# Optional: Set tesseract path manually if not in PATH
pytesseract.pytesseract.tesseract_cmd = 'C:\\Program Files\\Tesseract-OCR\\tesseract.exe'

def find_text_on_screen(text, region=None, confidence=0.8):
    screenshot = pyautogui.screenshot(region=region)
    image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

    # Use OCR to extract text + bounding boxes
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

    for i, word in enumerate(data["text"]):
        if word.strip().lower() == text.lower():
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            print(f"Found '{text}' at ({x},{y})")
            pyautogui.click(x + w // 2, y + h // 2)
            return True
    return False

def open_outlook_via_taskbar_or_start():
    print("Looking for Outlook on taskbar...")
    if find_text_on_screen("Outlook", region=(0, 1000, 1920, 80)):  # Adjust for taskbar area
        print("Clicked Outlook from taskbar.")
    else:
        print("Didn't find on taskbar. Using Start Menu...")
        pyautogui.press('win')
        time.sleep(1)
        pyautogui.write("Outlook", interval=0.1)
        time.sleep(1)
        pyautogui.press("enter")

def wait_for_window(keyword="Inbox", timeout=15):
    print("Waiting for Outlook to open...")
    for _ in range(timeout):
        if find_text_on_screen(keyword):
            print(f"Detected '{keyword}' — Outlook likely opened.")
            return True
        time.sleep(1)
    print("Timeout. Could not confirm Outlook is open.")
    return False

def click_first_email():
    print("Attempting to select first email...")
    if find_text_on_screen("Inbox"):  # fallback example, you may capture actual first email text
        print("Clicked near 'Inbox' area.")
    else:
        print("Could not find first email to click.")

if __name__ == "__main__":
    open_outlook_via_taskbar_or_start()
    if wait_for_window("Inbox"):
        click_first_email()
