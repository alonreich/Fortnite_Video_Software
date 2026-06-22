r"""
Multi-process MPV isolation layer.
Spawns each MPV engine as an independent OS process (its own PID) and talks to
it over a Windows Named Pipe (\\.\pipe\mpv-pipe-<id>). This completely decouples
the media engine from the Python runtime, eliminating the GIL deadlocks that
occurred when high-frequency libmpv C-callbacks contested with the UI thread
during rapid seeking.
``MpvProcessProxy`` is a drop-in, duck-typed replacement for the in-process
``mpv.MPV`` object returned by ``MPVSafetyManager.create_safe_mpv``. It exposes
the same attribute (``pause``, ``time_pos`` ...) and method (``command``,
``seek``, ``set_property`` ...) surface, plus the atomic seek state machine
(``_submit_gated_seek`` / ``_clear_seek_guard``) used by the safety manager.
"""

import os
import sys
import time
import json
import uuid
import queue
import shutil
import logging
import threading
import subprocess
import weakref
if sys.platform == 'win32':
    import win32file
    import win32pipe
    import pywintypes
else:
    win32file = None
    win32pipe = None
    pywintypes = None
_VALID_SEEK_PRECISIONS = ('unused', 'default-precise', 'keyframes', 'exact')
_PY_ATTR_TO_MPV_PROP = {
    'time_pos': 'time-pos',
    'idle_active': 'idle-active',
    'playback_time': 'playback-time',
    'duration': 'duration',
    'core_idle': 'core-idle',
    'eof_reached': 'eof-reached',
    'fullscreen': 'fullscreen',
    'pause': 'pause',
    'mute': 'mute',
    'speed': 'speed',
    'volume': 'volume',
    'path': 'path',
    'media_title': 'media-title',
    'seeking': 'seeking',
    'hr_seek': 'hr-seek',
    'keep_open': 'keep-open',
}
_KWARG_TO_FLAG = {
    'hr_seek': '--hr-seek',
    'keep_open': '--keep-open',
    'demuxer_max_bytes': '--demuxer-max-bytes',
    'demuxer_max_back_bytes': '--demuxer-max-back-bytes',
    'input_vo_keyboard': '--input-vo-keyboard',
    'input_default_bindings': '--input-default-bindings',
    'gpu_context': '--gpu-context',
    'msg_level': '--msg-level',
}
_INTERNAL_ATTRS = {
    'process', 'pipe_name', 'wid', 'handle', '_pipe',
    '_io_thread', '_write_queue',
    '_core_shutdown', '_safe_shutdown_initiated',
    '_seek_state_lock', '_seeking_active', '_seek_guard_start_mono',
    '_pending_seek_target', '_next_seek_target',
    '_tracked_event_callbacks', '_tracked_property_observers',
    '_event_handlers', '_observer_handlers', '_observer_ids',
    '_pending_requests', '_request_counter', '_request_lock',
    '_watchdog_thread', '_logger', '_argv',
}
_live_proxies = weakref.WeakSet()
_registry_lock = threading.Lock()

def shutdown_all_proxies(timeout=1.0):
    """Terminate every still-live MPV child process. Registered at exit."""
    with _registry_lock:
        proxies = list(_live_proxies)
    for proxy in proxies:
        try:
            proxy.terminate()
        except Exception:
            pass

def _resolve_mpv_executable():
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    candidates = [
        os.path.join(base, 'binaries', 'mpv.exe'),
        os.path.join(base, 'binaries', 'mpv.com'),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    found = shutil.which('mpv') or shutil.which('mpv.exe')
    if found:
        return found
    return None

def _serialize_mpv_value(value):
    """Serialize a Python value into the canonical form mpv accepts on the CLI.
    The classic GIL-crashing bug: ``str(False)`` is ``'False'`` (capitalized),
    but mpv only parses lowercase ``yes``/``no``/``true``/``false`` for flags.
    Passing ``--osc=False`` makes mpv abort during startup, so the IPC pipe is
    never created and ``create_safe_mpv`` silently fell back to the in-process
    libmpv binding that deadlocked the GIL under rapid seeking.
    """
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    return str(value)

def _connect_named_pipe(pipe_name, timeout=6.0):
    """Open a Windows named pipe that mpv creates asynchronously after launch.
    CRITICAL: On Windows, ``open(r'\\\\.\\pipe\\name', 'r+b')`` can BLOCK
    FOREVER when the pipe has been created by the server (mpv) but the server
    is still busy initializing its GPU/video context and hasn't reached
    ``ConnectNamedPipe`` yet. The naive retry loop never gets to re-check its
    deadline because a single ``open()`` call hangs indefinitely.
    Fix: poll ``CreateFile`` with a hard deadline. Once connected, force BYTE
    read-mode on the handle so mpv's MESSAGE-mode framing aligns with our
    line-based JSON protocol.
    """
    if sys.platform != 'win32':
        raise OSError('Named-pipe IPC is only supported on Windows.')
    if win32file is None:
        raise OSError('pywin32 is required for named-pipe IPC on Windows.')
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            handle = win32file.CreateFile(
                pipe_name,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None,
            )
            win32pipe.SetNamedPipeHandleState(
                handle, win32pipe.PIPE_READMODE_BYTE, None, None)
            return handle
        except pywintypes.error as exc:
            last_err = exc
            time.sleep(0.05)
    raise OSError(
        f'Failed to connect to mpv pipe {pipe_name} within {timeout}s: {last_err}'
    )

class MpvProcessProxy:
    """Duck-typed, process-isolated MPV engine speaking JSON IPC over a pipe."""

    def __init__(self, wid=None, **kwargs):
        self._logger = logging.getLogger('MpvProcessProxy')
        self._core_shutdown = False
        self._safe_shutdown_initiated = False
        self._pipe = None
        self._write_queue = queue.Queue(maxsize=256)
        self._io_thread = None
        self._wid = int(wid) if wid else None
        object.__setattr__(self, 'wid', self._wid)
        self._seek_state_lock = threading.RLock()
        self._seeking_active = False
        self._seek_guard_start_mono = 0.0
        self._pending_seek_target = None
        self._next_seek_target = None
        self._event_handlers = {}
        self._observer_handlers = {}
        self._observer_ids = {}
        self._tracked_event_callbacks = []
        self._tracked_property_observers = []
        self._pending_requests = {}
        self._request_counter = 0
        self._request_lock = threading.Lock()
        mpv_exe = _resolve_mpv_executable()
        if not mpv_exe:
            raise FileNotFoundError('mpv.exe not found in binaries/ or PATH.')
        self.pipe_name = f'\\\\.\\pipe\\mpv-pipe-{os.getpid()}-{uuid.uuid4().hex[:12]}'
        argv = self._build_argv(mpv_exe, kwargs)
        self._argv = argv
        creation = 0x08000000 if sys.platform == 'win32' else 0
        try:
            log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'logs'))
            os.makedirs(log_dir, exist_ok=True)
            self._mpv_stderr_path = os.path.join(
                log_dir, f'mpv-child-{os.getpid()}-{uuid.uuid4().hex[:8]}.log')
            stderr_target = open(self._mpv_stderr_path, 'wb', buffering=0)
        except Exception:
            self._mpv_stderr_path = None
            stderr_target = subprocess.DEVNULL
        self.process = subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=stderr_target,
            stdin=subprocess.DEVNULL,
            creationflags=creation,
        )
        self.handle = self.process.pid
        try:
            self._pipe = _connect_named_pipe(self.pipe_name)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass
            detail = ''
            if self._mpv_stderr_path and os.path.exists(self._mpv_stderr_path):
                try:
                    with open(self._mpv_stderr_path, 'r', errors='replace') as fh:
                        detail = fh.read().strip()
                except Exception:
                    detail = ''
            argv_str = ' '.join(str(a) for a in argv)
            raise OSError(
                f'Failed to connect to mpv pipe {self.pipe_name}.\n'
                f'ARGV: {argv_str}\n'
                f'MPV STDERR: {detail or "(empty)"}'
            )
        self._io_thread = threading.Thread(
            target=self._io_loop, name='mpv-pipe-io', daemon=True)
        self._io_thread.start()
        self._wait_until_ready(timeout=5.0)
        self._internal_observe('seeking', self._on_seeking_changed)
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, name='mpv-seek-watchdog', daemon=True)
        self._watchdog_thread.start()
        with _registry_lock:
            _live_proxies.add(self)

    def _wait_until_ready(self, timeout=5.0):
        """Block until mpv's IPC loop responds, or raise.
        ``idle-active`` is ``true`` the instant mpv's core is up, with no file
        loaded. A successful round-trip proves the writer, reader, and mpv's
        IPC loop are all live before we hand the proxy back to the caller.
        """
        deadline = time.monotonic() + timeout
        last_err = None
        while time.monotonic() < deadline:
            if self._core_shutdown or self.process.poll() is not None:
                last_err = 'mpv process exited during readiness probe'
                break
            try:
                val = self.get_property('idle-active', default=None, timeout=0.8)
            except Exception as exc:
                last_err = repr(exc)
                val = None
            if val is not None:
                return
            time.sleep(0.15)
        detail = ''
        if getattr(self, '_mpv_stderr_path', None) and os.path.exists(self._mpv_stderr_path):
            try:
                with open(self._mpv_stderr_path, 'r', errors='replace') as fh:
                    detail = fh.read().strip()[-2000:]
            except Exception:
                pass
        raise OSError(
            f'mpv IPC did not become responsive within {timeout}s '
            f'(last_err={last_err}). MPV STDERR: {detail or "(empty)"}'
        )

    def _build_argv(self, mpv_exe, kwargs):
        kw = dict(kwargs)
        kw.pop('log_handler', None)
        kw.pop('log_file', None)
        kw.pop('log-handler', None)
        kw.pop('log-file', None)
        kw.pop('start_event_thread', None)
        kw.pop('extra_mpv_flags', None)
        kw.pop('wid', None)
        kw.pop('loglevel', None)
        kw.pop('msg_level', None)
        argv = [
            mpv_exe,
            '--idle=yes',
            '--no-terminal',
            '--force-window=no',
            '--no-config',
            '--no-input-default-bindings',
            '--input-vo-keyboard=no',
            '--osc=no',
            '--no-ytdl',
            '--keep-open=yes',
            '--hr-seek=yes',
            f'--input-ipc-server={self.pipe_name}',
            '--msg-level=all=error',
        ]
        if self._wid:
            argv.append(f'--wid={int(self._wid)}')
        for key, value in kw.items():
            if value is None:
                continue
            flag = _KWARG_TO_FLAG.get(key)
            if flag is None:
                flag = '--' + key.replace('_', '-')
            argv.append(f'{flag}={_serialize_mpv_value(value)}')
        for flag, value in (kwargs.get('extra_mpv_flags') or []):
            argv.append(f'--{flag}={value}')
        return argv

    def _write_payload(self, payload):
        """Enqueue a JSON command for the I/O thread (non-blocking).
        NEVER calls ``WriteFile`` directly from the caller's thread. If the
        bounded queue is full (mpv overwhelmed or its IPC buffer not yet
        drained), the command is DROPPED rather than blocking - preserving UI
        responsiveness. The seek state machine already collapses rapid seek
        spam into the latest target, so a dropped intermediate command is
        harmless; only the most recent cached target will be flushed on seek
        completion.
        """
        if self._core_shutdown or self._safe_shutdown_initiated or self._pipe is None:
            return False
        data = (json.dumps(payload, separators=(',', ':')) + '\n').encode('utf-8')
        try:
            self._write_queue.put_nowait(data)
            return True
        except queue.Full:
            return False

    def _next_request_id(self):
        with self._request_lock:
            self._request_counter += 1
            return self._request_counter

    def _io_loop(self):
        """SINGLE-THREAD owner of ALL pipe I/O (both reads AND writes).
        Why single-threaded (the core architectural fix):
        pywin32's blocking ``ReadFile`` in non-overlapped mode holds the GIL
        while blocked. With a separate reader thread, the writer thread was
        starved (it could never acquire the GIL), which reproduced the EXACT
        GIL-deadlock symptom this layer was built to eliminate -
        ``get_property`` would hang forever in ``_wait_until_ready`` because
        the readiness-ping command was never written. The bisect proved it:
        inline single-threaded IPC works perfectly; the 2-thread wrapper
        deadlocks.
        The fix: ONE thread does EVERYTHING. Each iteration it (a) drains the
        write queue non-blockingly, then (b) uses ``PeekNamedPipe`` to check
        for inbound bytes WITHOUT blocking, and only calls ``ReadFile`` when
        bytes are actually pending. Because no call in this loop blocks
        indefinitely while holding the GIL, the UI thread and
        ``get_property`` requestors stay responsive.
        """
        q = self._write_queue
        buf = b''
        while not self._core_shutdown:
            drained_any = False
            while True:
                try:
                    data = q.get_nowait()
                except queue.Empty:
                    break
                drained_any = True
                if data is None:
                    self._core_shutdown = True
                    break
                try:
                    if self._pipe is not None:
                        win32file.WriteFile(self._pipe, data)
                except Exception:
                    self._core_shutdown = True
                    break
            if self._core_shutdown:
                break
            if self._pipe is not None:
                try:
                    available = win32pipe.PeekNamedPipe(self._pipe, 0)[1]
                except Exception:
                    self._core_shutdown = True
                    break
                if available > 0:
                    try:
                        result = win32file.ReadFile(
                            self._pipe, min(available, 65536))
                        chunk = result[1]
                    except Exception:
                        self._core_shutdown = True
                        break
                    if chunk:
                        buf += chunk
                        while b'\n' in buf:
                            line, buf = buf.split(b'\n', 1)
                            if not line:
                                continue
                            try:
                                obj = json.loads(
                                    line.decode('utf-8', errors='replace'))
                            except Exception:
                                continue
                            if 'event' in obj:
                                self._dispatch_event(obj)
                            elif 'request_id' in obj:
                                rid = obj.get('request_id')
                                fut = self._pending_requests.pop(rid, None)
                                if fut is not None:
                                    fut['response'] = obj
                                    fut['event'].set()
            time.sleep(0.005 if drained_any else 0.01)

    def _dispatch_event(self, obj):
        name = obj.get('event')
        if name == 'property-change':
            prop = obj.get('name')
            value = obj.get('data')
            for handler in list(self._observer_handlers.get(prop, [])):
                try:
                    handler(prop, value)
                except Exception:
                    pass
            return
        if name in ('playback-restart', 'seek'):
            self._schedule_clear_seek_guard(name)
        for handler in list(self._event_handlers.get(name, [])):
            try:
                handler(obj)
            except Exception:
                pass

    def _internal_observe(self, prop, handler):
        self._observer_handlers.setdefault(prop, []).append(handler)
        if prop not in self._observer_ids:
            oid = len(self._observer_ids) + 1
            self._observer_ids[prop] = oid
            self._write_payload({'command': ['observe_property', oid, prop]})

    def command(self, *args):
        if not args:
            return False
        return self._write_payload({'command': list(args)})

    def set_property(self, prop, value):
        return self._write_payload({'command': ['set_property', prop, value]})

    def get_property(self, prop, default=None, timeout=1.0):
        if self._core_shutdown or self._safe_shutdown_initiated or self._pipe is None:
            return default
        rid = self._next_request_id()
        box = {'event': threading.Event(), 'response': None}
        self._pending_requests[rid] = box
        ok = self._write_payload({'command': ['get_property', prop], 'request_id': rid})
        if not ok:
            self._pending_requests.pop(rid, None)
            return default
        if not box['event'].wait(timeout=timeout):
            self._pending_requests.pop(rid, None)
            return default
        resp = box['response'] or {}
        if resp.get('error') == 'success':
            return resp.get('data', default)
        return default

    def seek(self, target, reference='absolute', precision='exact'):
        return self._submit_gated_seek(float(target), reference, precision)

    def stop(self):
        return self.command('stop')

    def terminate(self):
        self._shutdown_process()

    def event_callback(self, event_name):
        def decorator(handler):
            self._event_handlers.setdefault(event_name, []).append(handler)
            return handler
        return decorator

    def property_observer(self, prop_name):
        def decorator(handler):
            self._internal_observe(prop_name, handler)
            self._tracked_property_observers.append((prop_name, handler))
            return handler
        return decorator

    def unobserve_property(self, name, handler):
        handlers = self._observer_handlers.get(name, [])
        if handler in handlers:
            handlers.remove(handler)

    def unregister_event_callback(self, handler):
        for handlers in list(self._event_handlers.values()):
            if handler in handlers:
                handlers.remove(handler)

    def __getattr__(self, name):
        if name.startswith('__') or name in _INTERNAL_ATTRS:
            raise AttributeError(name)
        prop = _PY_ATTR_TO_MPV_PROP.get(name, name.replace('_', '-'))
        return self.get_property(prop)

    def __setattr__(self, name, value):
        if name.startswith('_') or name in _INTERNAL_ATTRS or name in ('handle', 'pipe_name', 'process'):
            object.__setattr__(self, name, value)
            return
        prop = _PY_ATTR_TO_MPV_PROP.get(name, name.replace('_', '-'))
        if prop == 'wid':
            new_wid = int(value) if value else None
            object.__setattr__(self, '_wid', new_wid)
            object.__setattr__(self, 'wid', new_wid)
            if new_wid:
                try:
                    self.set_property('wid', new_wid)
                except Exception:
                    pass
            return
        self.set_property(prop, value)

    def _submit_gated_seek(self, target, reference='absolute', precision='exact'):
        if self._core_shutdown or self._safe_shutdown_initiated:
            return False
        if precision not in _VALID_SEEK_PRECISIONS:
            precision = 'keyframes'
        now = time.monotonic()
        with self._seek_state_lock:
            if self._seeking_active and (now - self._seek_guard_start_mono) > 2.0:
                self._seeking_active = False
            if self._seeking_active:
                self._next_seek_target = (target, reference, precision)
                self._pending_seek_target = (target, reference, precision)
                return True
            self._seeking_active = True
            self._seek_guard_start_mono = now
            self._next_seek_target = None
            self._pending_seek_target = None
        self._write_payload({'command': ['seek', float(target), reference, precision]})
        return True

    def _schedule_clear_seek_guard(self, reason='event'):
        if getattr(self, '_core_shutdown', False) or getattr(self, '_safe_shutdown_initiated', False):
            return
        try:
            from system.utils import _dispatch_on_qt_thread
        except Exception:
            _dispatch_on_qt_thread = None
        try:
            if _dispatch_on_qt_thread:
                _dispatch_on_qt_thread(lambda: self._clear_seek_guard(reason))
            else:
                self._clear_seek_guard(reason)
        except Exception:
            self._clear_seek_guard(reason)

    def _clear_seek_guard(self, reason='event', dispatch_pending=True):
        with self._seek_state_lock:
            was_active = self._seeking_active
            self._seeking_active = False
            self._seek_guard_start_mono = 0.0
            pending = self._next_seek_target
            self._next_seek_target = None
            self._pending_seek_target = None
        if dispatch_pending and was_active and pending is not None:
            t, r, p = pending
            self._submit_gated_seek(t, reference=r, precision=p)

    def _discard_stale_seek_guard(self, reason='stale'):
        self._clear_seek_guard(reason, dispatch_pending=False)

    def _on_seeking_changed(self, _name, value):
        if getattr(self, '_core_shutdown', False) or getattr(self, '_safe_shutdown_initiated', False):
            return
        if value in (False, None, 0):
            self._schedule_clear_seek_guard('seeking=false')

    def _watchdog_loop(self):
        while not self._core_shutdown and not self._safe_shutdown_initiated:
            time.sleep(0.5)
            if not getattr(self, '_seeking_active', False):
                continue
            try:
                started = float(getattr(self, '_seek_guard_start_mono', 0.0) or 0.0)
                if started and (time.monotonic() - started) > 2.5:
                    self._schedule_clear_seek_guard('watchdog-timeout')
            except Exception:
                pass

    def _shutdown_process(self):
        if self._core_shutdown and getattr(self, '_safe_shutdown_initiated', False):
            return
        self._safe_shutdown_initiated = True
        if self._pipe is not None and not self._core_shutdown:
            try:
                quit_data = (json.dumps({'command': ['quit']}, separators=(',', ':')) + '\n').encode('utf-8')
                try:
                    self._write_queue.put(quit_data, block=True, timeout=0.25)
                except queue.Full:
                    pass
            except Exception:
                pass
        try:
            self._write_queue.put(None, block=True, timeout=0.25)
        except Exception:
            pass
        iot = getattr(self, '_io_thread', None)
        if iot is not None:
            try:
                iot.join(timeout=1.0)
            except Exception:
                pass
        self._core_shutdown = True
        try:
            proc = getattr(self, 'process', None)
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=0.5)
                    except Exception:
                        proc.kill()
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            if self._pipe is not None:
                win32file.CloseHandle(self._pipe)
        except Exception:
            pass
        self._pipe = None

    def __del__(self):
        try:
            self._shutdown_process()
        except Exception:
            pass

import atexit
atexit.register(shutdown_all_proxies)