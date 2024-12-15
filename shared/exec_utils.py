import subprocess
import os
import signal
import sys
import atexit


def exec_grouping_subprocesses(cmd, timeout=None, **kwargs):
    """Run a command with a process group for child processes so that they can be killed
    when the main process exits (mostly due to timeout). This is needed because make4ht
    starts LaTeX as a subprocess that doesn't die when the parent is killed, leading to
    stuck 100% CPU usage on timeout and weirdness where LaTeX can't be ctrl+c killed.

    Should hopefully serve as a drop-in replacement for `subprocess.call()`.

    Args:
        cmd: Command to run (string or list)
        timeout: Execution time limit to enforce, in seconds
        **kwargs: Additional arguments to pass to subprocess.call
    """
    if os.name == "posix":  # Unix-like systems
        # Create a new process group
        kwargs.setdefault("preexec_fn", os.setsid)

        def cleanup():
            try:  # Kill the entire process group
                os.killpg(process.pid, signal.SIGKILL)
            except:
                pass

    else:  # Windows
        # Create a new process group
        kwargs.setdefault("creationflags", subprocess.CREATE_NEW_PROCESS_GROUP)

        def cleanup():
            try:  # Kill process tree on Windows (not well tested)
                subprocess.call(["taskkill", "/F", "/T", "/PID", str(process.pid)])
            except:
                pass

    atexit.register(cleanup)

    try:
        process = subprocess.Popen(cmd, **kwargs)
        process.wait(timeout=timeout)
        return process.returncode
    except:
        cleanup()
        raise
    finally:  # Unregister cleanup handler
        atexit.unregister(cleanup)
        cleanup()
