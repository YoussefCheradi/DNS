import pyautogui
import time

pyautogui.FAILSAFE = False

print("Bouge la souris sur le bouton solver dans 5 secondes...")
for i in range(5, 0, -1):
    print(f"  {i}...")
    time.sleep(1)

x, y = pyautogui.position()
print(f"  -> Coordonnees : x={x}, y={y}")