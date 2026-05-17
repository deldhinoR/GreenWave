import requests

url = "https://shortwave-stick-balmy.ngrok-free.dev/api/sumo/traffic/3"

try:
    response = requests.get(url, timeout=5)

    print("Status:", response.status_code)

    if response.status_code == 200:
        data = response.json()
        print(data)
    else:
        print("Error:", response.text)

except Exception as e:
    print("Connection error:", e)

