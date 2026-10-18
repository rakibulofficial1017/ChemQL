import argparse
import ast
import atexit
import contextlib
from fractions import Fraction
from functools import reduce
import io
import json
import math
from math import gcd
import os
from pathlib import Path
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.styles import Style
from prompt_toolkit.completion import Completer, Completion
import queue
import re
import shlex
import subprocess
import sys
import select
import time
import threading
import uuid
import urllib.parse
import urllib.request
import urllib.error


__all__ = [
    "ChemQLError",
    "Element",
    "Molecule",
    "Reaction",
    "ReturnTable",
    "Unknown",
    "balance_stoichiometry",
    "execute_query",
    "execute_query_text",
    "ChemQLQuery",
    "search",
    "union",
    "intersection",
    "__version__"
]

__version__ = "1.2.6"

# Persistent preprocessor/function state for the current ChemQL session.
DEFINITIONS = {}
FUNCTIONS = {}
MACROS = {}
EXECUTION_HISTORY = []
_DEFINITION_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_NO_RETURN = object()

def _expand_definitions(line):
    """Replace @NAME literally, including inside strings, using current definitions."""
    if not DEFINITIONS:
        return line
    pattern = re.compile(r"@(" + _DEFINITION_NAME + r")")
    # One substitution pass only: replacement text is not recursively expanded.
    return pattern.sub(lambda match: DEFINITIONS.get(match.group(1), match.group(0)), line)

def _split_function_arguments(source):
    """Split comma-separated arguments while respecting nested delimiters and strings."""
    args, start = [], 0
    quote = None
    escaped = False
    round_depth = square_depth = curly_depth = double_curly_depth = 0
    i = 0
    while i < len(source):
        ch = source[i]
        if quote is not None:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
        elif source.startswith("{{", i):
            double_curly_depth += 1
            i += 2
            continue
        elif source.startswith("}}", i) and double_curly_depth:
            double_curly_depth -= 1
            i += 2
            continue
        elif not double_curly_depth:
            if ch == "(": round_depth += 1
            elif ch == ")": round_depth = max(0, round_depth - 1)
            elif ch == "[": square_depth += 1
            elif ch == "]": square_depth = max(0, square_depth - 1)
            elif ch == "{": curly_depth += 1
            elif ch == "}": curly_depth = max(0, curly_depth - 1)
            elif ch == "," and not (round_depth or square_depth or curly_depth):
                args.append(source[start:i].strip())
                start = i + 1
        i += 1
    tail = source[start:].strip()
    if tail or source.strip():
        args.append(tail)
    return args
def is_block_header(line):
    """Return True only for actual ChemQL block headers."""
    if not (line.startswith("[") and line.endswith("]")):
        return False

    code = line[1:-1].strip()

    return (
        code.startswith("if ")
        or code.startswith("for ")
        or code.startswith("while ")
    )

def _call_function(name, arguments):
    """Call a ChemQL function, including let assignments and block syntax."""
    if name not in FUNCTIONS:
        raise NameError(f"Unknown ChemQL function `{name}`")

    values = [evaluate_python(arg) for arg in arguments]
    definition = FUNCTIONS[name]

    saved_globals = python_globals.copy()
    saved_chemql_variables = CHEMQL_VARIABLES.copy()

    had_arguments = "arguments" in python_globals
    saved_arguments = python_globals.get("arguments")

    # Expose only the supplied arguments.
    python_globals["arguments"] = list(values)

    def substitute_parameters(source):
        """Replace \\1, \\2, etc. without corrupting \\10 or longer indices."""
        return re.sub(
            r"\\(\d+)",
            lambda match: (
                repr(values[int(match.group(1)) - 1])
                if 0 < int(match.group(1)) <= len(values)
                else match.group(0)
            ),
            source,
        )

    def normalize_let_line(source):
        """Translate let name = expression into a Python assignment."""
        match = re.fullmatch(
            r"\s*let\s+([A-Za-z_]\w*)\s*=\s*(.*?)\s*",
            source,
        )

        if not match:
            return source

        variable, expression = match.groups()
        expression = substitute_parameters(expression)
        expression = _expand_definitions(expression)

        # Translate simple ChemQL [variable] expressions into (variable).
        expression = re.sub(
            r"\[\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\]",
            r"(\1)",
            expression,
        )

        return f"[{variable} = {expression}]"

    def execute_function_lines(lines):
        """Execute function statements and propagate return values."""
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            if not line:
                i += 1
                continue

            # Multiline Python block.
            if line == "[[[":
                block = []
                i += 1

                while i < len(lines) and lines[i].strip() != "]]]":
                    source_line = substitute_parameters(lines[i])
                    source_line = _expand_definitions(source_line)
                    block.append(source_line)
                    i += 1

                if i >= len(lines):
                    raise SyntaxError(
                        f"Missing `]]]` in function `{name}`"
                    )

                evaluate_python("\n".join(block))
                i += 1
                continue

            # Recognize block headers generically, while excluding
            # closing and branch markers from being treated as headers.
            # generic_header = re.match(
            #     r"^\[\s*(?!endblock\b|else\b|elif\b)"
            #     r"[A-Za-z_]\w*\b.*\]\s*$",
            #     line,
            # )

            if is_block_header(line):
                end = find_endblock(lines, i + 1)

                block_body = [
                    normalize_let_line(substitute_parameters(source_line))
                    for source_line in lines[i + 1:end]
                ]

                code = line[1:-1].strip()

                # Function parameters must also be substituted in block
                # headers, e.g. [for i in range(2, \1 + 1)].
                resolved_header = (
                    "["
                    + _expand_definitions(substitute_parameters(code))
                    + "]"
                )

                if code.startswith("for "):
                    execute_for_block(resolved_header, block_body)

                elif code.startswith("while "):
                    execute_while_block(resolved_header, block_body)

                elif code.startswith("if "):
                    # Expand parameters and definitions before evaluating.
                    condition = code[3:].strip()
                    condition = substitute_parameters(condition)
                    condition = _expand_definitions(condition)

                    # Find the top-level else branch.
                    else_index = next(
                        (
                            j
                            for j, source_line in enumerate(block_body)
                            if source_line.strip() == "[else]"
                        ),
                        None,
                    )

                    if evaluate_python(condition):
                        selected_body = (
                            block_body
                            if else_index is None
                            else block_body[:else_index]
                        )
                    else:
                        selected_body = (
                            []
                            if else_index is None
                            else block_body[else_index + 1:]
                        )

                    # Execute only the selected branch. A return exits
                    # this function immediately.
                    result = execute_function_lines(selected_body)

                    if result is not _NO_RETURN:
                        return result

                else:
                    raise SyntaxError(
                        f"Unsupported function block `{code}`"
                    )

                i = end + 1
                continue

            if line == "[endblock]":
                raise SyntaxError(
                    f"Unexpected `[endblock]` in function `{name}`"
                )

            # Handle return statements inside the function.
            if re.match(r"^return\b", line):
                expression = re.sub(r"^return\b", "", line, count=1).strip()

                if expression.startswith("[") and expression.endswith("]"):
                    expression = expression[1:-1].strip()

                expression = substitute_parameters(expression)
                expression = _expand_definitions(expression)

                return evaluate_python(expression) if expression else None

            normalized = normalize_let_line(line)

            if normalized != line:
                evaluate_python(normalized[1:-1])
            elif line.startswith("[") and line.endswith("]"):
                expression = line[1:-1].strip()
                expression = substitute_parameters(expression)
                expression = _expand_definitions(expression)
                evaluate_python(expression)
            else:
                expression = substitute_parameters(line)
                expression = _expand_definitions(expression)
                evaluate_python(expression)

            i += 1

        return _NO_RETURN

    try:
        result = execute_function_lines(definition["body"])
        return None if result is _NO_RETURN else result

    finally:
        # Restore the caller's namespaces.
        python_globals.clear()
        python_globals.update(saved_globals)

        CHEMQL_VARIABLES.clear()
        CHEMQL_VARIABLES.update(saved_chemql_variables)

        if had_arguments:
            python_globals["arguments"] = saved_arguments
        else:
            python_globals.pop("arguments", None)

def _expand_function_calls(text):
    """Expand function calls of the form name{arg1, arg2} in query text."""
    # This pass is only for top-level query expressions, not arbitrary strings.
    # The scanner preserves quoted strings and resolves innermost calls first.
    for _ in range(100):
        changed = False
        quote = None
        escaped = False
        i = 0
        while i < len(text):
            ch = text[i]
            if quote is not None:
                if escaped: escaped = False
                elif ch == "\\": escaped = True
                elif ch == quote: quote = None
                i += 1
                continue
            if ch in ("'", '"'):
                quote = ch; i += 1; continue
            match = re.match(r"([A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)?)\{", text[i:])
            if match:
                name = match.group(1)
                if name in FUNCTIONS:
                    opening = i + match.end() - 1
                    end = find_matching(text, opening, "{", "}")
                    args = _split_function_arguments(text[opening + 1:end])
                    value = _call_function(name, args)
                    replacement = repr(value) if isinstance(value, str) else ("None" if value is None else str(value))
                    text = text[:i] + replacement + text[end + 1:]
                    changed = True
                    break
            i += 1
        if not changed:
            return text
    raise SyntaxError("Function expansion exceeded 100 levels (possible recursion)")


_shell_process = None
_shell_master_fd = None
_shell_prompt_ready = False
_shell_output_streamed = False
_shell_output_queue = None
_shell_reader_thread = None
_shell_script_path = None
_shell_prompt = f"__CHEMQL_PROMPT_{uuid.uuid4().hex}__"

def get_shell():
    """Return the persistent OS shell process for the current platform."""
    global _shell_process, _shell_master_fd, _shell_prompt_ready
    global _shell_output_queue, _shell_reader_thread, _shell_script_path

    if _shell_process is not None and _shell_process.poll() is None:
        return _shell_process

    # Clean up any stale shell/PTY left by an interrupted command.
    close_shell()

    if os.name == "nt":
        # PowerShell reads its program from a file, leaving stdin available for
        # the command/marker protocol and commands such as Read-Host.
        import tempfile

        setup = r'''$ErrorActionPreference = 'Continue'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::Out.WriteLine('__CHEMQL_READY__')
[Console]::Out.Flush()

while ($true) {
    # One physical input line per request avoids command/marker line desync.
    $request = [Console]::In.ReadLine()
    if ($null -eq $request) { break }

    $separatorIndex = $request.IndexOf('|')
    if ($separatorIndex -le 0) {
        [Console]::Out.WriteLine('CHEMQL_PROTOCOL_ERROR: malformed request')
        [Console]::Out.Flush()
        continue
    }

    $marker = $request.Substring(0, $separatorIndex)
    $encodedCommand = $request.Substring($separatorIndex + 1)

    try {
        $commandText = [System.Text.Encoding]::UTF8.GetString(
            [System.Convert]::FromBase64String($encodedCommand)
        )
        if ([string]::IsNullOrWhiteSpace($commandText)) {
            [Console]::Out.WriteLine('ChemQL received an empty PowerShell command.')
        }
        else {
            # Invoke-Expression runs in this persistent script scope, preserving
            # PowerShell variables between ChemQL requests. Format pipeline
            # output explicitly for each request; otherwise PowerShell's default
            # formatting subsystem can defer table output until the next request,
            # making commands such as Get-Location appear blank or duplicated.
            $formattedOutput = Invoke-Expression -Command $commandText | Out-String -Width 4096
            if (-not [string]::IsNullOrEmpty($formattedOutput)) {
                [Console]::Out.Write($formattedOutput)
            }
        }
    }
    catch {
        [Console]::Out.WriteLine($_.ToString())
    }
    finally {
        [Console]::Out.WriteLine($marker)
        [Console]::Out.Flush()
    }
}
''' # I have no idea what this is, this is code I wrote today at 4:00AM but it somehow works
    # reminder to future self to not touch this
        fd, _shell_script_path = tempfile.mkstemp(prefix="chemql_shell_", suffix=".ps1")
        try:
            with os.fdopen(fd, "w", encoding="ascii", newline="\n") as script_file:
                script_file.write(setup)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(_shell_script_path)
            except OSError:
                pass
            _shell_script_path = None
            raise

        _shell_process = subprocess.Popen(
            ["powershell.exe", "-NoLogo", "-NoProfile",
             "-ExecutionPolicy", "Bypass", "-File", _shell_script_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        output_queue = queue.Queue()
        _shell_output_queue = output_queue
        process = _shell_process

        def read_output():
            try:
                while True:
                    character = process.stdout.read(1)  # type: ignore
                    if not character:
                        break
                    output_queue.put(character)
            except (OSError, ValueError):
                pass
            finally:
                output_queue.put(None)

        _shell_reader_thread = threading.Thread(target=read_output, daemon=True)
        _shell_reader_thread.start()

        # Wait briefly for the PowerShell script to confirm it started. This
        # prevents the first request from racing process startup and diagnoses
        # startup failures instead of hanging later while waiting for a marker.
        ready_text = ""
        ready_deadline = time.monotonic() + 5
        while "__CHEMQL_READY__" not in ready_text:
            remaining = ready_deadline - time.monotonic()
            if remaining <= 0:
                startup_output = ready_text.replace("\\r\\n", "\\n").strip()
                close_shell()
                raise RuntimeError(
                    "PowerShell request loop did not start within 5 seconds."
                    + (f" Output: {startup_output}" if startup_output else "")
                )
            try:
                character = output_queue.get(timeout=min(0.1, remaining))
            except queue.Empty:
                if _shell_process.poll() is not None:
                    raise RuntimeError(
                        "PowerShell exited during startup with code "
                        f"{_shell_process.returncode}."
                    )
                continue
            if character is None:
                raise RuntimeError("PowerShell closed its output during startup.")
            ready_text += character
        ready_pos = ready_text.find("__CHEMQL_READY__")
        # Any text before the readiness token is startup diagnostics. It is
        # not command output and should not leak into the first request.
        startup_extra = ready_text[:ready_pos]
        if startup_extra.strip():
            # Preserve startup diagnostics for the next request to display.
            for char in startup_extra:
                output_queue.put(char)

        # Windows PowerShell uses the explicit command/marker protocol above.
        # Do not run the POSIX PTY prompt handshake below: it waits for a shell
        # prompt that this non-interactive PowerShell script intentionally has
        # disabled, causing get_shell() to hang before the first command.
        return _shell_process

    else:
        # Leave the existing POSIX implementation unchanged.
        import fcntl
        import pty
        import termios

        master_fd, slave_fd = pty.openpty()
        attrs = termios.tcgetattr(slave_fd)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)

        def attach_controlling_terminal():
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

        try:
            _shell_process = subprocess.Popen(
                ["bash", "--noprofile", "--norc"],
                stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                close_fds=True, start_new_session=True,
                preexec_fn=attach_controlling_terminal,
                env={**os.environ, "PS1": _shell_prompt, "PS2": ""},
            )
            _shell_master_fd = master_fd
            _shell_prompt_ready = False
        except Exception:
            os.close(master_fd)
            raise
        finally:
            os.close(slave_fd)

    return _shell_process

def _run_shell_command_posix(command, marker=None):
    """Run a command through the persistent PTY and forward keyboard input.

    A unique shell prompt marks command completion. Unlike appending an `echo`
    marker to stdin, this does not accidentally feed that marker to commands
    such as `read -p` that consume keyboard input.
    """
    global _shell_prompt_ready, _shell_output_streamed
    _shell_output_streamed = False
    shell = get_shell()
    master_fd = _shell_master_fd
    if master_fd is None:
        return "Shell error: pseudo-terminal was not initialized."

    prompt_bytes = _shell_prompt.encode()

    def wait_for_prompt(forward_keyboard=False):
        global _shell_output_streamed
        collected = bytearray()
        streamed_pos = 0
        stdin_fd = None
        try:
            if forward_keyboard and sys.stdin is not None and sys.stdin.isatty():
                stdin_fd = sys.stdin.fileno()
        except (AttributeError, OSError, ValueError):
            stdin_fd = None

        while True:
            readers = [master_fd]
            if stdin_fd is not None:
                readers.append(stdin_fd) #type:ignore
            try:
                ready, _, _ = select.select(readers, [], [])
            except KeyboardInterrupt:
                # ChemQL owns the user's terminal, so forward Ctrl-C into the
                # child PTY to interrupt its foreground command.
                try:
                    os.write(master_fd, b"\x03")
                except OSError:
                    pass
                continue

            if stdin_fd is not None and stdin_fd in ready:
                try:
                    typed = os.read(stdin_fd, 4096)
                except OSError:
                    typed = b""
                if typed:
                    try:
                        os.write(master_fd, typed)
                    except OSError:
                        stdin_fd = None
                else:
                    stdin_fd = None

            if master_fd in ready:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    chunk = b""
                if not chunk:
                    return None
                collected.extend(chunk)
                prompt_pos = collected.find(prompt_bytes)
                if forward_keyboard:
                    # Stream command output immediately so prompts such as
                    # `read -p` are visible while the command waits for input.
                    # Hold back only a suffix that might be the start of PS1.
                    safe_end = prompt_pos if prompt_pos >= 0 else len(collected)
                    if prompt_pos < 0:
                        max_overlap = min(len(prompt_bytes) - 1, len(collected))
                        overlap = 0
                        for size in range(max_overlap, 0, -1):
                            if collected.endswith(prompt_bytes[:size]):
                                overlap = size
                                break
                        safe_end -= overlap
                    if safe_end > streamed_pos:
                        visible = bytes(collected[streamed_pos:safe_end])
                        try:
                            sys.stdout.write(visible.decode(errors="replace"))
                            sys.stdout.flush()
                            _shell_output_streamed = True
                        except (OSError, UnicodeError):
                            pass
                        streamed_pos = safe_end
                if prompt_pos >= 0:
                    before = bytes(collected[:prompt_pos])
                    # Strip terminal CRs while preserving meaningful output.
                    return before.decode(errors="replace").replace("\r\n", "\n").rstrip("\r\n ")

    # Bash emits a prompt immediately on startup. Consume it before submitting
    # the first command; after each command the same prompt signals completion.
    if not _shell_prompt_ready:
        initial = wait_for_prompt(forward_keyboard=False)
        if initial is None:
            close_shell()
            return "Shell session terminated."
        _shell_prompt_ready = True

    try:
        os.write(master_fd, (command + "\n").encode())
        result = wait_for_prompt(forward_keyboard=True)
        if result is None:
            close_shell()
            return "Shell session terminated."
        return result
    except (BrokenPipeError, OSError) as exc:
        close_shell()
        return f"Shell error: {exc}"

def _run_shell_command_windows(command):
    """Execute one command in the persistent PowerShell request loop."""
    import base64
    import msvcrt
    import uuid

    shell = get_shell()
    output_queue = _shell_output_queue
    if output_queue is None:
        return "Shell error: PowerShell output reader was not initialized."
    if shell.stdin is None:
        return "Shell error: PowerShell stdin is unavailable."

    marker = f"__CHEMQL_DONE_{uuid.uuid4().hex}__"
    encoded_command = base64.b64encode(command.encode("utf-8")).decode("ascii")
    timeout_seconds=120
    def wait_for_marker(timeout_seconds=120):
        """Collect output while streaming prompts so interactive commands remain usable."""
        global _shell_output_streamed

        collected = ""
        streamed_pos = 0
        started = time.monotonic()
        try:
            stdin_is_tty = sys.stdin is not None and sys.stdin.isatty()
        except (AttributeError, OSError, ValueError):
            stdin_is_tty = False
        pending_input = ""

        def stream_until(end):
            nonlocal streamed_pos
            global _shell_output_streamed
            if not stdin_is_tty or end <= streamed_pos:
                return
            visible = collected[streamed_pos:end]
            if visible:
                try:
                    sys.stdout.write(visible)
                    sys.stdout.flush()
                    _shell_output_streamed = True
                except (OSError, UnicodeError):
                    pass
                streamed_pos = end

        while True:
            if time.monotonic() - started > timeout_seconds:
                return (None, collected, True)

            if stdin_is_tty:
                try:
                    while msvcrt.kbhit():  # type: ignore
                        key = msvcrt.getwch()  # type: ignore
                        if key in ("\x00", "\xe0"):
                            if msvcrt.kbhit():  # type: ignore
                                msvcrt.getwch()  # type: ignore
                        elif key in ("\r", "\n"):
                            shell.stdin.write(pending_input + "\n")  # type: ignore  # text mode normalizes newlines on Windows
                            shell.stdin.flush()  # type: ignore
                            sys.stdout.write("\n")
                            sys.stdout.flush()
                            pending_input = ""
                        elif key == "\b":
                            if pending_input:
                                pending_input = pending_input[:-1]
                                sys.stdout.write("\b \b")
                                sys.stdout.flush()
                        elif key == "\x03":
                            close_shell()
                            return (None, collected, False)
                        elif key >= " " and key != "\x7f": # I have no idea what I did but it workd
                            pending_input += key
                            sys.stdout.write(key)
                            sys.stdout.flush()
                except (OSError, ValueError):
                    stdin_is_tty = False

            try:
                character = output_queue.get(timeout=0.04)
            except queue.Empty:
                if shell.poll() is not None:
                    return (None, collected, False)
                continue
            if character is None:
                return (None, collected, False)

            collected += character
            marker_pos = collected.find(marker)
            if marker_pos >= 0:
                stream_until(marker_pos)
                visible = collected[:marker_pos]
                return (
                    visible.replace("\r\n", "\n").rstrip("\r\n "),
                    collected,
                    False,
                )

            # Hold back a suffix that could be the beginning of the completion
            # marker, so protocol text is never accidentally printed.
            overlap = min(len(marker) - 1, len(collected))
            while overlap and not collected.endswith(marker[:overlap]):
                overlap -= 1
            stream_until(len(collected) - overlap)

    try:
        shell.stdin.write(marker + "|" + encoded_command + "\n")  # text mode normalizes newlines on Windows
        shell.stdin.flush()
        result, collected, timed_out = wait_for_marker()
        if timed_out:
            close_shell()
            debug = collected.replace("\r\n", "\n").rstrip()
            detail = f"PowerShell did not return its completion marker within {timeout_seconds} seconds."
            if debug:
                detail += f"\nOutput received before timeout:\n{debug}"
            else:
                detail += "\nNo output was received. The PowerShell request loop may not have started or may not be reading stdin."
            return detail
        if result is None:
            close_shell()
            return "Shell session terminated before PowerShell returned its completion marker."
        return result
    except (BrokenPipeError, OSError, ValueError) as exc:
        close_shell()
        return f"Shell error: {exc}"

def run_shell_command(command):
    global _shell_output_streamed

    command = (
        command.replace("\r\n", "\n")
        .replace("\r", "\n")
        .rstrip("\n")
    )

    try:
        if os.name == "nt":
            stripped = command.strip()

            if stripped.casefold() in {
                "powershell",
                "powershell.exe",
                "pwsh",
                "pwsh.exe",
            }:
                return (
                    "ChemQL already uses PowerShell on Windows; "
                    "run the command directly instead of starting "
                    "a nested shell."
                )

            # Clear the terminal without sending Clear-Host to PowerShell.
            if stripped.casefold() in {
                "clear",
                "cls",
                "clear-host",
            }:
                os.system("cls")
                return ""

            _shell_output_streamed = False
            return _run_shell_command_windows(command)

        # POSIX behavior remains unchanged.
        return _run_shell_command_posix(command)

    except KeyboardInterrupt:
        close_shell()
        return "Shell command interrupted. Shell session was reset."

def close_shell():
    """Clean up the persistent shell and its pseudo-terminal on exit."""
    global _shell_process, _shell_master_fd, _shell_prompt_ready
    global _shell_output_queue, _shell_reader_thread, _shell_script_path

    if _shell_process is not None:
        if _shell_process.poll() is None:
            try:
                _shell_process.terminate()
                _shell_process.wait(timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    _shell_process.kill()
                    _shell_process.wait(timeout=2)
                except (subprocess.TimeoutExpired, OSError):
                    pass
        _shell_process = None

    if _shell_master_fd is not None:
        try:
            os.close(_shell_master_fd)
        except OSError:
            pass
        _shell_master_fd = None
    _shell_prompt_ready = False
    _shell_output_queue = None
    _shell_reader_thread = None

    if _shell_script_path is not None:
        try:
            os.unlink(_shell_script_path)
        except OSError:
            pass
        _shell_script_path = None


atexit.register(close_shell)

class Unknown:
    """Represents a Chemql query result that cannot be resolved to a known object."""

    __slots__ = ("value",)

    def __init__(self, value=None):
        self.value = value

    def __str__(self):
        return str(self.value) if self.value is not None else "Unknown"

    def __repr__(self):
        return repr(self.value) if self.value is not None else "Unknown"


class ChemQLError(Exception):
    def __init__(self, message, position=None, length=1):
        super().__init__(message)
        self.position = position
        self.length = length


def format_error(message, text=None, position=None, length=1):
    output = f"Error: {message}"

    if text is not None and position is not None:
        output += f"\n{text}\n{' ' * position}{'^' * max(1, length)}"

    return output


def token_positions(text):
    positions = []
    i = 0
    while i < len(text):
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break

        start = i
        quote = None
        escaped = False
        while i < len(text):
            char = text[i]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif quote:
                if char == quote:
                    quote = None
            elif char in ("\'", '"'):
                quote = char
            elif char.isspace():
                break
            i += 1
        positions.append((start, max(1, i - start)))
    return positions


def error_position(positions, index):
    if 0 <= index < len(positions):
        return positions[index]
    return (None, 1)
from prompt_toolkit.shortcuts import choice

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

with (DATA_DIR / "PeriodicTableJSON.json").open("r", encoding="utf-8") as f:
    elements = json.load(f)
with (DATA_DIR / "Molecules.json").open("r", encoding="utf-8") as f:
    molecules = json.load(f)
with (DATA_DIR / "Reactions.json").open("r", encoding="utf-8") as f:
    reactions = json.load(f)
with (DATA_DIR / "MoleculeBonds.json").open("r", encoding="utf-8") as f:
    moleculeBonds = json.load(f)
with (DATA_DIR / "BondEnergies.json").open("r", encoding="utf-8") as f:
    bondEnergies = json.load(f)

operators = {"has", "like", "like!", "likep", "=", "!=", ">", "<", ">=", "<="}

queryOperations = {"sort", "limit", "count"}

def like_match(value, pattern, case_sensitive=False):
    regex = ""
    i = 0

    while i < len(pattern):
        char = pattern[i]

        if char == "\\":
            i += 1

            if i >= len(pattern):
                raise ValueError(
                    "Escape character at end of pattern"
                )

            regex += re.escape(pattern[i])

        elif char == "*":
            regex += ".*"

        elif char == "%":
            regex += "[0-9]*"

        elif char == "&":
            regex += "[A-Za-z]*"

        elif char == "_":
            regex += "."

        elif char == "#":
            regex += "[0-9]"

        elif char == "?":
            regex += "[A-Za-z]"

        else:
            regex += re.escape(char)

        i += 1

    flags = 0 if case_sensitive else re.IGNORECASE

    return re.fullmatch(regex, value, flags) is not None


def normal_round(num, p=0):
    num1 = num / 10**p
    numint = math.floor(num1)
    numfloat = num - numint
    if numfloat >= 0.5:
        return -(-numint - 1) * 10**p
    return numint * 10 ** p



class Element:
    __slots__ = ("name", "appearance", "atomic_mass", "boil", "category", "density", "discovered_by", "melt", "molar_heat", "named_by", "number", "period", "group", "phase", "source", "bohr_model_image", "bohr_model_3d", "spectral_img", "summary", "symbol", "xpos", "ypos", "wxpos", "wypos", "shells", "electron_configuration", "electron_configuration_semantic", "electron_affinity", "electronegativity_pauling", "ionization_energies", "cpk_hex", "image", "block")

    def __init__(
        self,
        name,
        appearance,
        atomic_mass,
        boil,
        category,
        density,
        discovered_by,
        melt,
        molar_heat,
        named_by,
        number,
        period,
        group,
        phase,
        source,
        bohr_model_image,
        bohr_model_3d,
        spectral_img,
        summary,
        symbol,
        xpos,
        ypos,
        wxpos,
        wypos,
        shells,
        electron_configuration,
        electron_configuration_semantic,
        electron_affinity,
        electronegativity_pauling,
        ionization_energies,
        cpk_hex,
        image,
        block,
    ):
        self.name = name
        self.appearance = appearance
        self.atomic_mass = atomic_mass
        self.boil = boil
        self.category = category
        self.density = density
        self.discovered_by = discovered_by
        self.melt = melt
        self.molar_heat = molar_heat
        self.named_by = named_by
        self.number = number
        self.period = period
        self.group = group
        self.phase = phase
        self.source = source
        self.bohr_model_image = bohr_model_image
        self.bohr_model_3d = bohr_model_3d
        self.spectral_img = spectral_img
        self.summary = summary
        self.symbol = symbol
        self.xpos = xpos
        self.ypos = ypos
        self.wxpos = wxpos
        self.wypos = wypos
        self.shells = shells
        self.electron_configuration = electron_configuration
        self.electron_configuration_semantic = electron_configuration_semantic
        self.electron_affinity = electron_affinity
        self.electronegativity_pauling = electronegativity_pauling
        self.ionization_energies = ionization_energies
        self.cpk_hex = cpk_hex
        self.image = image
        self.block = block

    def __getitem__(self, key):
        return getattr(self, key)

    def __str__(self):
        if self.cpk_hex:
            r = int(self.cpk_hex[0:2], 16)
            g = int(self.cpk_hex[2:4], 16)
            b = int(self.cpk_hex[4:6], 16)
        else:
            r = g = b = 255

        return (
            f"\033[38;2;{r};{g};{b}m"
            f" ______________\n"
            f"|     {self.number:^3}      |\n"
            f"|              |\n"
            f"|     {self.symbol:^3}      |\n"
            f"|              |\n"
            f"|     {normal_round(self.atomic_mass):^3}      |\n"
            f"|______________|"
            f"\033[0m\n"
        )
    def __repr__(self):
        return f"{self.name}"

elementKeys = ("name", "appearance", "atomic_mass", "boil", "category", "density", "discovered_by", "melt", "molar_heat", "named_by", "number", "period", "group", "phase", "source", "bohr_model_image", "bohr_model_3d", "spectral_img", "summary", "symbol", "xpos", "ypos", "wxpos", "wypos", "shells", "electron_configuration", "electron_configuration_semantic", "electron_affinity", "electronegativity_pauling", "ionization_energies", "cpk-hex", "image", "block")

ELEMENTS = [Element(*(item[key] if item[key] is not None else "" for key in elementKeys)) for item in elements["elements"]]

# No longer need the JSON structure.

ELEMENTS.pop()

class Molecule:
    __slots__ = ("name", "formula", "elements", "molecular_weight", "iupac_name", "smiles", "cid", "melting_point","boiling_point", "density", "state", "bonds", "total_bond_energy")
    def __init__(self, name, formula, elements, molecular_weight, iupac_name, smiles, cid, melting_point, boiling_point, density, state):
        self.name = name
        self.formula = formula
        self.elements = elements
        self.molecular_weight = molecular_weight
        self.iupac_name = iupac_name
        self.smiles = smiles
        self.cid = cid
        self.melting_point = melting_point
        self.boiling_point = boiling_point
        self.density = density
        self.state = state
        self.bonds = moleculeBonds.get(name, {}).get("bonds", [])
        self.total_bond_energy = sum(
            bond.get("count", 0) * bondEnergies[
                f"{'-'.join(sorted(bond['elements']))}-{bond['type']}"
            ]["energy"]
            for bond in self.bonds
        )
    def __getitem__(self, key):
        return getattr(self, key)
    def __str__(self):
        return f"{self.formula.translate(str.maketrans('0123456789', '₀₁₂₃₄₅₆₇₈₉'))} ({self.name})"

    def __repr__(self):
        return self.name

moleculeKeys = ("name", "formula", "elements", "molecular_weight", "iupac_name", "smiles", "cid", "melting_point", "boiling_point", "density", "state", "bonds", "total_bond_energy")

PUBCHEM_BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUBCHEM_VIEW_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
PUBCHEM_SERVICE_ERROR = False


def _normalize_molecule_value(value):
    """Strip surrounding quotes and whitespace from a molecule lookup."""
    if value is None:
        return ""

    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()

    return text


def _fetch_url_text(url, timeout=15, retries=2):
    """Fetch a raw text response from a URL, retrying transient failures."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ChemQL/1.0 (+https://example.invalid)",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        },
    )

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            return ""

    return ""


def _get_json(url, timeout=10, retries=3):
    """Fetch JSON from a URL with retries for transient server errors."""
    global PUBCHEM_SERVICE_ERROR

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ChemQL/1.0 (+https://example.invalid)",
            "Accept": "application/json",
        },
    )

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.load(response)
                PUBCHEM_SERVICE_ERROR = False
                return data

        except urllib.error.HTTPError as exc:
            if exc.code in (500, 502, 503, 504):
                PUBCHEM_SERVICE_ERROR = True
                if attempt < retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                return None
            PUBCHEM_SERVICE_ERROR = False
            return None

        except (
            urllib.error.URLError,
            json.JSONDecodeError,
            TimeoutError,
            OSError,
            ValueError,
        ):
            PUBCHEM_SERVICE_ERROR = True
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            return None


def _find_local_molecule(value):
    """Return a built-in molecule when the network lookup is unavailable."""
    if value is None:
        return None

    target = _normalize_molecule_value(value)
    if not target:
        return None

    normalized = target.lower()

    for molecule in MOLECULES:
        if molecule.name.lower() == normalized:
            return molecule
        if molecule.formula.lower() == normalized:
            return molecule
        if molecule.iupac_name and molecule.iupac_name.lower() == normalized:
            return molecule

    for molecule in MOLECULES:
        if molecule.name.lower().startswith(normalized):
            return molecule
        if molecule.formula.lower().startswith(normalized):
            return molecule
        if molecule.iupac_name and molecule.iupac_name.lower().startswith(normalized):
            return molecule

    return None


def _fetch_nist_molecule(value):
    """Try NIST WebBook as a fallback chemistry source."""
    target = _normalize_molecule_value(value)
    if not target:
        return None

    encoded = urllib.parse.quote(target)
    url = f"https://webbook.nist.gov/cgi/cbook.cgi?Name={encoded}&Units=SI"
    html = _fetch_url_text(url)
    if not html:
        return None

    formula_match = re.search(r"Formula\s*[:<]?[\s\n]*([A-Z][a-z]?(?:\d+)?(?:[A-Z][a-z]?(?:\d+)?)*)", html, re.I)
    weight_match = re.search(r"Molecular weight\s*[:<]?[\s\n]*([0-9]+(?:\.[0-9]+)?)", html, re.I)

    if not formula_match:
        return None

    formula = formula_match.group(1).strip()
    molecular_weight = float(weight_match.group(1)) if weight_match else 0.0

    return Molecule(
        name=target,
        formula=formula,
        elements=[],
        molecular_weight=molecular_weight,
        iupac_name="",
        smiles="",
        cid=None,
        melting_point=None,
        boiling_point=None,
        density=None,
        state=None,
    )


def fetch_external_molecule(value):
    """Try public chemistry sources once the local JSON does not contain the molecule."""
    target = _normalize_molecule_value(value)
    if not target:
        return None

    # PubChem is the first external source because it is the most complete.
    cid = _find_cid(target)
    if cid is None:
        return _fetch_nist_molecule(target)

    properties = _get_basic_properties(cid)
    if properties is None:
        return _fetch_nist_molecule(target)

    view_data = _get_view_data(cid)
    melting_point = _get_first_temperature(view_data, "Melting Point") if view_data else None
    boiling_point = _get_first_temperature(view_data, "Boiling Point") if view_data else None
    density = _get_first_density(view_data) if view_data else None
    state = _determine_state(melting_point, boiling_point, temperature=25.0) if melting_point is not None and boiling_point is not None else None

    return Molecule(
        name=target,
        formula=properties.get("MolecularFormula", ""),
        elements=[],
        molecular_weight=properties.get("MolecularWeight", 0),
        iupac_name=properties.get("IUPACName", ""),
        smiles=properties.get("SMILES", ""),
        cid=properties.get("CID", cid),
        melting_point=melting_point,
        boiling_point=boiling_point,
        density=density,
        state=state,
    )


def _find_cid(value):
    """
    Find a PubChem CID.

    Tries the input as:
    1. Chemical name
    2. Molecular formula
    """

    if value is None:
        return None

    encoded_value = urllib.parse.quote(str(value), safe="")

    # ---------------------------------------------------------
    # Try chemical name
    # ---------------------------------------------------------
    url = (
        f"{PUBCHEM_BASE_URL}/compound/name/"
        f"{encoded_value}/cids/JSON"
    )

    data = _get_json(url)

    if data:
        identifier_list = data.get("IdentifierList", {})
        cids = identifier_list.get("CID", [])
        if cids:
            return cids[0]

    # ---------------------------------------------------------
    # Try molecular formula
    # ---------------------------------------------------------
    url = (
        f"{PUBCHEM_BASE_URL}/compound/fastformula/"
        f"{encoded_value}/cids/JSON"
    )

    data = _get_json(url)

    if data:
        identifier_list = data.get("IdentifierList", {})
        cids = identifier_list.get("CID", [])
        if cids:
            return cids[0]

    return None


def _get_basic_properties(cid):
    """Get basic molecular properties from PubChem."""

    url = (
        f"{PUBCHEM_BASE_URL}/compound/cid/{cid}/property/"
        "MolecularFormula,MolecularWeight,IUPACName,SMILES/JSON"
    )

    data = _get_json(url)

    if not data:
        return None

    try:
        return data["PropertyTable"]["Properties"][0]

    except (KeyError, IndexError, TypeError):
        return None


def _get_view_data(cid):
    """
    Get the complete PUG-View record.

    PUG-View contains experimental properties such as:
    - Melting Point
    - Boiling Point
    - Density
    """

    url = (
        f"{PUBCHEM_VIEW_URL}/data/compound/{cid}/JSON"
    )

    return _get_json(url)


def _walk_sections(obj):
    """Recursively find PubChem PUG-View sections."""

    if isinstance(obj, dict):

        if "TOCHeading" in obj:
            yield obj

        for value in obj.values():
            yield from _walk_sections(value)

    elif isinstance(obj, list):

        for item in obj:
            yield from _walk_sections(item)


def _find_section(data, heading):
    """Find a PUG-View section by heading."""

    if not data:
        return None

    for section in _walk_sections(data):

        if section.get("TOCHeading", "").lower() == heading.lower():
            return section

    return None


def _extract_text(value):
    """
    Convert PubChem's nested Value structure into text.
    """

    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, list):
        return " ".join(
            text
            for item in value
            if (text := _extract_text(item))
        )

    if isinstance(value, dict):

        # Common PubChem formats
        for key in (
            "StringWithMarkup",
            "String",
            "StringValue",
        ):
            if key in value:
                text = _extract_text(value[key])

                if text:
                    return text

        for key in (
            "Number",
            "FloatValue",
        ):
            if key in value:
                return str(value[key])

        # Fallback
        return " ".join(
            text
            for item in value.values()
            if (text := _extract_text(item))
        )

    return ""


def _get_section_values(data, heading):
    """
    Get the text values reported in a PubChem section.
    """

    section = _find_section(data, heading)

    if not section:
        return []

    values = []

    for information in section.get("Information", []):

        if not isinstance(information, dict):
            continue

        value = information.get("Value")

        text = _extract_text(value)

        if text:
            values.append(text.strip())

    return values


def _parse_temperature(text):
    """
    Convert a temperature string into Celsius.

    Examples:
        "78 °C"       -> 78.0
        "78-80 °C"    -> 79.0
        "172 °F"      -> 77.777...
        "351 K"       -> 77.85

    Returns None if no temperature can be extracted.
    """

    if not text:
        return None

    # ---------------------------------------------------------
    # Find numbers
    # ---------------------------------------------------------
    numbers = re.findall(
        r"[-+]?\d+(?:\.\d+)?",
        text
    )

    if not numbers:
        return None

    values = [float(number) for number in numbers]

    # If it's a range, use the average
    value = sum(values[:2]) / min(len(values), 2)

    text_lower = text.lower()

    # ---------------------------------------------------------
    # Convert to Celsius
    # ---------------------------------------------------------
    if "°f" in text_lower or "deg f" in text_lower:
        return (value - 32) * 5 / 9

    if re.search(r"\bk\b", text_lower):
        return value - 273.15

    # Default / expected unit
    return value


def _parse_density(text):
    """
    Convert density to g/cm^3.

    Examples:
        "1.05 g/mL"  -> 1.05
        "1.05 g/cm3" -> 1.05
        "1050 kg/m3" -> 1.05
        "1.05 g/cm³" -> 1.05
    """

    if not text:
        return None

    match = re.search(
        r"[-+]?\d+(?:\.\d+)?",
        text
    )

    if not match:
        return None

    value = float(match.group(0))
    text_lower = text.lower()

    # ---------------------------------------------------------
    # Convert to g/cm^3
    # ---------------------------------------------------------

    if "kg/m3" in text_lower or "kg/m³" in text_lower:
        return value / 1000

    if "mg/ml" in text_lower:
        return value / 1000

    # g/mL and g/cm3 are numerically equivalent
    if "g/ml" in text_lower:
        return value

    if "g/cm3" in text_lower or "g/cm³" in text_lower:
        return value

    # If PubChem didn't provide a recognizable unit,
    # assume g/cm3 because that is the unit used by this app.
    return value


def _get_first_temperature(data, heading):
    """Get the first reported temperature in Celsius."""

    values = _get_section_values(data, heading)

    for value in values:

        temperature = _parse_temperature(value)

        if temperature is not None:
            return temperature

    return None


def _get_first_density(data):
    """Get the first reported density in g/cm3."""

    values = _get_section_values(data, "Density")

    for value in values:

        density = _parse_density(value)

        if density is not None:
            return density

    return None


def _determine_state(
    melting_point,
    boiling_point,
    temperature=25.0,
):
    """
    Determine physical state at 25 °C.

    Assumes approximately 1 atm pressure.
    """

    if melting_point is None or boiling_point is None:
        return None

    if temperature < melting_point:
        return "solid"

    if temperature >= boiling_point:
        return "gas"

    return "liquid"


def fetch_pubchem_molecule(value):
    """
    Look up a molecule locally, then using PubChem and fallback sources.

    `value` can be:
        - chemical name: "water"
        - molecular formula: "H2O"

    Returns:
        Molecule instance
        or None if the molecule cannot be found.
    """

    local_match = _find_local_molecule(value)
    if local_match is not None:
        return local_match

    # ---------------------------------------------------------
    # Search external chemistry sources when not in the local dataset.
    # ---------------------------------------------------------
    external_match = fetch_external_molecule(value)
    return external_match



MOLECULES = [Molecule(item["name"], item["formula"], item["elements"], item["molecular_weight"], item["iupac_name"] or "", item["smiles"] or "", item["cid"], item["melting_point"], item["boiling_point"], item["density"], item["state"]) for item in molecules]

MOLECULES_BY_FORMULA = {molecule.formula: molecule for molecule in MOLECULES}

def molecule_bond_energy(formula):
    molecule = MOLECULES_BY_FORMULA.get(formula)
    return molecule.total_bond_energy if molecule is not None else 0



class Reaction:
    __slots__ = ("id", "name", "equation", "reaction_type", "reversible", "reactants", "products", "conditions", "notes", "source")
    def __init__(self, id_, name, reaction_type, reversible, reactants, products, conditions, notes, source=""):
        self.id = id_
        self.name = name
        self.reaction_type = reaction_type
        self.reversible = reversible
        self.reactants = reactants
        self.products = products
        self.conditions = conditions
        self.notes = notes
        self.source = source
        subscript_digits = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")

        reactant_text = " + ".join(
            f"{item['stoichiometric_coefficient']} {item['molecule'].translate(subscript_digits)}"
            for item in reactants
        )
        product_text = " + ".join(
            f"{item['stoichiometric_coefficient']} {item['molecule'].translate(subscript_digits)}"
            for item in products
        )
        arrow = " ⇌ " if self.reversible is True else " → " if self.reversible is False else " = "
        self.equation = f"{reactant_text}{arrow}{product_text}"

        if reversible is not None:
            reactant_energy = sum(
                molecule_bond_energy(item["molecule"]) * item["stoichiometric_coefficient"]
                for item in reactants
            )
            product_energy = sum(
                molecule_bond_energy(item["molecule"]) * item["stoichiometric_coefficient"]
                for item in products
            )
            total_energy = reactant_energy - product_energy
            self.equation += f"\tΔH={total_energy}kJ/mol"
        if self.conditions:
            self.equation += "\nConditions:\n"
            for i in self.conditions:
                self.equation += f"\t{i}: {self.conditions[i]}\n"
    def __str__(self):
        return self.equation
    def __repr__(self):
        return self.name


REACTIONS = [Reaction(item["id"], item["name"], item["reaction_type"], item["reversible"], item["reactants"], item["products"], item["conditions"], item["notes"], item.get("source", "")) for item in reactions]
reactionKeys = ("id", "name", "equation", "reaction_type", "reversible", "reactants", "products", "conditions", "notes", "source")
del elements
del reactions
del molecules


def _formula_counts(formula):
    if not isinstance(formula, str) or not formula:
        raise ValueError("Chemical formulas must be non-empty strings")
    symbols = {element.symbol for element in ELEMENTS}

    def parse_group(index, nested=False):
        counts = {}
        while index < len(formula):
            char = formula[index]
            if char == ")":
                if not nested:
                    raise ValueError(f"Unmatched closing parenthesis in formula `{formula}`")
                return counts, index
            if char == "(":
                group, index = parse_group(index + 1, True)
                if index >= len(formula) or formula[index] != ")":
                    raise ValueError(f"Unclosed parenthesis in formula `{formula}`")
                index += 1
                match = re.match(r"\d+", formula[index:])
                multiplier = int(match.group()) if match else 1
                if multiplier <= 0:
                    raise ValueError(f"Invalid atom count in formula `{formula}`")
                if match:
                    index += len(match.group())
                for symbol, amount in group.items():
                    counts[symbol] = counts.get(symbol, 0) + amount * multiplier
                continue
            if not char.isupper():
                raise ValueError(f"Invalid chemical formula `{formula}`")
            end = index + 1
            if end < len(formula) and formula[end].islower():
                end += 1
            symbol = formula[index:end]
            if symbol not in symbols:
                raise ValueError(f"Unknown element `{symbol}` in formula `{formula}`")
            index = end
            match = re.match(r"\d+", formula[index:])
            amount = int(match.group()) if match else 1
            if amount <= 0:
                raise ValueError(f"Invalid atom count in formula `{formula}`")
            if match:
                index += len(match.group())
            counts[symbol] = counts.get(symbol, 0) + amount
        if nested:
            raise ValueError(f"Unclosed parenthesis in formula `{formula}`")
        return counts, index

    counts, end = parse_group(0)
    if end != len(formula) or not counts:
        raise ValueError(f"Invalid chemical formula `{formula}`")
    return counts


def _stoichiometric_species(side):
    if isinstance(side, str):
        species = [item.strip() for item in side.split("+")]
    else:
        species = [str(item).strip() for item in side]
    if not species or any(not item for item in species):
        raise ValueError("Both sides of a reaction must contain molecules")
    return species


def balance_stoichiometry(reactants, products, reversible=None):
    """Balance a reaction and return it as a :class:`Reaction`."""
    reactant_formulas = _stoichiometric_species(reactants)
    product_formulas = _stoichiometric_species(products)
    formulas = reactant_formulas + product_formulas
    formulas_by_element = [_formula_counts(formula) for formula in formulas]
    elements = list(dict.fromkeys(
        element for counts in formulas_by_element for element in counts
    ))
    matrix = [
        [
            Fraction(counts.get(element, 0) * (1 if index < len(reactant_formulas) else -1))
            for index, counts in enumerate(formulas_by_element)
        ]
        for element in elements
    ]

    pivot_columns = []
    pivot_row = 0
    for column in range(len(formulas)):
        selected = next(
            (row for row in range(pivot_row, len(matrix)) if matrix[row][column]),
            None,
        )
        if selected is None:
            continue
        matrix[pivot_row], matrix[selected] = matrix[selected], matrix[pivot_row]
        divisor = matrix[pivot_row][column]
        matrix[pivot_row] = [value / divisor for value in matrix[pivot_row]]
        for row in range(len(matrix)):
            if row == pivot_row or not matrix[row][column]:
                continue
            factor = matrix[row][column]
            matrix[row] = [
                value - factor * pivot
                for value, pivot in zip(matrix[row], matrix[pivot_row])
            ]
        pivot_columns.append(column)
        pivot_row += 1
        if pivot_row == len(matrix):
            break

    free_columns = [
        column for column in range(len(formulas)) if column not in pivot_columns
    ]
    if len(free_columns) != 1:
        raise ValueError("Reaction does not have a unique stoichiometric balance")
    coefficients = [Fraction(0) for _ in formulas]
    free_column = free_columns[0]
    coefficients[free_column] = Fraction(1)
    for row, column in enumerate(pivot_columns):
        coefficients[column] = -matrix[row][free_column]
    if all(value < 0 for value in coefficients):
        coefficients = [-value for value in coefficients]
    if any(value <= 0 for value in coefficients):
        raise ValueError("Reaction cannot be balanced with positive coefficients")

    denominator = 1
    for coefficient in coefficients:
        denominator = denominator * coefficient.denominator // gcd(
            denominator, coefficient.denominator
        )
    integer_coefficients = [
        int(coefficient * denominator) for coefficient in coefficients
    ]
    common_divisor = reduce(gcd, integer_coefficients)
    integer_coefficients = [value // common_divisor for value in integer_coefficients]
    participants = [
        {
            "molecule": formula,
            "stoichiometric_coefficient": coefficient,
        }
        for formula, coefficient in zip(formulas, integer_coefficients)
    ]
    split_at = len(reactant_formulas)
    return Reaction(
        "BALANCED",
        "Balanced reaction",
        "balanced",
        reversible,
        participants[:split_at],
        participants[split_at:],
        {},
        "",
    )


def _execute_balance_command(text):
    text = text.split("//", 1)[0].rstrip()
    match = re.fullmatch(
        r"\s*balance\s+(.+?)\s*(<->|->)\s*(.+?)\s*",
        text,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError("Usage: balance <reactants> ->|<-> <products>")
    reactants, arrow, products = match.groups()
    reversible = arrow == "<->"
    return balance_stoichiometry(reactants, products, reversible)



def queryElement(key, func, value, *params):
    if key not in elementKeys:
        return f"There is no key `{key}`"

    for element in ELEMENTS:
        if getattr(element[key], func)(value, *params):
            return element

    return f"Turns out no element has a {key} of {value}"


def queryElementLast(key, func, value, *params):
    if key not in elementKeys:
        raise KeyError(f"There is no key `{key}`")

    for element in reversed(ELEMENTS):
        if getattr(element[key], func)(value, *params):
            return element

    return f"Turns out no element has a {key} of {value}"


def queryElementAll(key, func, value, *params):
    if key not in elementKeys:
        raise KeyError(f"There is no key `{key}`")

    found = False

    for element in ELEMENTS:
        if getattr(element[key], func)(value, *params):
            found = True
            yield element

    if not found:
        return

class ReturnTable(dict):
    """Dictionary result that prints as a table in the REPL."""

    def __str__(self):
        return format_return_table(self)


def format_return_table(data):
    if not data:
        return ""

    columns = list(data.keys())
    rows = []
    row_count = max((len(data[column]) for column in columns), default=0)

    for i in range(row_count):
        rows.append([str(data[column][i]) if i < len(data[column]) else "" for column in columns])

    widths = [max(len(str(column)), *(len(row[index]) for row in rows)) for index, column in enumerate(columns)]

    header = "  ".join(
        str(column).upper().ljust(widths[index])
        for index, column in enumerate(columns)
    ).rstrip()

    separator = ''.join("─" * i for i  in widths) + "──" *(len(data.keys()) - 1)

    body = ["  ".join(row[index].ljust(widths[index]) for index in range(len(columns))).rstrip() for row in rows]

    return "\n".join([header, separator, *body])


def project_results(results, attributes):
    """Return one column as a 1D list, or multiple columns as a dict of 1D lists."""

    if len(attributes) == 1:
        return [getattr(item, attributes[0]) for item in results]

    return ReturnTable({attribute: [getattr(item, attribute) for item in results] for attribute in attributes})


def sort_results(results, key, descending=False):
    try:
        return sorted(
            results,
            key=lambda item: getattr(item, key),
            reverse=descending
        )
    except (TypeError, AttributeError):
        raise ValueError(f"Cannot sort by `{key}`")

def apply_query_operations(results, tokens, keys, positions=None):
    i = 0

    while i < len(tokens):
        token = tokens[i]

        # sort
        if token == "sort":
            if i + 1 >= len(tokens):
                raise ChemQLError("Expected a key after `sort`", *(error_position(positions, i) if positions else (None, 1))) #type:ignore

            key = tokens[i + 1]

            if key not in keys:
                pos, length = error_position(positions, i + 1) if positions else (None, 1)
                raise ChemQLError(f"There is no key `{key}`", pos, length)

            descending = False

            if i + 2 < len(tokens):
                direction = tokens[i + 2].lower()

                if direction == "asc":
                    i += 1

                elif direction == "desc":
                    descending = True
                    i += 1

            try:
                results = sort_results(
                    results,
                    key,
                    descending
                )
            except ValueError as e:
                pos, length = error_position(positions, i + 1) if positions else (None, 1)
                raise ChemQLError(str(e), pos, length) from e

            i += 2

        # limit
        elif token == "limit":
            if i + 1 >= len(tokens):
                raise ChemQLError("Expected a number after `limit`", *(error_position(positions, i) if positions else (None, 1)))#type:ignore

            try:
                amount = int(tokens[i + 1])
            except ValueError:
                pos, length = error_position(positions, i + 1) if positions else (None, 1)
                raise ChemQLError("`limit` requires an integer", pos, length)

            if amount < 0:
                pos, length = error_position(positions, i + 1) if positions else (None, 1)
                raise ChemQLError("`limit` cannot be negative", pos, length)

            results = results[:amount] # type: ignore

            i += 2

        # count
        elif token == "count":
            if i + 1 < len(tokens):
                pos, length = error_position(positions, i) if positions else (None, 1)
                raise ChemQLError("`count` must be the final query operation", pos, length)

            results = len(results) # type: ignore
            i += 1

        else:
            pos, length = error_position(positions, i) if positions else (None, 1)
            raise ChemQLError(f"Unknown query operation `{token}`", pos, length)

    return results


functionMap = {"=": "__eq__", "!=": "__ne__", ">": "__gt__", "<": "__lt__", ">=": "__ge__", "<=": "__le__"}


def convert_value(value, sample):
    """Convert a query value to the type of the element value."""

    if isinstance(sample, bool):

        if value.lower() == "true":
            return True

        if value.lower() == "false":
            return False

        raise ValueError(f"`{value}` is not a boolean")

    if isinstance(sample, (int, float)):

        try:
            number = float(value)

            if number.is_integer():
                return int(number)

            return number

        except ValueError:
            raise ValueError(f"`{value}` is not a number")

    return value


def tokenize_query(arguments):
    """Convert tokens into a form suitable for parsing."""

    return arguments


def parse_condition(tokens, index, source, keys, positions=None):
    if index + 2 >= len(tokens):
        raise ChemQLError("Incomplete condition", *(error_position(positions, index) if positions else (None, 1)))#type:ignore

    key = tokens[index]
    operator = tokens[index + 1]
    negated = operator.casefold() == "not"
    if negated:
        if index + 3 >= len(tokens):
            raise ChemQLError("Expected an operator and value after `not`", *(error_position(positions, index + 1) if positions else (None, 1)))  # type: ignore
        operator = tokens[index + 2]
        value = tokens[index + 3]
        consumed = index + 4
    else:
        value = tokens[index + 2]
        consumed = index + 3

    if key not in keys:
        pos, length = error_position(positions, index) if positions else (None, 1)
        raise ChemQLError(f"There is no key `{key}`", pos, length)

    if operator in {"like", "like!", "likep"}:
        pattern = value
        if operator == "likep":
            try:
                compiled_pattern = re.compile(pattern)
            except re.error as exc:
                pos, length = error_position(positions, index + 2) if positions else (None, 1)
                raise ChemQLError(f"Invalid regex: {exc}", pos, length) from exc

            def regex_condition(item):
                actual = getattr(item, key)
                return isinstance(actual, str) and compiled_pattern.search(actual) is not None

            return (lambda item, fn=regex_condition: not fn(item)) if negated else regex_condition, consumed
        case_sensitive = operator == "like!"

        def like_condition(item):
            actual = getattr(item, key)

            if not isinstance(actual, str):
                return False

            return like_match(
                actual,
                pattern,
                case_sensitive
            )

        return (lambda item, fn=like_condition: not fn(item)) if negated else like_condition, consumed

    if operator == "has":
        def has_condition(item):
            actual = getattr(item, key)

            try:
                return value in actual
            except TypeError:
                return False

        return (lambda item, fn=has_condition: not fn(item)) if negated else has_condition, consumed

    if operator not in functionMap:
        pos, length = error_position(positions, index + 1) if positions else (None, 1)
        raise ChemQLError(f"Unknown operator `{operator}`", pos, length)

    sample = getattr(source[0], key)

    try:
        value = convert_value(value, sample)
    except ValueError as e:
        pos, length = error_position(positions, index + 2) if positions else (None, 1)
        raise ChemQLError(str(e), pos, length) from e

    function = functionMap[operator]

    def comparison_condition(item):
        try:
            return getattr(
                getattr(item, key),
                function
            )(value)
        except (TypeError, AttributeError):
            return False

    return (lambda item, fn=comparison_condition: not fn(item)) if negated else comparison_condition, consumed

def parse_primary(tokens, index, source, keys, positions=None):
    if index >= len(tokens):
        raise ChemQLError("Expected condition", *(error_position(positions, index) if positions else (None, 1)))#type:ignore

    if tokens[index].casefold() == "not":
        expression, next_index = parse_primary(tokens, index + 1, source, keys, positions)
        return (lambda item, fn=expression: not fn(item)), next_index

    if tokens[index] == "(":
        expression, index = parse_or(
            tokens,
            index + 1,
            source,
            keys,
            positions
        )

        if index >= len(tokens) or tokens[index] != ")":
            pos = positions[index][0] if positions and index < len(positions) else None
            raise ChemQLError("Missing `)`", pos)

        return expression, index + 1

    return parse_condition(
        tokens,
        index,
        source,
        keys,
        positions
    )


def parse_and(tokens, index, source, keys, positions=None):
    left, index = parse_primary(
        tokens,
        index,
        source,
        keys,
        positions
    )

    while index < len(tokens) and tokens[index] == "and":
        right, index = parse_primary(
            tokens,
            index + 1,
            source,
            keys,
            positions
        )

        previous = left

        left = lambda item, a=previous, b=right: (
            a(item) and b(item)
        )

    return left, index


def parse_or(tokens, index, source, keys, positions=None):
    left, index = parse_and(
        tokens,
        index,
        source,
        keys,
        positions
    )

    while index < len(tokens) and tokens[index] == "or":
        right, index = parse_and(
            tokens,
            index + 1,
            source,
            keys,
            positions
        )

        previous = left

        left = lambda item, a=previous, b=right: (
            a(item) or b(item)
        )

    return left, index


def parse_query(tokens, source, keys, positions=None):
    if not tokens:
        raise ChemQLError("No conditions specified", *(error_position(positions, 0) if positions else (None, 1)))#type:ignore

    # Allow a query to operate on the entire source when it begins
    # with a query operation, e.g. `search molecules count`.
    if tokens[0] in queryOperations:
        return (lambda item: True), 0

    condition, index = parse_or(
        tokens,
        0,
        source,
        keys,
        positions
    )

    # Conditions end when a query operation begins.
    if index < len(tokens) and tokens[index] not in queryOperations:
        pos, length = error_position(positions, index) if positions else (None, 1)
        raise ChemQLError(
            f"Unexpected `{tokens[index]}`", pos, length
        )

    return condition, index



SOURCES = {"elements": (ELEMENTS, elementKeys), "molecules": (MOLECULES, moleculeKeys), "reactions": (REACTIONS, reactionKeys)}


def get_source(source):
    return SOURCES.get(source)

current_source = None

REACTION_TEMPERATURE_TOLERANCE_K = 5.0
REACTION_PRESSURE_TOLERANCE = 0.05
reaction_state = {
    "temperature_k": None,
    "pressure_pa": None,
    "catalysts": [],
}

# Python variables persist for the whole session.
python_globals = {"__builtins__": __builtins__, "math": math}
CHEMQL_VARIABLES = set()

def _chemql_value(expression):
    """Resolve a native ChemQL variable, otherwise evaluate a query expression."""
    expression = expression.strip()
    if re.fullmatch(_DEFINITION_NAME, expression) and expression in CHEMQL_VARIABLES:
        return python_globals[expression]
    return execute_query_block(expression)


def find_matching(text, start, opening, closing):
    """Find the matching closing delimiter, allowing nested delimiters."""
    depth = 1
    i = start + len(opening)
    quote = None
    escaped = False

    while i < len(text):
        char = text[i]

        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            i += 1
            continue

        if char in ("'", '"'):
            quote = char
            i += 1
            continue

        if text.startswith(opening, i):
            depth += 1
            i += len(opening)
            continue

        if text.startswith(closing, i):
            depth -= 1
            if depth == 0:
                return i
            i += len(closing)
            continue

        i += 1

    raise SyntaxError(f"Missing `{closing}`")


def interpolate_query(text):
    """Evaluate [Python] expressions inside a query."""
    result = []
    i = 0

    while i < len(text):
        if text[i] == "[":
            end = find_matching(text, i, "[", "]")
            code = text[i + 1:end]
            value = evaluate_python(code)

            if isinstance(value, str):
                result.append(shlex.quote(value))
            elif value is None:
                result.append("None")
            else:
                result.append(shlex.quote(str(value)))

            i = end + 1
            continue

        result.append(text[i])
        i += 1

    return "".join(result)

def interpolate_python_queries(code):
    rewritten = []
    query_values = {}
    query_index = 0
    i = 0

    while i < len(code):
        if code.startswith("{{", i):
            end = find_matching(code, i, "{{", "}}")
            query = code[i + 2:end].strip()

            value = _chemql_value(query)

            name = f"__chemql_query_{query_index}"
            query_index += 1

            query_values[name] = value
            rewritten.append(name)

            i = end + 2
            continue

        rewritten.append(code[i])
        i += 1

    python_globals.update(query_values)
    return "".join(rewritten)

def _space_query_operators(text):
    """Separate comparison operators and parentheses outside quoted strings."""
    out, quote, escaped = [], None, False
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue
                # Preserve the compound operator "like!" as a single token.
        if text[i:i + 5].casefold() == "like!":
            before_ok = (
                i == 0 or not (
                    text[i - 1].isalnum() or text[i - 1] == "_"
                )
            )
            end = i + 5
            after_ok = (
                end == len(text) or not (
                    text[end].isalnum() or text[end] == "_"
                )
            )

            if before_ok and after_ok:
                out.extend((" ", text[i:end], " "))
                i = end
                continue
        if ch in "()":
            out.extend((" ", ch, " "))
            i += 1
            continue
        if ch in "<>!=" and i + 1 < len(text) and text[i + 1] == "=":
            out.extend((" ", ch + "=", " "))
            i += 2
            continue
        if ch in "<>!=":
            out.extend((" ", ch, " "))
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _split_set_operations(text):
    """Split top-level union/intersection outside quotes and parentheses, left-to-right."""
    parts, ops, start, depth = [], [], 0, 0
    quote, escaped = None, False
    words = re.finditer(r"\b(union|intersection)\b", text, re.IGNORECASE)
    for match in words:
        i = match.start()
        quote = None
        escaped = False
        depth = 0
        j = 0
        while j < i:
            ch = text[j]
            if quote:
                if escaped: escaped = False
                elif ch == "\\": escaped = True
                elif ch == quote: quote = None
            elif ch in ("'", '"'): quote = ch
            elif ch == "(": depth += 1
            elif ch == ")": depth -= 1
            j += 1
        if quote is None and depth == 0:
            parts.append(text[start:i].strip())
            ops.append(match.group(1).casefold())
            start = match.end()
    if not ops:
        return None
    parts.append(text[start:].strip())
    if any(not part for part in parts):
        raise ChemQLError("Missing query around union/intersection")
    return parts, ops


def _as_result_list(result):
    if result is None or result == "No matching item":
        return []
    return result if isinstance(result, list) else [result]


def execute_query_text(text):
    """Execute plain query-language text."""
    text = text.strip()
    text = _expand_function_calls(text)
    set_expression = _split_set_operations(text)
    if set_expression:
        parts, ops = set_expression
        result = _as_result_list(execute_query_text(parts[0]))
        for operator, part in zip(ops, parts[1:]):
            right = _as_result_list(execute_query_text(part))
            def identity(item):
                if hasattr(item, "id"): return ("id", getattr(item, "id"))
                if hasattr(item, "number"): return ("number", getattr(item, "number"))
                if hasattr(item, "cid") and getattr(item, "cid") is not None: return ("cid", getattr(item, "cid"))
                return (type(item).__name__, repr(item))
            right_map = {identity(item): item for item in right}
            if operator == "union":
                seen = {identity(item) for item in result}
                result.extend(item for item in right if identity(item) not in seen and not seen.add(identity(item)))
            else:
                result = [item for item in result if identity(item) in right_map]
        return result

    text = interpolate_query(text)
    text = _space_query_operators(text)
    positions = token_positions(text)

    try:
        arguments = shlex.split(text)
    except ValueError as e:
        raise ChemQLError(f"Query syntax error: {e}")

    try:
        return execute(arguments, text, positions)
    except ChemQLError as e:
        if e.position is None:
            raise
        raise


def execute_query(query: str) -> str | Molecule | Element | Reaction | list | None | Unknown:
    """Execute a Chemql query through the public programmatic API."""
    result = execute_query_text(query)

    if isinstance(result, (str, Molecule, Element, Reaction, Unknown)):
        return result

    # Keep the public API total for result types that have not yet been
    # given a dedicated return type (for example lists, ReturnTable, and
    # integer counts).
    return Unknown(result)


def execute_query_block(text):
    # Hybrid code needs the raw query result, so it intentionally bypasses
    # the public Unknown wrapper.
    return execute_query_text(text)


def evaluate_python(code):
    """Evaluate Python, with {{ query }} expressions available inside it.

    If the Python is an expression, its value is returned.
    Otherwise it is executed and None is returned.
    """
    query_values = {}
    rewritten = []
    i = 0
    query_index = 0

    while i < len(code):
        if code.startswith("{{", i):
            end = find_matching(code, i, "{{", "}}")
            query = code[i + 2:end].strip()
            query = _expand_function_calls(query)
            value = _chemql_value(query)

            name = f"__chemql_query_{query_index}"
            query_index += 1
            query_values[name] = value
            rewritten.append(name)
            i = end + 2
            continue

        rewritten.append(code[i])
        i += 1

    rewritten = "".join(rewritten)
    rewritten = _expand_function_calls(rewritten)

    python_globals.update(query_values)

    try:
        tree = ast.parse(rewritten, mode="eval")
    except SyntaxError:
        module = ast.parse(rewritten, mode="exec")
        for node in ast.walk(module):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                if isinstance(node.ctx, ast.Store) and node.id.isidentifier() and not node.id.startswith("__chemql_"):
                    CHEMQL_VARIABLES.add(node.id)
        exec(compile(module, "<embedded-python>", "exec"), python_globals)
        return None

    return eval(compile(tree, "<embedded-python>", "eval"), python_globals)


def is_python_block_header(text):
    """Recognize [for ...], [if ...], etc. without requiring a colon."""
    text = text.strip()

    if not (text.startswith("[") and text.endswith("]")):
        return False

    code = text[1:-1].strip()

    # Replace {{...}} queries with valid Python variable names
    while "{{" in code:
        start = code.index("{{")
        end = find_matching(code, start, "{{", "}}")
        code = code[:start] + "__chemql_query_placeholder" + code[end + 2:]

    try:
        tree = ast.parse(code + ":\n    pass", mode="exec")
    except SyntaxError:
        return False

    return bool(tree.body) and isinstance(
        tree.body[0],
        (
            ast.For,
            ast.While,
            ast.If,
            ast.With,
            ast.Try,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
        )
    )


def find_endblock(lines, start):
    """Find the matching [endblock], allowing nested blocks."""
    depth = 1

    for i in range(start, len(lines)):
        stripped = lines[i].strip()

        # Closing block.
        if stripped == "[endblock]":
            depth -= 1

            if depth == 0:
                return i

            continue

        # Branch markers do not start new blocks.
        if stripped in ("[else]", "[endif]", "[endfor]", "[endwhile]"):
            continue

        # Recognize both validated Python headers and generic
        # ChemQL block headers, consistently with _call_function().
        generic_header = re.match(
            r"^\[\s*(?!endblock\b|else\b|elif\b)"
            r"[A-Za-z_]\w*\b.*\]\s*$",
            stripped,
        )

        if is_block_header(stripped):
            depth += 1

    raise SyntaxError("Missing `[endblock]`")

def remove_comments(line):
    in_quote = None
    escaped = False

    for i in range(len(line) - 1):
        char = line[i]

        if escaped:
            escaped = False
            continue

        if char == "\\" and in_quote:
            escaped = True
            continue

        if char in ('"', "'"):
            if in_quote is None:
                in_quote = char
            elif in_quote == char:
                in_quote = None
            continue

        if line[i:i + 2] == "//" and in_quote is None:
            return line[:i].rstrip()

    return line


class ChemQLBreak(Exception):
    pass
class ChemQLContinue(Exception):
    pass


def execute_for_block(header, body):
    code = header[1:-1].strip()
    code = interpolate_python_queries(code)

    tree = ast.parse(code + ":\n    pass", mode="exec")

    node = tree.body[0]

    if not isinstance(node, ast.For):
        raise SyntaxError("Expected a `for` block")

    iterable = eval(
        compile(ast.Expression(node.iter), "<embedded-python>", "eval"),
        python_globals
    )

    if not hasattr(iterable, "__iter__"):
        iterable = (iterable,)

    for value in iterable:
        temp_name = "__chemql_for_value"
        python_globals[temp_name] = value

        assignment = ast.Assign(
            targets=[node.target],
            value=ast.Name(
                id=temp_name,
                ctx=ast.Load()
            )
        )

        module = ast.Module(
            body=[assignment],
            type_ignores=[]
        )

        ast.fix_missing_locations(module)

        exec(
            compile(
                module,
                "<embedded-python>",
                "exec"
            ),
            python_globals
        )

        try:
            process_lines(body)

        except ChemQLContinue:
            continue

        except ChemQLBreak:
            break


def execute_while_block(header, body):
    code = header[1:-1].strip()

    tree = ast.parse(
        code + ":\n    pass",
        mode="exec"
    )

    node = tree.body[0]

    if not isinstance(node, ast.While):
        raise SyntaxError("Expected a `while` block")

    while eval(
        compile(
            ast.Expression(node.test),
            "<embedded-python>",
            "eval"
        ),
        python_globals
    ):
        try:
            process_lines(body)

        except ChemQLContinue:
            continue

        except ChemQLBreak:
            break


def execute_if_block(header, body):
    """
    Execute an if/elif/else chain.

    The body contains the entire block, including any
    [elif ...] and [else] clauses.
    """

    sections = []

    current_header = header
    current_body = []

    depth = 0

    for line in body:
        stripped = line.strip()

        if is_python_block_header(stripped):
            depth += 1

        elif stripped == "[endblock]":
            depth -= 1

        # Only recognize elif/else belonging to THIS if.
        if depth == 0 and (
            stripped.startswith("[elif ")
            or stripped == "[else]"
        ):
            sections.append(
                (current_header, current_body)
            )

            current_header = stripped
            current_body = []

        else:
            current_body.append(line)

    sections.append(
        (current_header, current_body)
    )

    for section_header, section_body in sections:
        code = _expand_definitions(section_header[1:-1].strip())

        if code.startswith("if "):
            condition = code[3:].strip()

        elif code.startswith("elif "):
            condition = code[5:].strip()

        elif code == "else":
            process_lines(section_body)
            return

        else:
            raise SyntaxError(
                f"Invalid conditional `{code}`"
            )

        if evaluate_python(condition):
            process_lines(section_body)
            return

def split_commands(text):
    """Split top-level semicolons, respecting quotes and nested syntax."""
    commands = []
    start = 0
    i = 0
    square = 0
    curly = 0
    quote = None
    escaped = False
    backtick = False

    while i < len(text):
        char = text[i]

        if backtick:
            if char == "`" and not escaped:
                backtick = False
            if char == "\\" and not escaped:
                escaped = True
            else:
                escaped = False
            i += 1
            continue

        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            i += 1
            continue

        if char in ("'", '"'):
            quote = char
        elif char == "`":
            backtick = True
        elif text.startswith("{{", i):
            curly += 1
            i += 2
            continue
        elif text.startswith("}}", i) and curly:
            curly -= 1
            i += 2
            continue
        elif char == "[":
            square += 1
        elif char == "]" and square:
            square -= 1
        elif char == ";" and square == 0 and curly == 0:
            commands.append(text[start:i])
            start = i + 1

        i += 1

    commands.append(text[start:])
    return commands


def _record_execution(query, result, success):
    EXECUTION_HISTORY.append({
        "query": str(query),
        "result": str(result) if result is not None else "",
        "success": bool(success),
    })


def _dump_history(command):
    """Implement: dump [all|good|bad] [queries|results] FILE."""
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise ChemQLError(f"Invalid dump command: {exc}") from exc

    if len(parts) == 2:
        category, mode, filename = "all", "both", parts[1]
    elif len(parts) == 4:
        category, mode, filename = parts[1:]
        if category not in {"all", "good", "bad"} or mode not in {"queries", "results"}:
            raise ChemQLError("Usage: dump [all|good|bad] [queries|results] FILE")
    elif len(parts) == 3 and parts[1] in {"all", "good", "bad"}:
        category, mode, filename = parts[1], "both", parts[2]
    else:
        raise ChemQLError("Usage: dump [all|good|bad] [queries|results] FILE")

    records = EXECUTION_HISTORY
    if category == "good":
        records = [record for record in records if record["success"]]
    elif category == "bad":
        records = [record for record in records if not record["success"]]

    if mode == "queries":
        content = "\n".join(record["query"] for record in records)
    elif mode == "results":
        content = "\n".join(record["result"] for record in records)
    else:
        content = "\n\n".join(
            f"QUERY:\n{record['query']}\nRESULT:\n{record['result']}"
            for record in records
        )

    Path(filename).write_text(strip_ansi(content), encoding="utf-8")
    return f"Dumped {len(records)} execution record(s) to {filename}"


def strip_ansi(text):
    """Remove common ANSI CSI, OSC, and single-character escape sequences."""
    text = re.sub(r"\x1B\][^\x07]*(?:\x07|\x1B\\)", "", str(text))
    return re.sub(r"\x1B(?:\[[0-?]*[ -/]*[@-~]|[@-_])", "", text)


def process_inline(text):
    """Process one complete line of the chemql language."""
    stripped = text.strip()

    if not stripped:
        return

    # Native dynamically typed variables: `let name = expression`.
    let_match = re.fullmatch(r"let\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)", stripped, re.DOTALL)
    if let_match:
        name, expression = let_match.groups()
        value = evaluate_python(expression)
        python_globals[name] = value
        CHEMQL_VARIABLES.add(name)
        return None

    if stripped.casefold() == "variables":
        if not CHEMQL_VARIABLES:
            return "No variables."
        return "\n".join(f"{name} = {python_globals.get(name)!r}" for name in sorted(CHEMQL_VARIABLES) if name in python_globals)

    unset_match = re.fullmatch(r"unset\s+([A-Za-z_][A-Za-z0-9_]*)", stripped, re.IGNORECASE)
    if unset_match:
        name = unset_match.group(1)
        CHEMQL_VARIABLES.discard(name)
        python_globals.pop(name, None)
        return None

    # A bare native variable is an expression that prints its value in the REPL.
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", stripped) and stripped in CHEMQL_VARIABLES:
        return python_globals.get(stripped)

    # History dump command.
    if stripped.casefold().startswith("dump "):
        return _dump_history(stripped)

    # A standalone user-defined function call returns its value directly.
    function_call = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)?)\s*\{(.*)\}", stripped, re.DOTALL)
    if function_call and function_call.group(1) in FUNCTIONS:
        return _call_function(function_call.group(1), _split_function_arguments(function_call.group(2)))

    # [ ... ] is Python.
    if stripped.startswith("["):
        end = find_matching(stripped, 0, "[", "]")
        if not stripped[end + 1:].strip():
            return evaluate_python(stripped[1:end])

    # {{ ... }} is a query expression.
    if stripped.startswith("{{"):
        end = find_matching(stripped, 0, "{{", "}}")
        if not stripped[end + 2:].strip():
            return execute_query_block(stripped[2:end].strip())

    # Backtick-wrapped commands use the persistent Bash session.
    if len(stripped) >= 2 and stripped.startswith("`") and stripped.endswith("`"):
        command = stripped[1:-1]
        return run_shell_command(command)


    # Everything else is query language.
    return execute_query_text(stripped)


def join_continuations(lines):
    """Join lines ending in \\ with the following line."""
    joined = []
    buffer = None

    for line in lines:
        if buffer is None:
            buffer = line
        else:
            buffer += line

        if buffer.endswith("\\"):
            buffer = buffer[:-1] + " "
            continue

        joined.append(buffer)
        buffer = None

    if buffer is not None:
        joined.append(buffer)

    return joined


def _find_unquoted_marker(text, marker, start=0):
    """Find a marker outside single- and double-quoted strings."""
    quote = None
    escaped = False
    i = start
    while i <= len(text) - len(marker):
        char = text[i]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            i += 1
            continue
        if char in ("'", '"'):
            quote = char
            i += 1
            continue
        if text.startswith(marker, i):
            return i
        i += 1
    return -1


def process_lines(lines):
    """Process ChemQL source, including multiline Python, terminal, and comments."""
    lines = join_continuations(list(lines))
    i = 0

    while i < len(lines):
        raw_line = lines[i]
        stripped = raw_line.strip()

        if not stripped:
            i += 1
            continue

        # Definitions are processed in source order and affect only later lines.
        define_match = re.fullmatch(r"define\s+(" + _DEFINITION_NAME + r")\s+(.+)", stripped)
        if define_match and not stripped.endswith("{}"):
            DEFINITIONS[define_match.group(1)] = define_match.group(2)
            i += 1
            continue

        remove_definition = re.fullmatch(r"remove\s+definition\s+(" + _DEFINITION_NAME + r")", stripped, re.IGNORECASE)
        if remove_definition:
            DEFINITIONS.pop(remove_definition.group(1), None)
            i += 1
            continue

        if stripped.casefold() == "definitions":
            if DEFINITIONS:
                for name, value in DEFINITIONS.items():
                    print(f"@{name} = {value}")
            else:
                print("No definitions.")
            i += 1
            continue
        if stripped.casefold() == "macros":
            if MACROS:
                for name, value in MACROS.items():
                    print(f"@{name} = {value}")
            else:
                print("No macros.")
            i += 1
            continue

        # Function definitions use `func NAME ... endfunc`.
        function_match = re.fullmatch(r"func\s+(" + _DEFINITION_NAME + r")", stripped, re.IGNORECASE)
        if function_match:
            name = function_match.group(1)
            end = i + 1
            while end < len(lines) and lines[end].strip().casefold() != "endfunc":
                end += 1
            if end >= len(lines):
                raise SyntaxError(f"Missing `endfunc` for function `{name}`")
            FUNCTIONS[name] = {"body": [_expand_definitions(source_line) for source_line in lines[i + 1:end]]}
            i = end + 1
            continue

        # `define NAME{}` introduces a source-generating macro.
        macro_match = re.fullmatch(r"define\s+(" + _DEFINITION_NAME + r")\s*\{\s*\}", stripped)
        if macro_match:
            name = macro_match.group(1)
            end = i + 1
            while end < len(lines) and lines[end].strip().casefold() != "enddefine":
                end += 1
            if end >= len(lines):
                raise SyntaxError(f"Missing `enddefine` for macro `{name}`")
            MACROS[name] = [_expand_definitions(source_line) for source_line in lines[i + 1:end]]
            i = end + 1
            continue

        # Multiline comments can start/end within a line, but markers inside
        # quoted strings are ordinary text. Keep any code surrounding a comment.
        comment_start = _find_unquoted_marker(raw_line, "///")
        if comment_start >= 0:
            prefix = raw_line[:comment_start]
            same_line_end = _find_unquoted_marker(raw_line, "///", comment_start + 3)
            if same_line_end >= 0:
                suffix = raw_line[same_line_end + 3:]
                lines[i] = prefix + suffix
                if not lines[i].strip():
                    i += 1
                    continue
                raw_line = lines[i]
                stripped = raw_line.strip()
            else:
                close_line = i + 1
                close_pos = -1
                while close_line < len(lines):
                    close_pos = _find_unquoted_marker(lines[close_line], "///")
                    if close_pos >= 0:
                        break
                    close_line += 1
                if close_line >= len(lines):
                    raise SyntaxError("Missing closing `///` for multiline comment")
                suffix = lines[close_line][close_pos + 3:]
                lines[i] = prefix
                del lines[i + 1:close_line + 1]
                if suffix.strip():
                    lines.insert(i + 1, suffix)
                if not prefix.strip():
                    if suffix.strip():
                        i += 1
                    else:
                        continue
                else:
                    raw_line = prefix
                    stripped = prefix.strip()

        # Multiline Python block. Closing delimiter must be alone on a line;
        # this avoids mistaking valid expressions such as [[4]]] for a close.
        if stripped == "[[[":
            body = []
            i += 1
            while i < len(lines) and lines[i].strip() != "]]]":
                body.append(lines[i])
                i += 1
            if i >= len(lines):
                raise SyntaxError("Missing closing `]]]` for Python block")
            body = [_expand_definitions(source_line) for source_line in body]
            code = "\n".join(body)
            captured = io.StringIO()
            try:
                with contextlib.redirect_stdout(captured):
                    value = evaluate_python(code)
                output = captured.getvalue()
                if value is not None:
                    output += str(value)
                if output:
                    output = strip_ansi(output) if NO_ANSI else output
                    print(output, end="" if output.endswith("\n") else "\n")
                _record_execution("[[[\n" + code + "\n]]]", output, True)
            except Exception as exc:
                message = f"Error: {exc}"
                print(strip_ansi(message) if NO_ANSI else message, file=sys.stderr)
                _record_execution("[[[\n" + code + "\n]]]", message, False)
            i += 1
            continue

        # Multiline terminal block, sent as one script to the persistent shell.
        if stripped in {"```", "```bash", "```sh", "```cmd", "```terminal"}:
            body = []
            i += 1
            while i < len(lines) and lines[i].strip() != "```":
                body.append(lines[i])
                i += 1
            if i >= len(lines):
                raise SyntaxError("Missing closing ``` for terminal block")
            body = [_expand_definitions(source_line) for source_line in body]
            command = "\n".join(body)
            result = run_shell_command(command)
            result = strip_ansi(result) if NO_ANSI else result
            # POSIX PTY commands stream output live. Never print their returned
            # capture a second time; Windows pipe mode still needs normal printing.
            if result and not _shell_output_streamed:
                print(result)
            _record_execution("```\n" + command + "\n```", result, not result.startswith("Shell error:"))
            globals()["_shell_output_streamed"] = False
            i += 1
            continue

        # Literal definitions are intentionally expanded inside strings too.
        # Directives themselves were handled above, so updates are not retroactive.
        raw_line = _expand_definitions(raw_line)
        line = remove_comments(raw_line).strip()
        if not line:
            i += 1
            continue

        if line == "[endblock]":
            raise SyntaxError("Unexpected `[endblock]`")

        # Existing Python control-flow blocks.
        if is_python_block_header(line):
            end = find_endblock(lines, i + 1)
            body = lines[i + 1:end]
            code = line[1:-1].strip()
            if code.startswith("for "):
                execute_for_block(line, body)
            elif code.startswith("while "):
                execute_while_block(line, body)
            elif code.startswith("if "):
                execute_if_block(line, body)
            else:
                raise SyntaxError(f"Unsupported block `{code}`")
            i = end + 1
            continue

        if line == "[break]":
            raise ChemQLBreak()
        if line == "[continue]":
            raise ChemQLContinue()
        if line == "view":
            view_periodic_table()
            i += 1
            continue

        for command in split_commands(line):
            command = command.strip()
            if not command:
                continue
            try:
                macro_call = re.fullmatch(r"@(" + _DEFINITION_NAME + r")\s*\{(.*)\}", command, re.DOTALL)
                if macro_call and macro_call.group(1) in MACROS:
                    macro_name = macro_call.group(1)
                    macro_args = _split_function_arguments(macro_call.group(2))
                    expanded_lines = []
                    for macro_line in MACROS[macro_name]:
                        expanded = macro_line
                        for arg_index, arg in enumerate(macro_args, start=1):
                            expanded = re.sub(
                                r"\\" + str(arg_index) + r"(?!\d)",
                                lambda _match, value=arg: value,
                                expanded,
                            )
                        expanded_lines.append(_expand_definitions(expanded))
                    process_lines(expanded_lines)
                    result = None
                elif command.casefold().startswith("dump "):
                    result = _dump_history(command)
                else:
                    result = process_inline(command)
                rendered = "" if result is None else str(result)
                if result is not None:
                    if NO_ANSI:
                        rendered = strip_ansi(rendered)
                    # PTY-backed backtick commands already stream their output.
                    # Don't echo their captured return value a second time.
                    is_streamed_shell = (
                        os.name != "nt"
                        and len(command) >= 2
                        and command.startswith("`")
                        and command.endswith("`")
                    )
                    if not is_streamed_shell and not _shell_output_streamed:
                        print(rendered)
                _record_execution(command, rendered, True)
                globals()["_shell_output_streamed"] = False
            except Exception as exc:
                message = f"Error: {exc}"
                print(strip_ansi(message) if NO_ANSI else message, file=sys.stderr)
                _record_execution(command, message, False)

        i += 1


def normalize_catalysts(values):
    catalysts = []
    seen = set()

    for value in values:
        catalyst = value.strip()
        normalized = catalyst.casefold()
        if catalyst and normalized not in seen:
            catalysts.append(catalyst)
            seen.add(normalized)

    return catalysts


def parse_temperature_setting(value):
    normalized = value.strip().casefold()
    if normalized == "standard":
        return 273.15
    if normalized == "room":
        return 298.15

    match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(?:°\s*)?(celsius|fahrenheit|kelvin|degc|degf|degk|c|f|k)", normalized)
    if not match:
        raise ValueError("Temperature must use C, F, or K, or be `standard` or `room`")

    temperature = float(match.group(1))
    unit = match.group(2)
    unit = {"celsius": "c", "degc": "c", "fahrenheit": "f", "degf": "f", "kelvin": "k", "degk": "k", "K":"k", "C":"c", "F": "f","k":"k", "c":"c", "f": "f"}[unit]
    if unit == "f":
        temperature = (temperature - 32) * 5 / 9 + 273.15
    elif unit == "c":
        temperature += 273.15

    if temperature < 0:
        raise ValueError("Temperature cannot be below absolute zero")

    return temperature


def parse_pressure_setting(value):
    normalized = value.strip().casefold()
    if normalized == "standard":
        return 100000.0
    if normalized == "room":
        return 101325.0

    match = re.fullmatch(r"([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(.*?)", normalized)
    if not match:
        raise ValueError("Pressure must be a non-negative value with Pa, N/m^2, bar, or atm units")

    pressure = float(match.group(1))
    unit = re.sub(r"\s+", "", match.group(2)).replace("²", "^2")
    unit_scales = {
        "pa": 1.0, "pascal": 1.0, "pascals": 1.0,
        "kpa": 1_000.0, "mpa": 1_000_000.0,
        "hpa": 100.0, "mbar": 100.0,
        "n/m^2": 1.0, "n/m2": 1.0, "nm^-2": 1.0, "n·m^-2": 1.0,
        "bar": 100_000.0, "mbar": 100.0,
        "atm": 101_325.0, "torr": 101_325.0 / 760, "mmhg": 101_325.0 / 760,
        "psi": 6894.757293168, "kpsi": 6_894_757.293168,
    }
    if unit not in unit_scales:
        raise ValueError("Unsupported pressure unit. Try Pa, kPa, MPa, hPa, bar, atm, torr, mmHg, or psi")

    return pressure * unit_scales[unit]


def _reaction_formula(value):
    normalized = value.casefold()
    for molecule in MOLECULES:
        if molecule.formula.casefold() == normalized:
            return molecule.formula
        if molecule.name.casefold() == normalized or molecule.iupac_name.casefold() == normalized:
            return molecule.formula
    return value


def parse_reactants(values):
    counts = {}
    index = 0

    while index < len(values):
        value = values[index]
        coefficient = 1

        if value.isdigit():
            coefficient = int(value)
            index += 1
            if index >= len(values):
                raise ValueError("Expected a molecule after its coefficient")
            value = values[index]
        else:
            match = re.match(r"^(\d+)(?=[A-Za-z])", value)
            if match:
                coefficient = int(match.group(1))
                value = value[match.end():]

        if coefficient <= 0 or not value:
            raise ValueError("Reactant coefficients must be positive integers")

        formula = _reaction_formula(value)
        key = formula.casefold()
        counts[key] = counts.get(key, 0) + coefficient
        index += 1

    if not counts:
        raise ValueError("Usage: react <coefficient><molecule> ...")

    return counts


def _reaction_side_counts(participants):
    counts = {}
    for participant in participants:
        formula = participant["molecule"]
        key = formula.casefold()
        counts[key] = counts.get(key, 0) + participant["stoichiometric_coefficient"]
    return counts


def _reaction_conditions_match(reaction):
    conditions = reaction.conditions
    temperature = conditions.get("temperature_k")
    if temperature is not None:
        current_temperature = reaction_state["temperature_k"]
        if current_temperature is None or abs(current_temperature - temperature) > REACTION_TEMPERATURE_TOLERANCE_K:
            return False

    pressure = conditions.get("pressure_pa")
    if pressure is not None:
        current_pressure = reaction_state["pressure_pa"]
        if current_pressure is None:
            return False
        tolerance = abs(pressure) * REACTION_PRESSURE_TOLERANCE
        if abs(current_pressure - pressure) > tolerance:
            return False

    required_catalysts = {
        item.casefold() for item in conditions.get("catalysts", [])
    }
    available_catalysts = {
        item.casefold() for item in reaction_state["catalysts"]
    }
    return required_catalysts.issubset(available_catalysts)


def _resolve_reaction_product(participant):
    formula = participant["molecule"]
    for molecule in MOLECULES:
        if molecule.formula.casefold() == formula.casefold():
            return molecule

    name = participant.get("name", formula)
    result = fetch_pubchem_molecule(name)
    if result is None:
        result = fetch_pubchem_molecule(formula)
    return result


def react(values):
    try:
        reactants = parse_reactants(values)
    except ValueError as exc:
        return str(exc)

    matches = []
    for reaction in REACTIONS:
        if not _reaction_conditions_match(reaction):
            continue

        forward = _reaction_side_counts(reaction.reactants)
        if reactants == forward:
            matches.append((reaction, reaction.products))
            continue

        if reaction.reversible is True and reactants == _reaction_side_counts(reaction.products):
            matches.append((reaction, reaction.reactants))

    if not matches:
        return "No reaction matches those reactants and the current temperature, pressure, and catalysts"

    if len(matches) > 1:
        names = ", ".join(f"{reaction.name} ({reaction.id})" for reaction, _ in matches[:5])
        return f"Multiple reactions match: {names}"

    reaction, products = matches[0]
    resolved = []
    for product in products:
        molecule = _resolve_reaction_product(product)
        if molecule is None:
            label = product.get("name", product["molecule"])
            return f"Could not resolve product molecule `{label}` for reaction `{reaction.id}`"
        resolved.append((molecule, product["stoichiometric_coefficient"], product.get("phase")))

    if len(resolved) == 1:
        return resolved[0][0]

    return ReturnTable({
        "molecule": [item[0] for item in resolved],
        "stoichiometric_coefficient": [item[1] for item in resolved],
        "phase": [item[2] or "" for item in resolved],
    })


def current_conditions():
    temperature = reaction_state["temperature_k"]
    pressure = reaction_state["pressure_pa"]
    catalysts = reaction_state["catalysts"]

    temperature_text = f"{temperature:g} K" if temperature is not None else "Not Set"
    pressure_text = f"{pressure:g} Pa" if pressure is not None else "Not Set"
    catalysts_text = ", ".join(catalysts) if catalysts else "Not Set"

    return (
        f"Temperature: {temperature_text}\n"
        f"Pressure: {pressure_text}\n"
        f"Catalysts: {catalysts_text}"
    )


def execute(arguments, query_text=None, positions=None):
    global current_source

    if not arguments:
        return

    if arguments[0].lower() == "balance":
        try:
            return _execute_balance_command(
                query_text if query_text is not None else shlex.join(arguments)
            )
        except ValueError as exc:
            return format_error(str(exc), query_text)

    if arguments[0].lower() in {"help", "?"}:
        return HELP

    if arguments[0].lower() == "sorry":
        return "\033[34mIt's ok, everybody makes mistakes👌\033[0m"
    
    if arguments[0].lower() == "view":
        view_periodic_table()
        return "Check your browser to view periodic table"

    if arguments[0].lower() == "version":
        return __version__
    if arguments[0].lower() == "exit":
        return sys.exit(0)
    if arguments[0].lower() == "definitions":
        return "\n".join([f"@{name} = {value}" for name, value in DEFINITIONS.items()]) if DEFINITIONS else "No definitions."
        
    if arguments[0].lower() == "macros":
        return "\n".join([f"@{name} = {value}" for name, value in MACROS.items()]) if MACROS else "No macros."
    
    if arguments[0] == "conditions":
        if len(arguments) != 1:
            return "Usage: conditions"
        return current_conditions()

    if arguments[0] == "set":
        if len(arguments) < 2:
            return "Usage: set temperature|pressure|catalysts <value>"

        setting = arguments[1].lower()
        values = arguments[2:]

        if setting == "temperature":
            if len(values) != 1:
                return "Usage: set temperature <valueC|valueF|valueK|standard|room>"

            try:
                reaction_state["temperature_k"] = parse_temperature_setting(values[0])
            except ValueError as exc:
                return str(exc)

            return f"Temperature set to {reaction_state['temperature_k']:.2f} K"

        if setting == "pressure":
            if len(values) != 1:
                return "Usage: set pressure <valuePa|valueN/m^2|valuebar|valueatm|standard|room>"

            try:
                reaction_state["pressure_pa"] = parse_pressure_setting(values[0])
            except ValueError as exc:
                return str(exc)

            return f"Pressure set to {reaction_state['pressure_pa']:g} Pa"

        if setting == "catalysts":
            reaction_state["catalysts"] = normalize_catalysts(values)
            if not reaction_state["catalysts"]:
                return "Catalysts cleared"
            return f"Catalysts set to {', '.join(reaction_state['catalysts'])}"

        return f"Unknown reaction setting `{setting}`"

    if arguments[0] == "add" and len(arguments) >= 2 and arguments[1].lower() == "catalyst":
        if len(arguments) < 3:
            return 'Usage: add catalyst "name"'

        catalyst = " ".join(arguments[2:]).strip()
        current = reaction_state["catalysts"]
        if catalyst and catalyst.casefold() not in {item.casefold() for item in current}:
            current.append(catalyst)
        return f"Catalysts: {', '.join(current)}" if current else "Catalysts cleared"

    if arguments[0] == "remove" and len(arguments) >= 2 and arguments[1].lower() in {"catalyst", "calatyst"}:
        if len(arguments) < 3:
            return 'Usage: remove catalyst "name"'

        catalyst = " ".join(arguments[2:]).strip()
        reaction_state["catalysts"] = [
            item for item in reaction_state["catalysts"]
            if item.casefold() != catalyst.casefold()
        ]
        return f"Catalysts: {', '.join(reaction_state['catalysts'])}" if reaction_state["catalysts"] else "Catalysts cleared"

    if arguments[0] == "react":
        return react(arguments[1:])

    # Convenience aliases for very common lookups.
    # These are syntactic sugar for normal search queries.
    if arguments[0] == "findel":
        if len(arguments) < 2:
            return "Usage: findel <name-or-symbol>"

        value = arguments[1]
        
        return_attributes = None

        return execute(
            ["search", "elements", "name", "like", value, "or", "symbol", "like", value]
        )

    if arguments[0] == "findmol":
        if len(arguments) < 2:
            return "Usage: findmol <name-or-formula> [return <attribute> ...]"

        value = arguments[1]

        # Optional return clause
        return_attributes = None

        if "return" in arguments[2:]:
            return_index = arguments.index("return", 2)
            return_attributes = arguments[return_index + 1:]

            if not return_attributes:
                return "Usage: findmol <name-or-formula> return <attribute> ..."

            for attribute in return_attributes:
                if attribute not in moleculeKeys:
                    return f"There is no key `{attribute}`"

            if return_index != 2:
                return "Usage: findmol <name-or-formula> [return <attribute> ...]"

        elif len(arguments) > 2:
            return "Usage: findmol <name-or-formula> [return <attribute> ...]"

        # Search the local dataset first.
        result = execute(
            ["search", "molecules", "name", "like", value, "or", "formula", "like", value]
        )

        if result == [] or result == "No matching item":
            result = fetch_pubchem_molecule(value)

        if result is None:
            return f"Could not find molecule `{value}`"

        if isinstance(result, str) and "PubChem is currently unavailable" in result:
            return result

        if isinstance(result, str) and "could not be found in the recommended sources" in result.lower():
            return result

        # Apply optional projection.
        if return_attributes:
            if isinstance(result, list):
                return project_results(result, return_attributes)

            return ReturnTable({
                attribute: [getattr(result, attribute)]
                for attribute in return_attributes
            })

        return result

    if arguments[0] == "findre":
        if len(arguments) < 2:
            return "Usage: findre <name-or-id> [return <attribute> ...]"

        value = arguments[1]
        return_attributes = None

        if "return" in arguments[2:]:
            return_index = arguments.index("return", 2)
            return_attributes = arguments[return_index + 1:]

            if not return_attributes:
                return "Usage: findre <name-or-id> return <attribute> ..."

            for attribute in return_attributes:
                if attribute not in reactionKeys:
                    return f"There is no key `{attribute}`"

            if return_index != 2:
                return "Usage: findre <name-or-id> [return <attribute> ...]"

        elif len(arguments) > 2:
            return "Usage: findre <name-or-id> [return <attribute> ...]"

        result = execute([
            "search", "reactions",
            "name", "like", value,
            "or", "id", "like", value,
            "or", "equation", "like", value,
        ])

        if result == [] or result == "No matching item":
            return f"Could not find reaction `{value}`"

        if return_attributes:
            if isinstance(result, list):
                return project_results(result, return_attributes)

            return ReturnTable({
                attribute: [getattr(result, attribute)]
                for attribute in return_attributes
            })

        return result

    if arguments[0] == "clear":
        if len(arguments) != 1:
            return "Usage: clear"

        print("\033[2J\033[H", end="")
        return

    if arguments[0] == "source":
        if len(arguments) != 2:
            return "Usage: source <source>"

        source_name = arguments[1]

        if source_name not in SOURCES:
            return f"There is no source `{source_name}`"

        current_source = source_name
        return f"Source set to `{source_name}`"

    if arguments[0] == "list":
        if len(arguments) != 2 or arguments[1] != "all":
            return "Usage: list all"

        if current_source is None:
            return list(SOURCES)

        _, keys = SOURCES[current_source]
        return list(keys)

    if arguments[0] == "search":
        i = 1
        mode = "all"

        if i < len(arguments) and arguments[i] in ("first", "last", "all"):
            mode = arguments[i]
            i += 1

        if (
            i + 1 < len(arguments)
            and arguments[i] in SOURCES
            and (
                current_source is None
                or arguments[i + 1] not in operators
            )
        ):
            source_name = arguments[i]
            i += 1
        else:
            source_name = current_source

        if source_name is None:
            return (
                "No source selected. "
                "Specify one, e.g. "
                "`search all elements atomic_mass < 100`"
            )

        source, keys = SOURCES[source_name]
        if i >= len(arguments):
            return list(source)
        return_attributes = None

        if "return" in arguments[i:]:
            return_index = arguments.index("return", i)
            query_tokens = arguments[i:return_index]
            return_attributes = arguments[return_index + 1:]

            if not return_attributes:
                return format_error("Usage: return <attribute> [<attribute> ...]", query_text)

            for attribute_index, attribute in enumerate(return_attributes):
                if attribute not in keys:
                    absolute_index = return_index + 1 + attribute_index
                    pos, length = error_position(positions, absolute_index) if positions else (None, 1)
                    return format_error(
                        f"There is no key `{attribute}`",
                        query_text,
                        pos,
                        length
                    )
        else:
            query_tokens = arguments[i:]

        try:
            condition, operation_index = parse_query(
                query_tokens,
                source,
                keys,
                positions[i:] if positions else None
            )
        except ChemQLError as e:
            return format_error(str(e), query_text, e.position, e.length)
        except ValueError as e:
            return format_error(str(e))

        results = [item for item in source if condition(item)]

        try:
            results = apply_query_operations(
                results,
                query_tokens[operation_index:],
                keys,
                positions[i + operation_index:] if positions else None
            )
        except ChemQLError as e:
            return format_error(str(e), query_text, e.position, e.length)
        except ValueError as e:
            return format_error(str(e))

        if isinstance(results, int):
            if mode != "all":
                return format_error("`count` cannot be combined with `first` or `last`")
            if return_attributes is not None:
                return format_error("`return` cannot be used with `count`")
            return results

        # `return` is a projection. It intentionally happens after
        # filtering, sorting, limiting, and first/last selection.
        if return_attributes is not None:
            if mode == "first":
                selected = results[:1]
            elif mode == "last":
                selected = results[-1:]
            else:
                selected = results

            if not selected:
                if len(return_attributes) == 1:
                    return []
                return ReturnTable({attribute: [] for attribute in return_attributes})

            return project_results(selected, return_attributes)

        if mode == "first":
            result = results[0] if results else None
        elif mode == "last":
            result = results[-1] if results else None
        else:
            if len(results) == 1:
                result = results[0]
            else:
                result = results

        if result is None:
            return "No matching item"

        return result

    if query_text is not None and positions:
        pos, length = error_position(positions, 0)
        return format_error(
            f"Unknown command `{arguments[0]}`",
            query_text,
            pos,
            length
        )

    return format_error(f"Unknown command `{arguments[0]}`")

HELP = '\x1b[1;94m╭──────────────────────────────────────────────────────────────────────────────╮\x1b[0m\n\x1b[1;94m│\x1b[0m  \x1b[1;96m✦ \x1b[1mChemQL\x1b[0m \x1b[97mv1.2.0\x1b[0m \x1b[90m│\x1b[0m \x1b[1m\x1b[97mTHE PYTHON CHEMISTRY QUERY LANGUAGE\x1b[0m                         \x1b[1;94m│\x1b[0m\n\x1b[1;94m│\x1b[0m  \x1b[90mQuery chemical datasets · balance equations · embed Python · automate workflows\x1b[0m   \x1b[1;94m│\x1b[0m\n\x1b[1;94m╰──────────────────────────────────────────────────────────────────────────────╯\x1b[0m\n\n\x1b[1;93m\x1b[1m▶  QUICK START\x1b[0m\n  \x1b[92msearch elements ...          \x1b[0m \x1b[90m│\x1b[0m Query the periodic-table dataset\n  \x1b[92msearch molecules ...         \x1b[0m \x1b[90m│\x1b[0m Query molecule records\n  \x1b[92msearch reactions ...         \x1b[0m \x1b[90m│\x1b[0m Query stored reaction records\n  \x1b[92mfindel "He"                  \x1b[0m \x1b[90m│\x1b[0m Find an element by name or symbol\n  \x1b[92mfindmol "Water"              \x1b[0m \x1b[90m│\x1b[0m Find a molecule by name or formula\n  \x1b[92mfindre "Haber process"       \x1b[0m \x1b[90m│\x1b[0m Find a reaction by name, ID, or equation\n  \x1b[92mlist all                     \x1b[0m \x1b[90m│\x1b[0m List available fields and sources\n  \x1b[92mhelp  or  ?                  \x1b[0m \x1b[90m│\x1b[0m Show this help reference\n  \x1b[92mversion                      \x1b[0m \x1b[90m│\x1b[0m Show the installed version\n  \x1b[92mexit                         \x1b[0m \x1b[90m│\x1b[0m Leave the interactive prompt\n\n\x1b[1;93m\x1b[1m◆  QUERY SOURCES & EXAMPLES\x1b[0m\n  \x1b[92msearch elements [where]      \x1b[0m \x1b[90m│\x1b[0m Search element data\n  \x1b[92msearch molecules [where]     \x1b[0m \x1b[90m│\x1b[0m Search molecule data\n  \x1b[92msearch reactions [where]     \x1b[0m \x1b[90m│\x1b[0m Search reaction data\n  \x1b[1;96msource elements|molecules|reactions\x1b[0m \x1b[90m│\x1b[0m Set the current source\n    \x1b[95msearch elements symbol = "Fe" return name symbol number atomic_mass\x1b[0m\n    \x1b[95msearch molecules molecular_weight < 50 sort molecular_weight limit 10\x1b[0m\n    \x1b[95msearch reactions reversible = true return name equation source\x1b[0m\n\n\x1b[1;93m\x1b[1m◆  FILTERS & LOGIC\x1b[0m\n  \x1b[1;96m=   !=   >   <   >=   <=     \x1b[0m \x1b[90m│\x1b[0m Comparison operators\n  \x1b[1;96mlike  /  like!               \x1b[0m \x1b[90m│\x1b[0m Case-insensitive / case-sensitive wildcard matching\n  \x1b[1;96mlikep  /  has                \x1b[0m \x1b[90m│\x1b[0m Pattern matching / contains an item\n  \x1b[1;96mand  /  or  /  ( ... )       \x1b[0m \x1b[90m│\x1b[0m Combine conditions; parentheses group logic\n    \x1b[95msearch elements number > 10 and number < 20\x1b[0m\n    \x1b[95msearch molecules name like "*water*"\x1b[0m\n    \x1b[95msearch molecules (name like "*water*" or formula = "H2O") and molecular_weight < 25\x1b[0m\n\n\x1b[1;93m\x1b[1m◆  RESULT OPERATIONS\x1b[0m\n  \x1b[92mfirst  /  last               \x1b[0m \x1b[90m│\x1b[0m Return the first or last match\n  \x1b[92msort FIELD [asc|desc]        \x1b[0m \x1b[90m│\x1b[0m Sort matching records\n  \x1b[92mlimit N                      \x1b[0m \x1b[90m│\x1b[0m Limit the number of results\n  \x1b[92mcount                        \x1b[0m \x1b[90m│\x1b[0m Count matches\n  \x1b[92mreturn FIELD ...             \x1b[0m \x1b[90m│\x1b[0m Choose fields; one field lists, multiple fields form a table\n  \x1b[92munion / intersection         \x1b[0m \x1b[90m│\x1b[0m Combine result sets\n    \x1b[95msearch molecules molecular_weight < 20 sort molecular_weight asc limit 5\x1b[0m\n    \x1b[95msearch elements number < 10 union search elements number > 90\x1b[0m\n\n\x1b[1;93m\x1b[1m◆  REACTION TOOLS & CONDITIONS\x1b[0m\n  \x1b[1;96mset temperature 723K|150C|300F|standard|room    \x1b[0m \x1b[90m│\x1b[0m Set reaction temperature\n  \x1b[1;96mset pressure 101325Pa|2bar|1atm|standard|room   \x1b[0m \x1b[90m│\x1b[0m Set reaction pressure\n  \x1b[1;96mset catalysts iron zinc      \x1b[0m \x1b[90m│\x1b[0m Set the catalyst list\n  \x1b[1;96mset catalysts                \x1b[0m \x1b[90m│\x1b[0m Clear the catalyst list\n  \x1b[1;96madd catalyst "Vanadium oxide"\x1b[0m \x1b[90m│\x1b[0m Add a catalyst\n  \x1b[1;96mremove catalyst "Vanadium oxide"\x1b[0m \x1b[90m│\x1b[0m Remove a catalyst\n  \x1b[1;96mconditions                   \x1b[0m \x1b[90m│\x1b[0m Show active temperature, pressure, and catalysts\n  \x1b[1;96mreact N2 3H2                 \x1b[0m \x1b[90m│\x1b[0m Find a stored reaction matching reactants\n  \x1b[1;96mbalance H2 + O2 -> H2O       \x1b[0m \x1b[90m│\x1b[0m Balance an irreversible equation\n  \x1b[1;96mbalance N2 + H2 <-> NH3      \x1b[0m \x1b[90m│\x1b[0m Balance a reversible equation\n  \x1b[2mTemperature units: C, F, K. Pressure units include Pa, N/m^2, Nm^-2, bar, and atm.\x1b[0m\n  \x1b[2mPresets: standard = 0 C and 100000 Pa; room = 25 C and 101325 Pa.\x1b[0m\n\n\x1b[1;93m\x1b[1m◆  PREPROCESSOR, FUNCTIONS & MACROS  ·  V1.2.0\x1b[0m\n  \x1b[95mdefine MAX 9                 \x1b[0m \x1b[90m│\x1b[0m Define a literal replacement used as @MAX\n  \x1b[95mdefinitions                  \x1b[0m \x1b[90m│\x1b[0m List current literal definitions\n  \x1b[95mremove definition MAX        \x1b[0m \x1b[90m│\x1b[0m Remove a definition\n    \x1b[95mdefine MAX 9\x1b[0m\n    \x1b[95msearch elements number <= @MAX\x1b[0m\n\n  \x1b[95mfunc square                  \x1b[0m \x1b[90m│\x1b[0m Begin a function; finish it with endfunc\n  \x1b[95mreturn [\\1 * \\1]             \x1b[0m \x1b[90m│\x1b[0m Return a value using positional argument \\1\n  \x1b[95mendfunc                      \x1b[0m \x1b[90m│\x1b[0m Close the function definition\n  \x1b[95msquare{5}                    \x1b[0m \x1b[90m│\x1b[0m Call the function with brace-delimited arguments\n\n  \x1b[95mdefine light{}               \x1b[0m \x1b[90m│\x1b[0m Begin a macro; finish it with enddefine\n    \x1b[95msearch molecules molecular_weight < \\1 return name formula\x1b[0m\n  \x1b[95menddefine                    \x1b[0m \x1b[90m│\x1b[0m Close the macro definition\n  \x1b[95m@light{50}                   \x1b[0m \x1b[90m│\x1b[0m Expand and execute a macro\n  \x1b[2mFunction and macro arguments use positional placeholders: \\1, \\2, and so on.\x1b[0m\n  \x1b[2mDefinitions are processed in source order and are local to the current session.\x1b[0m\n\n\x1b[1;93m\x1b[1m◆  PYTHON INTEGRATION\x1b[0m\n  \x1b[1;96m[x = 10]                     \x1b[0m \x1b[90m│\x1b[0m Execute a Python statement\n  \x1b[1;96m[print(x)]                   \x1b[0m \x1b[90m│\x1b[0m Use Python variables across commands\n  \x1b[1;96m[x * 2]                      \x1b[0m \x1b[90m│\x1b[0m Evaluate and display a Python expression\n    \x1b[95m{{ search elements name = "Hydrogen" }}\x1b[0m\n  \x1b[2mEmbedded {{ ... }} queries return their result as a value.\x1b[0m\n  Python control-flow blocks:\n    \x1b[95m[if condition] ... [elif condition] ... [else] ... [endblock]\x1b[0m\n    \x1b[95m[for item in iterable] ... [endblock]\x1b[0m\n    \x1b[95m[while condition] ... [endblock]\x1b[0m\n    \x1b[95m[break] and [continue] inside loops\x1b[0m\n  Multiline Python block:\n    \x1b[95m[[[\x1b[0m\n    \x1b[95mfor x in range(3):\x1b[0m\n    \x1b[95m    print(x)\x1b[0m\n    \x1b[95m]]]   # close on its own line\x1b[0m\n\n\x1b[1;93m\x1b[1m◆  SHELL, COMMENTS & COMMAND COMPOSITION\x1b[0m\n  \x1b[1;96m`command`                    \x1b[0m \x1b[90m│\x1b[0m Run a command in the persistent system shell\n  \x1b[1;96m```bash ... ```              \x1b[0m \x1b[90m│\x1b[0m Run a multiline shell block (also sh, cmd, terminal)\n  \x1b[1;96m// comment                   \x1b[0m \x1b[90m│\x1b[0m Single-line comment\n  \x1b[1;96m/// ... ///                  \x1b[0m \x1b[90m│\x1b[0m Multiline comment\n  \x1b[1;96mcommand1; command2           \x1b[0m \x1b[90m│\x1b[0m Run multiple commands on one line\n  \x1b[1;96mtrailing backslash           \x1b[0m \x1b[90m│\x1b[0m Continue a command on the next line\n  \x1b[1;96mview                         \x1b[0m \x1b[90m│\x1b[0m Open the bundled periodic-table viewer\n  \x1b[1;96mclear                        \x1b[0m \x1b[90m│\x1b[0m Clear the terminal\n\n\x1b[1;93m\x1b[1m◆  HISTORY EXPORT\x1b[0m\n  \x1b[92mdump FILE                    \x1b[0m \x1b[90m│\x1b[0m Export all recorded queries and results\n  \x1b[92mdump all|good|bad FILE       \x1b[0m \x1b[90m│\x1b[0m Export all, successful, or failed executions\n  \x1b[92mdump all|good|bad queries FILE\x1b[0m \x1b[90m│\x1b[0m Export query history\n  \x1b[92mdump all|good|bad results FILE\x1b[0m \x1b[90m│\x1b[0m Export result history\n\n\x1b[1;93m\x1b[1m◆  COMMAND-LINE OPTIONS\x1b[0m\n  \x1b[1;96mchemql                       \x1b[0m \x1b[90m│\x1b[0m Start the interactive prompt\n  \x1b[1;96mchemql -c "COMMAND"          \x1b[0m \x1b[90m│\x1b[0m Execute one command\n  \x1b[1;96mchemql -f FILE               \x1b[0m \x1b[90m│\x1b[0m Execute commands from a file\n  \x1b[1;96mchemql --version             \x1b[0m \x1b[90m│\x1b[0m Print the installed version\n  \x1b[1;96mchemql --no-ansi             \x1b[0m \x1b[90m│\x1b[0m Disable ANSI styling in output\n  \x1b[1;96mchemql -c "COMMAND" -o FILE  \x1b[0m \x1b[90m│\x1b[0m Write command output to a plain-text file\n  \x1b[1;96mchemql --upgrade [VERSION]   \x1b[0m \x1b[90m│\x1b[0m Upgrade to latest or a chosen release\n  \x1b[1;96mchemql --force               \x1b[0m \x1b[90m│\x1b[0m Force upgrade past system-package protections\n\n\x1b[1;93m\x1b[1m◆  PYTHON API\x1b[0m\n    \x1b[95mfrom chemql import execute_query_text, execute_query\x1b[0m\n    \x1b[95mresult = execute_query_text(\'search elements symbol = "O"\')\x1b[0m\n  \x1b[2mDistribution package: chemql-python  ·  import / CLI name: chemql\x1b[0m\n\n\x1b[1;93m\x1b[1m⚠  SAFETY & DATA NOTES\x1b[0m\n  \x1b[2mPython blocks and shell commands run real code with your user permissions.\x1b[0m\n  \x1b[2mRun only code and commands you trust. External lookups need network access\x1b[0m\n  \x1b[2mand can fail when a remote service is unavailable.\x1b[0m\n\n\x1b[1;94m────────────────────────────────────────────────────────────────────────────────\x1b[0m\n\x1b[90mChemQL 1.2.0  ·  Type \x1b[92mhelp\x1b[90m for this guide, or \x1b[92mexit\x1b[90m to quit.\x1b[0m\n'

import webbrowser
from pathlib import Path

def view_periodic_table():
    path = Path(__file__).parent / "html" /"periodic_table.html"
    webbrowser.open(path.resolve().as_uri())


class ChemqlLexer(Lexer):
    """Syntax highlighting for ChemQL, native variables, and embedded Python."""

    COMMANDS = {
        "search", "source", "list", "clear", "exit", "findel",
        "findmol", "findre", "set", "add", "remove", "react",
        "balance", "conditions", "view", "help", "dump", "version",
        "return", "union", "intersection", "let", "unset", "variables",
        "macros", "definitions", "arguments",
    }

    OPERATORS = {
        "and", "or", "has", "like", "like!", "likep", "sort",
        "limit", "count", "asc", "desc",
    }

    CONTROL_WORDS = {
        "if", "elif", "else", "for", "while", "in", "break",
        "continue", "endblock", "endfunc", "func", "enddefine",
        "define", "import", "as",
    }

    CONDITIONS = {
        "temperature", "pressure", "catalyst", "catalysts",
        "standard", "room", "c", "f", "k", "pa", "bar",
    }

    def lex_document(self, document):
        lines = document.lines

        def get_line(lineno):
            if lineno >= len(lines):
                return []

            line = lines[lineno]
            tokens = []
            i = 0

            # Preserve leading indentation.
            while i < len(line) and line[i].isspace():
                start = i
                while i < len(line) and line[i].isspace():
                    i += 1
                tokens.append(("", line[start:i]))

            # Highlight a leading ChemQL command.
            first_match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", line[i:])
            if first_match:
                word = first_match.group(0)
                if word in self.COMMANDS:
                    tokens.append(("class:command", word))
                    i += len(word)

            while i < len(line):
                # Whitespace
                if line[i].isspace():
                    start = i
                    while i < len(line) and line[i].isspace():
                        i += 1
                    tokens.append(("", line[start:i]))
                    continue

                # Comments
                if line.startswith("//", i):
                    tokens.append(("class:comment", line[i:]))
                    break

                # # Embedded ChemQL expressions: {{ ... }}
                # # Embedded ChemQL expressions: {{ ... }}
                # if line.startswith("{{", i):
                #     try:
                #         end = find_matching(line, i + 2, "{{", "}}")
                #     except SyntaxError:
                #         # The user may still be typing the expression.
                #         tokens.append(("class:interpolation", line[i:]))
                #         break

                #     if end is None:
                #         tokens.append(("class:interpolation", line[i:]))
                #         break

                #     end += 2
                #     tokens.append(("class:interpolation", line[i:end]))
                #     i = end
                #     continue

                # Backtick shell commands
                if line[i] == "`":
                    end = line.find("`", i + 1)
                    if end == -1:
                        end = len(line) - 1

                    tokens.append((
                        "class:terminalcommand",
                        line[i:end + 1]
                    ))
                    i = end + 1
                    continue

                # # Python blocks and single-line Python statements
                # if line[i] == "[":
                #     try:
                #         end = find_matching(line, i + 1, "[", "]")
                #     except SyntaxError:
                #         # An unfinished bracket is valid while editing.
                #         tokens.append(("class:python", line[i:]))
                #         break

                #     if end is not None:
                #         end += 1
                #         tokens.append(("class:python", line[i:end]))
                #         i = end
                #         continue

                #     tokens.append(("class:python", line[i]))
                #     i += 1
                #     continue

                # Strings
                if line[i] in "\"'":
                    quote = line[i]
                    start = i
                    i += 1

                    while i < len(line):
                        if line[i] == "\\":
                            i += 2
                            continue
                        if line[i] == quote:
                            i += 1
                            break
                        i += 1

                    tokens.append(("class:string", line[start:i]))
                    continue

                # Numbers
                if line[i].isdigit():
                    start = i
                    i += 1
                    while i < len(line) and (
                        line[i].isdigit() or line[i] == "."
                    ):
                        i += 1

                    tokens.append(("class:number", line[start:i]))
                    continue

                # Operators
                operator = next(
                    (
                        op for op in (
                            "!=", ">=", "<=", "==", "=", ">", "<",
                            "+=", "-=", "*=", "/=", "+", "-", "*", "/",
                    )
                        if line.startswith(op, i)
                    ),
                    None,
                )

                if operator:
                    tokens.append(("class:operator", operator))
                    i += len(operator)
                    continue

                # Identifiers and keywords
                if line[i].isalpha() or line[i] == "_":
                    start = i
                    while i < len(line) and (
                        line[i].isalnum() or line[i] == "_"
                    ):
                        i += 1

                    word = line[start:i]

                    if word in self.COMMANDS:
                        style = "class:command"
                    elif word in self.CONTROL_WORDS:
                        style = "class:control"
                    elif word in {"True", "False", "None"}:
                        style = "class:number"
                    elif word in {"print", "len", "str", "int", "float", "range"}:
                        style = "class:python"
                    elif word in SOURCES:
                        style = "class:source"
                    elif word.casefold() in self.CONDITIONS:
                        style = "class:condition"
                    elif word in self.OPERATORS:
                        style = "class:operator"
                    elif (
                        word in CHEMQL_VARIABLES
                        or word in python_globals
                    ):
                        style = "class:variable"
                    elif (
                        word in elementKeys
                        or word in moleculeKeys
                        or word in reactionKeys
                    ):
                        style = "class:key"
                    else:
                        style = ""

                    tokens.append((style, word))
                    continue

                # Other punctuation
                tokens.append(("", line[i]))
                i += 1

            return tokens

        return get_line


class ChemqlCompleter(Completer):
    """Context-aware completion for ChemQL commands and variables."""

    COMMANDS = (
        "search", "source", "list", "clear", "return", "exit",
        "findel", "findmol", "findre", "set", "add", "remove",
        "react", "balance", "conditions", "version", "help", "view",
        "dump", "let", "unset", "variables", "func", "define",
        "import", "definitions", "macros",
    )

    QUERY_OPERATORS = [
        "=", "!=", ">", "<", ">=", "<=", "like", "like!",
        "likep", "has", "sort", "limit", "count", "asc",
        "desc", "return", "and", "or",
    ]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        parts = text.split()
        trailing_space = bool(text and text[-1].isspace())

        current = "" if trailing_space or not parts else parts[-1]
        command_words = parts if trailing_space else parts[:-1]

        def emit(suggestions):
            seen = set()
            for suggestion in suggestions:
                suggestion = str(suggestion)
                key = suggestion.casefold()

                if (
                    key not in seen
                    and key.startswith(current.casefold())
                ):
                    seen.add(key)
                    yield Completion(
                        suggestion,
                        start_position=-len(current),
                    )

        # At the beginning of a command, suggest commands and variables.
        if not command_words:
            suggestions = list(self.COMMANDS)
            suggestions.extend(
                sorted(CHEMQL_VARIABLES)
            )
            yield from emit(suggestions)
            return

        command = command_words[0]
        suggestions = []

        # Native variable syntax
        if command == "let":
            if len(command_words) == 1:
                suggestions = ["name = value"]
            elif len(command_words) >= 2:
                suggestions = ["="]

        elif command == "unset":
            suggestions = sorted(CHEMQL_VARIABLES)

        elif command == "variables":
            suggestions = []

        # Source names
        elif command in {"search", "source"}:
            if len(command_words) == 1:
                suggestions = list(SOURCES)
            elif command == "search" and len(command_words) >= 2:
                source_name = command_words[1]
                if source_name in SOURCES:
                    _, keys = SOURCES[source_name]
                    suggestions = list(keys) + self.QUERY_OPERATORS

        # Reaction settings
        elif command == "set":
            if len(command_words) == 1:
                suggestions = [
                    "temperature", "pressure", "catalysts"
                ]
            elif len(command_words) == 2:
                setting = command_words[1].casefold()

                if setting == "temperature":
                    suggestions = [
                        "standard", "room", "0C", "0F", "0K"
                    ]
                elif setting == "pressure":
                    suggestions = [
                        "standard", "room", "0Pa",
                        "0N/m^2", "0Nm^-2", "0bar",
                    ]
                elif setting == "catalysts":
                    suggestions = list(
                        reaction_state["catalysts"]
                    )

        # Catalyst management
        elif command in {"add", "remove"}:
            if len(command_words) == 1:
                suggestions = ["catalyst"]
            elif (
                command == "remove"
                and len(command_words) == 2
                and command_words[1] == "catalyst"
            ):
                suggestions = list(
                    reaction_state["catalysts"]
                )

        # Variable names can be useful in expressions.
        elif command in {"print", "return"}:
            suggestions = sorted(CHEMQL_VARIABLES)

        # Offer native variables in other expression contexts too.
        if not suggestions and (
            "{{" in text
            or text.lstrip().startswith("[")
        ):
            suggestions = sorted(CHEMQL_VARIABLES)

        yield from emit(suggestions)


        
chemql_style = Style.from_dict({
    "command": "ansicyan",
    "terminalcommand": "ansipurple",
    "comment": "#545454 bold underline",
    "source": "ansiblue",
    "key": "ansimagenta",
    "operator": "ansiyellow",
    "string": "ansigreen",
    "number": "ansimagenta",
    "control": "ansired",
    "python": "ansibrightcyan",
    "condition": "ansibrightyellow",
})




class _ChemQLField:
    """Field selector used by the fluent Python query API."""
    def __init__(self, query, field):
        self.query = query
        self.field = field

    def condition(self, **conditions):
        operators = {
            "eq": "=", "ne": "!=", "lt": "<", "lte": "<=",
            "gt": ">", "gte": ">=", "like": "like", "likep": "likep",
            "has": "has",
        }
        if len(conditions) != 1:
            raise ValueError("condition() expects exactly one condition, e.g. lt=10")
        name, value = next(iter(conditions.items()))
        if name not in operators:
            raise ValueError(f"Unknown condition {name!r}; use {', '.join(operators)}")
        rendered = shlex.quote(str(value))
        return ChemQLQuery(f"{self.query.query} {self.field} {operators[name]} {rendered}")


class ChemQLQuery:
    """Composable ChemQL query. Use .execute() to evaluate it."""
    def __init__(self, query):
        self.query = str(query).strip()

    def __getattr__(self, field):
        if field.startswith("_"):
            raise AttributeError(field)
        return _ChemQLField(self, field)

    def return_(self, *attributes):
        if not attributes:
            raise ValueError("return_() requires at least one attribute")
        return ChemQLQuery(f"{self.query} return " + " ".join(attributes))

    def execute(self):
        return execute_query_text(self.query)

    def __or__(self, other):
        if not isinstance(other, ChemQLQuery):
            return NotImplemented
        return ChemQLQuery(f"{self.query} union {other.query}")

    def __and__(self, other):
        if not isinstance(other, ChemQLQuery):
            return NotImplemented
        return ChemQLQuery(f"{self.query} intersection {other.query}")

    def __str__(self):
        return f"Query of `{self.query}`"

    def __repr__(self):
        return str(self)


def search(source):
    """Create a native Python API query, e.g. search('elements')."""
    source = str(source).strip()
    if source not in SOURCES:
        raise ValueError(f"Unknown ChemQL source {source!r}; expected one of {', '.join(SOURCES)}")
    return ChemQLQuery(f"search {source}")


def union(x, y):
    """Return the left-to-right union of two ChemQLQuery objects."""
    if not isinstance(x, ChemQLQuery) or not isinstance(y, ChemQLQuery):
        raise TypeError("union() expects two ChemQLQuery objects")
    return x | y


def intersection(x, y):
    """Return the intersection of two ChemQLQuery objects."""
    if not isinstance(x, ChemQLQuery) or not isinstance(y, ChemQLQuery):
        raise TypeError("intersection() expects two ChemQLQuery objects")
    return x & y

PACKAGE_NAME = "chemql-python"

def upgrade_package(version=None, force=False):
    """Upgrade ChemQL, optionally to a specific version."""

    if version is not None:
        # Accept ordinary numeric release versions, optionally with
        # prerelease or post-release suffixes.
        if not re.fullmatch(
            r"\d+(?:\.\d+)*(?:(?:a|b|rc)\d+)?(?:\.post\d+)?(?:\.dev\d+)?",
            version,
            re.IGNORECASE,
        ):
            print(f"Invalid version: {version}", file=sys.stderr)
            return 2

        target = f"{PACKAGE_NAME}=={version}"
        print(f"Installing {target}...")
        if force:
            cmd = [
                sys.executable, "-m", "pip", "install",
                "--force-reinstall", target, "--break-system-packages"
            ]
        else:
            cmd = [
                sys.executable, "-m", "pip", "install",
                "--force-reinstall", target,
            ]
    else:
        print(f"Upgrading {PACKAGE_NAME} to the latest version...")
        if force:
            cmd = [
                sys.executable, "-m", "pip", "install",
                "--upgrade", PACKAGE_NAME, "--break-system-packages"
            ]
        else:
            cmd = [
                sys.executable, "-m", "pip", "install",
                "--upgrade", PACKAGE_NAME,
            ]

    try:
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            print(
                f"Installation failed (exit code {result.returncode}).",
                file=sys.stderr,
            )
            return result.returncode

    except KeyboardInterrupt:
        print("\nUpgrade cancelled.", file=sys.stderr)
        return 130
    except OSError as exc:
        print(f"Could not run pip: {exc}", file=sys.stderr)
        return 1

    print("ChemQL installation completed.")
    return 0


ChemQLQuery.__name__ = "ChemQLQuery"
ChemQLQuery.__qualname__ = "ChemQLQuery"


def main():
    parser = argparse.ArgumentParser(
        description="Chemql query and chemistry language"
    )

    parser.add_argument(
        "-c",
        "--command",
        help="Execute Chemql code"
    )

    parser.add_argument(
        "-f",
        "--file",
        help="Execute Chemql code from a file"
    )

    parser.add_argument(
        "--no-ansi",
        action="store_true",
        help="Strip ANSI escape sequences from output.",
    )

    parser.add_argument(
        "-o", "--output",
        metavar="FILE",
        help="Write -c or -f output to a file without ANSI sequences.",
    )

    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=__version__,
    )


    parser.add_argument(
        "--upgrade",
        nargs="?",
        const="latest",
        default=None,
        metavar="VERSION",
        help="Upgrade ChemQL, optionally to a specific version.",
    )

    parser.add_argument(
    "--force",
    "--dangerously",
    dest="force",
    action="store_true",
    help="Force the upgrade, including breaking system-package protections.",
    )

    args = parser.parse_args()

    if args.upgrade is not None:
        version_target = (
            None if args.upgrade == "latest" else args.upgrade
        )
        sys.exit(upgrade_package(version_target, args.force))

    global NO_ANSI
    NO_ANSI = args.no_ansi or bool(args.output)

    if args.output and args.command is None and args.file is None:
        parser.error("-o/--output requires -c/--command or -f/--file")

    if args.command is not None or args.file:
        if args.command is not None:
            code = args.command
        else:
            code = Path(args.file).read_text(encoding="utf-8")

        if args.output:
            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()
            with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
                process_lines(code.splitlines())
            output_text = stdout_capture.getvalue() + stderr_capture.getvalue()
            Path(args.output).write_text(strip_ansi(output_text), encoding="utf-8")
        else:
            process_lines(code.splitlines())
        return

    if not sys.stdin.isatty():
        piped = sys.stdin.read()
        if piped.strip():
            process_lines(piped.splitlines())
        else:
            run_interactive()
    else:
        run_interactive()

def run_interactive():
        history = []
        welcome = "Type help or ? for help"
        print(welcome if NO_ANSI else "\033[1m" + welcome + "\033[0m")
        bindings = KeyBindings()

        def multiline_input_needs_more(text):
            """Return True when Enter should add a newline instead of submitting."""
            if not text:
                return False
            source_lines = text.splitlines()
            first = source_lines[0].strip()
            last = source_lines[-1].strip()

            if last.endswith("\\"):
                return True

            if first in {"[[[", "```", "```bash", "```sh", "```cmd", "```terminal"}:
                closer = "]]]" if first == "[[[" else "```"
                return not (len(source_lines) > 1 and last == closer)

            if re.fullmatch(r"func\s+" + _DEFINITION_NAME, first, re.IGNORECASE):
                return last.casefold() != "endfunc"

            if re.fullmatch(r"define\s+" + _DEFINITION_NAME + r"\s*\{\s*\}", first):
                return last.casefold() != "enddefine"

            if "///" in first:
                return sum(line.count("///") for line in source_lines) < 2

            if is_python_block_header(first):
                depth = 0
                for line in source_lines:
                    stripped = line.strip()
                    if is_python_block_header(stripped):
                        depth += 1
                    elif stripped == "[endblock]":
                        depth -= 1
                return depth > 0

            return False

        @bindings.add(Keys.Enter)
        def _handle_enter(event):
            buffer = event.current_buffer
            if multiline_input_needs_more(buffer.text):
                buffer.insert_text("\n")
            else:
                buffer.validate_and_handle()

        session = PromptSession(
            lexer=ChemqlLexer(),
            completer=ChemqlCompleter(),
            style=Style.from_dict({}) if NO_ANSI else chemql_style,
            reserve_space_for_menu=0,
            multiline=True,
            key_bindings=bindings,
            prompt_continuation=lambda width, line_number, is_soft_wrap: "... ",
        )
        while True:
            try:
                first_line = session.prompt(">>> ")

            except KeyboardInterrupt:
                print()
                break

            except EOFError:
                message = "\nUse CTRL+C or type 'exit' to exit"
                print(message if NO_ANSI else "\n\033[34mUse \033[1mCTRL+C\033[22m or type '\033[1mexit\033[22m' to exit\033[0m")
                continue
            if first_line.strip() == "":
                continue
            elif first_line.strip() == "exit":
                break

            elif first_line.strip() in ("?", "help"):
                print(strip_ansi(HELP) if NO_ANSI else HELP)
                continue

            elif first_line.strip().lower() == "sorry":
                message = "It's ok, everybody makes mistakes👌"
                print(message if NO_ANSI else "\033[34m" + message + "\033[0m")
                continue
            
            elif first_line.strip().split()[0].casefold() == "dump":
                try:
                    print(_dump_history(first_line.strip()))
                except Exception as exc:
                    print(f"Error: {exc}")
                continue
        
            if not first_line.strip():
                continue

            # PromptSession now edits multiline blocks in one buffer, so the
            # user can move across lines and Backspace can join them.
            lines = first_line.splitlines() or [first_line]

            # Preserve the existing backslash continuation behavior for commands
            # that were not collected as a block by the Enter key binding.
            while lines[-1].rstrip().endswith("\\"):
                lines[-1] = lines[-1].rstrip()[:-1] + " "
                try:
                    next_line = session.prompt("... ")
                except KeyboardInterrupt:
                    print()
                    lines = []
                    break
                except EOFError:
                    message = "Error: Incomplete continued input"
                    print("\n" + (message if NO_ANSI else "\033[31m" + message + "\033[0m"))
                    lines = []
                    break
                lines.extend(next_line.splitlines() or [next_line])
            if not lines:
                continue

            # Collect function and macro declarations as complete REPL units.
            if lines and re.fullmatch(r"func\s+" + _DEFINITION_NAME, lines[0].strip(), re.IGNORECASE):
                while lines[-1].strip().casefold() != "endfunc":
                    try:
                        lines.append(session.prompt("... "))
                    except (KeyboardInterrupt, EOFError):
                        print("\nIncomplete function definition")
                        lines = []
                        break
                if not lines:
                    continue
            elif lines and re.fullmatch(r"define\s+" + _DEFINITION_NAME + r"\s*\{\s*\}", lines[0].strip()):
                while lines[-1].strip().casefold() != "enddefine":
                    try:
                        lines.append(session.prompt("... "))
                    except (KeyboardInterrupt, EOFError):
                        print("\nIncomplete macro definition")
                        lines = []
                        break
                if not lines:
                    continue

            # Collect new multiline Python, terminal, and comment blocks in the REPL.
            if lines and lines[0].strip() in {"[[[", "```", "```bash", "```sh", "```cmd", "```terminal"}:
                opener = lines[0].strip()
                closer = "]]]" if opener == "[[[" else "```"
                while not (len(lines) > 1 and lines[-1].strip() == closer):
                    try:
                        next_line = session.prompt("... ")
                    except (KeyboardInterrupt, EOFError):
                        print("\nIncomplete multiline block")
                        lines = []
                        break
                    lines.append(next_line)
                if not lines:
                    continue

            elif lines and "///" in lines[0]:
                # Collect multiline comment until its closing marker.
                while sum(line.count("///") for line in lines) < 2:
                    try:
                        next_line = session.prompt("... ")
                    except (KeyboardInterrupt, EOFError):
                        print("\nIncomplete multiline comment")
                        lines = []
                        break
                    lines.append(next_line)
                if not lines:
                    continue

            # Collect a Python control block only if the single editable buffer
            # was submitted before its matching [endblock] was entered.
            if lines and is_python_block_header(lines[0].strip()):
                depth = 0
                for existing_line in lines:
                    if is_python_block_header(existing_line.strip()):
                        depth += 1
                    elif existing_line.strip() == "[endblock]":
                        depth -= 1

                while depth > 0:
                    try:
                        line = session.prompt(">>> ")
                    except KeyboardInterrupt:
                        print()
                        lines = []
                        break
                    except EOFError:
                        message = "Missing `[endblock]`"
                        print("\n" + (message if NO_ANSI else "\033[31mMissing `\033[1m[endblock]\033[22m`\033[0m"))
                        lines = []
                        break

                    lines.extend(line.splitlines() or [line])
                    for added_line in (line.splitlines() or [line]):
                        if is_python_block_header(added_line.strip()):
                            depth += 1
                        elif added_line.strip() == "[endblock]":
                            depth -= 1
                if not lines:
                    continue

            try:
                process_lines(lines)
                history.extend(lines)
            except Exception as e:
                message = f"Error: {e}"
                print(message if NO_ANSI else f"\033[31m{message}\033[0m")


if __name__ == "__main__":
    main()
