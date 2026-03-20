import requests

try:
    # Need to find the token or bypass if it requires auth
    # For a quick test, let's just do a GET without auth to see if it is 401/403 OR 404!
    # If it is 404, the route does not exist (server needs restart).
    # If it's 401/403, the route exists but is protected correctly.
    r = requests.get("https://127.0.0.1:8000/api/v1/activity/stats", verify=False)
    print(f"Status Code: {r.status_code}")
    print(f"Response: {r.text[:200]}")
except Exception as e:
    print(f"Error connecting: {e}")
