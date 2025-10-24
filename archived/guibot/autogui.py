import pyautogui
import pytesseract
import cv2
import numpy as np
from PIL import Image
import time


class GUIAgent:
    def __init__(self, pytesseract_path=None):
        if pytesseract_path:
            pytesseract.pytesseract.tesseract_cmd = pytesseract_path
        else:
            # if it is windows, set default path
            import platform
            if platform.system() == "Windows":
                pytesseract.pytesseract.tesseract_cmd = 'C:\\Program Files\\Tesseract-OCR\\tesseract.exe'  
            else:
                pytesseract.pytesseract.tesseract_cmd = 'tesseract'
    
    def find_text_on_screen(self, text, region=None, confidence=0.8):
        """Find text on the screen using OCR and click it."""
        screenshot = pyautogui.screenshot(region=region)
        
        # Convert screenshot to OpenCV format
        image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR) 

        # Use OCR to extract text + bounding boxes
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

        # Iterate through detected text
        for i, word in enumerate(data["text"]):
            if word.strip().lower() == text.lower():
                x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
                print(f"Found '{text}' at ({x},{y})")
                pyautogui.click(x + w // 2, y + h // 2)
                return True
        return False


    def click_image_on_screen(self, image_path, confidence=0.8):
        """Find an image on the screen and click it."""
        location = pyautogui.locateCenterOnScreen(image_path, confidence=confidence)
        if location:
            print(f"Found image at {location}")
            pyautogui.click(location)
            return True
        return False
    
    def type_text(self, text, interval=0.05):
        """Type text into the active window."""
        pyautogui.write(text, interval=interval)
        
    def press_key(self, key):
        """Press a single key."""
        pyautogui.press(key)
        
    def hotkey(self, *keys):
        """Press a combination of keys."""
        pyautogui.hotkey(*keys) 
        
    def wait(self, seconds):
        """Wait for a specified number of seconds."""
        time.sleep(seconds)
        
    def screenshot_region(self, region, save_path):
        """Take a screenshot of a specific region."""
        screenshot = pyautogui.screenshot(region=region)
        screenshot.save(save_path)
        
    def scroll(self, clicks):
        """Scroll the mouse wheel."""
        pyautogui.scroll(clicks)
        
# Example usage:  
agent = GUIAgent()

agent.find_text_on_screen("Code")