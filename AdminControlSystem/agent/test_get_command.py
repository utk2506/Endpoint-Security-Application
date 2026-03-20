
import json
import ssl
from urllib import request, error

base_url = "https://localhost:8000"
device_id = "4fbeb576-2ba6-4f89-a809-3018e170d8ff"

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

def test_get_command():
    url = f"{base_url}/get_command/{device_id}"
    req = request.Request(url)
    print(f"Calling {url}...")
    try:
        with request.urlopen(req, timeout=10, context=ssl_context) as res:
            print(f"Status: {res.status}")
            print(f"Body: {res.read().decode('utf-8')}")
    except error.HTTPError as e:
        print(f"HTTPError: {e.code}")
        print(f"Detail: {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_get_command()
