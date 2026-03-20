
import asyncio
import websockets
import ssl
import os

ws_url = "wss://localhost:8000/ws/agent/4fbeb576-2ba6-4f89-a809-3018e170d8ff"
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

async def test_ws():
    print(f"Connecting to {ws_url}...")
    try:
        async with websockets.connect(ws_url, ssl=ssl_context) as ws:
            print("Connected!")
            # Send a test ping
            await ws.send("heartbeat from tester")
            print("Sent heartbeat.")
            # Wait for 2 seconds
            await asyncio.sleep(2)
            print("Done.")
    except Exception as e:
        print(f"WS Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_ws())
