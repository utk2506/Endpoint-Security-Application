
import json
import ssl
from urllib import request, error

# Mock agent config
base_url = "https://localhost:8000"
device_id = "4fbeb576-2ba6-4f89-a809-3018e170d8ff"
agent_version = "1.1.8"

# SSL context as per agent
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

def test_api():
    url = f"{base_url}/agent/version?device_id={device_id}&current_version={agent_version}"
    req = request.Request(url)
    req.add_header('X-Agent-Version', agent_version)
    
    # Try with and without trailing slash or other small variations
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
    test_api()
