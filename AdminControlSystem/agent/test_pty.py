
try:
    from pywinpty import PtyProcess, Backend
    import os
    import time

    print("Import successful. Attempting spawn...")
    ps_path = r"C:\Windows\System32\cmd.exe"
    proc = PtyProcess.spawn([ps_path], backend=Backend.WinPTY, cwd="C:\\")
    print(f"Spawned! PID: {proc.pid}")
    
    time.sleep(1)
    if proc.isalive():
        print("Process is alive. Reading output...")
        data = proc.read(1024)
        print(f"Read {len(data)} chars: {data[:100]!r}")
    else:
        print("Process died immediately.")
    
    proc.terminate()
    print("Test complete.")
except Exception as e:
    print(f"FAILED: {e}")
except BaseException as e:
    print(f"CRITICAL: {e}")
