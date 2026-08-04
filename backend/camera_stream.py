"""
camera_stream.py
----------------
High-performance TCP frame receiver for the HapticGuide Android camera client.

Optimizations
-------------
  1. TCP_NODELAY disabled Nagle's algorithm for minimal packet latency.
  2. Zero-copy buffer reuse: reads directly into reusable memoryview buffers.
  3. Decoupled network and decoder threads via single-slot latest-wins RawJpegSlot.
  4. Real-time latency & throughput measurements (Recv FPS, Decode FPS, Decode Time, JPEG Size, Bandwidth, Frame Age).
"""

from __future__ import annotations

import struct
import threading
import time
import datetime
import socket

import cv2
import numpy as np

from shared_state import frame_slot, stream_stats, stop_event


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_TCP_PORT: int   = 9000      # must match SettingsManager.DEFAULT_PORT
STATS_INTERVAL_S: float = 1.0       # how often to print performance table
WINDOW_NAME:      str   = "HapticGuide — TCP Stream (Optimized)"

# Overlay style
_FONT       = cv2.FONT_HERSHEY_SIMPLEX
_FONT_SCALE = 0.50
_THICKNESS  = 1
_COLOR_OK   = (0, 255, 120)   # green — connected
_COLOR_ERR  = (0,  60, 255)   # red   — disconnected


# ---------------------------------------------------------------------------
# Low-level socket helper (Zero-allocation)
# ---------------------------------------------------------------------------

def _recvall_into(sock: socket.socket, target_buffer: bytearray, n: int) -> bool:
    """
    Read exactly *n* bytes from *sock* directly into *target_buffer*.

    Returns True on success, or False if connection closed or socket error.
    Extends target_buffer if needed, but avoids re-allocating on every frame.
    """
    if len(target_buffer) < n:
        target_buffer.extend(b"\x00" * (n - len(target_buffer)))

    view = memoryview(target_buffer)
    received = 0
    while received < n:
        try:
            chunk = sock.recv_into(view[received:n], n - received)
        except OSError:
            return False
        if chunk == 0:
            return False
        received += chunk
    return True


# ---------------------------------------------------------------------------
# Single-slot Raw JPEG Container (Drop-oldest, Latest-wins)
# ---------------------------------------------------------------------------

class _RawJpegSlot:
    """
    Single-frame raw JPEG slot with drop-oldest semantics.

    The network receiver thread pushes incoming JPEG payloads into this slot.
    If the dedicated decoder thread is busy decoding a previous frame, any new arrival
    overwrites the un-decoded raw JPEG (dropping it) and records a dropped frame.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._data: bytes | None = None
        self._recv_ts: float = 0.0

    def put(self, data: bytes, recv_ts: float) -> None:
        with self._cond:
            if self._data is not None:
                # Previous frame wasn't decoded in time — dropped for low latency
                stream_stats.record_dropped()
            self._data = data
            self._recv_ts = recv_ts
            self._cond.notify()

    def get(self, timeout: float = 0.05) -> tuple[bytes | None, float]:
        with self._cond:
            if self._data is None:
                self._cond.wait(timeout=timeout)
            if self._data is None:
                return None, 0.0
            data, ts = self._data, self._recv_ts
            self._data = None
            return data, ts

    def clear(self) -> None:
        with self._cond:
            self._data = None
            self._cond.notify_all()


# ---------------------------------------------------------------------------
# Per-client receive & decode handler
# ---------------------------------------------------------------------------

class _ClientHandler:
    """
    Handles one connected Android client.

    Spawns two dedicated daemon threads:
      1. Network thread (_recv_loop): Reads header + payload zero-copy into reusable buffer.
      2. Decoder thread (_decoder_loop): Decodes raw JPEGs using cv2.imdecode with zero-copy arrays.
    """

    def __init__(self, conn: socket.socket, addr: tuple) -> None:
        self._conn    = conn
        self._addr    = addr
        self.finished = False

        # Socket performance tuning: disable Nagle's algorithm & expand buffer
        try:
            self._conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512 * 1024)
        except OSError:
            pass

        self._raw_slot    = _RawJpegSlot()
        self._recv_buffer = bytearray(256 * 1024)   # reusable 256KB receive buffer
        self._header_buf  = bytearray(4)

        self._recv_thread = threading.Thread(
            target=self._recv_loop,
            name=f"tcp-recv-{addr[0]}:{addr[1]}",
            daemon=True,
        )
        self._decoder_thread = threading.Thread(
            target=self._decoder_loop,
            name=f"tcp-dec-{addr[0]}:{addr[1]}",
            daemon=True,
        )

    def start(self) -> None:
        self._decoder_thread.start()
        self._recv_thread.start()

    def stop(self) -> None:
        self.finished = True
        self._raw_slot.clear()
        try:
            self._conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._conn.close()
        except OSError:
            pass

    def _recv_loop(self) -> None:
        """Dedicated network receive loop."""
        print(
            f"[CameraStream] Connected  ←  {self._addr[0]}:{self._addr[1]}",
            flush=True,
        )
        stream_stats.increment_reconnect()

        try:
            while not stop_event.is_set() and not self.finished:
                # ── 1. Read 4-byte header zero-copy ───────────────────────────
                if not _recvall_into(self._conn, self._header_buf, 4):
                    break

                length: int = struct.unpack(">I", self._header_buf[:4])[0]
                if length == 0 or length > 20_000_000:
                    print(
                        f"[CameraStream] Bad frame length {length} — dropping connection",
                        flush=True,
                    )
                    stream_stats.record_dropped()
                    break

                # ── 2. Read JPEG payload into reusable buffer ─────────────────
                if not _recvall_into(self._conn, self._recv_buffer, length):
                    break

                recv_ts = time.monotonic()
                stream_stats.record_receive(length + 4)

                # Push raw payload copy to decoder thread (latest-wins)
                payload = bytes(memoryview(self._recv_buffer)[:length])
                self._raw_slot.put(payload, recv_ts)

        except Exception as exc:
            print(f"[CameraStream] Receive error: {exc}", flush=True)
        finally:
            self.finished = True
            self.stop()

    def _decoder_loop(self) -> None:
        """Dedicated frame decoder loop."""
        try:
            while not stop_event.is_set() and not self.finished:
                data, recv_ts = self._raw_slot.get(timeout=0.05)
                if data is None:
                    continue

                t_start = time.perf_counter()
                arr = np.frombuffer(data, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                decode_time_ms = (time.perf_counter() - t_start) * 1000.0

                if frame is None:
                    stream_stats.record_dropped()
                    continue

                frame_slot.put(frame)
                h, w = frame.shape[:2]
                age_ms = frame_slot.get_age_ms()
                stream_stats.record_decode(
                    decode_time_ms=decode_time_ms,
                    jpeg_size_bytes=len(data),
                    age_ms=age_ms,
                )

                stream_stats.mark_connected(
                    rtsp_url=f"tcp://{self._addr[0]}:{self._addr[1]}",
                    width=w,
                    height=h,
                )

        except Exception as exc:
            print(f"[CameraStream] Decoder error: {exc}", flush=True)
        finally:
            stream_stats.mark_disconnected()
            print(
                f"[CameraStream] Disconnected  ←  {self._addr[0]}:{self._addr[1]}",
                flush=True,
            )


# ---------------------------------------------------------------------------
# CameraStream — public API
# ---------------------------------------------------------------------------

class CameraStream:
    """
    TCP server that accepts one Android camera client at a time.

    Usage
    -----
        stream = CameraStream(tcp_port=9000, show_window=True)
        stream.start()
        ...
        frame, ts = stream.get_latest_frame()
        ...
        stream.stop()
    """

    def __init__(
        self,
        tcp_port:    int  = DEFAULT_TCP_PORT,
        show_window: bool = True,
        print_stats: bool = True,
        rtsp_url:    str  = "",      # legacy compat — ignored
    ) -> None:
        self._tcp_port    = tcp_port
        self._show_window = show_window
        self._print_stats = print_stats

        self._running          = False
        self._server_sock:  socket.socket | None  = None
        self._current_handler: _ClientHandler | None = None

        self._accept_thread:  threading.Thread | None = None
        self._stats_thread:   threading.Thread | None = None
        self._window_thread:  threading.Thread | None = None

    # =========================================================================
    # Public lifecycle
    # =========================================================================

    def start(self) -> None:
        """Bind the server socket and start daemon threads."""
        if self._running:
            return

        stop_event.clear()
        stream_stats.reset()
        self._running = True

        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("0.0.0.0", self._tcp_port))
        self._server_sock.listen(5)
        self._server_sock.settimeout(1.0)

        print(
            f"[CameraStream] TCP server listening on port {self._tcp_port}",
            flush=True,
        )

        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name="tcp-accept",
            daemon=True,
        )
        self._stats_thread = threading.Thread(
            target=self._stats_printer_loop,
            name="tcp-stats",
            daemon=True,
        )

        self._accept_thread.start()
        self._stats_thread.start()

        if self._show_window:
            self._window_thread = threading.Thread(
                target=self._debug_window_loop,
                name="tcp-window",
                daemon=True,
            )
            self._window_thread.start()

    def stop(self) -> None:
        """Stop all threads and close all sockets."""
        if not self._running:
            return

        print("[CameraStream] Stopping…", flush=True)
        self._running = False
        stop_event.set()

        if self._current_handler:
            self._current_handler.stop()
            self._current_handler = None

        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
            self._server_sock = None

        for t in (self._accept_thread, self._stats_thread, self._window_thread):
            if t and t.is_alive():
                t.join(timeout=3.0)

        if self._show_window:
            cv2.destroyAllWindows()

        stream_stats.mark_disconnected()
        stop_event.clear()
        print("[CameraStream] Stopped.", flush=True)

    def get_latest_frame(self) -> tuple[np.ndarray | None, float]:
        """
        Return (frame, monotonic_timestamp) of the most recent decoded frame.
        Returns (None, 0.0) if no frame has been received yet.
        """
        return frame_slot.get()

    def is_connected(self) -> bool:
        """True while a client is actively sending frames."""
        handler = self._current_handler
        return (
            handler is not None
            and not handler.finished
            and frame_slot.is_fresh(1.0)
        )

    # =========================================================================
    # Accept loop  (tcp-accept thread)
    # =========================================================================

    def _accept_loop(self) -> None:
        """Wait for one Android client, hand it to a _ClientHandler."""
        print("[CameraStream] Waiting for Android client…", flush=True)

        while self._running and not stop_event.is_set():
            try:
                conn, addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            if self._current_handler and not self._current_handler.finished:
                self._current_handler.stop()

            # Disable Nagle algorithm & enlarge TCP receive window
            try:
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512 * 1024)
            except OSError:
                pass

            handler = _ClientHandler(conn, addr)
            self._current_handler = handler
            handler.start()

            while not handler.finished and not stop_event.is_set():
                time.sleep(0.1)

            print("[CameraStream] Waiting for Android client…", flush=True)

        print("[CameraStream] Accept loop exited.", flush=True)

    # =========================================================================
    # Stats printer  (tcp-stats thread)
    # =========================================================================

    def _stats_printer_loop(self) -> None:
        """Print a performance table to stdout every STATS_INTERVAL_S."""
        while self._running and not stop_event.is_set():
            time.sleep(STATS_INTERVAL_S)
            if not self._running or not self._print_stats:
                continue

            s      = stream_stats.snapshot()
            age_ms = frame_slot.get_age_ms()

            bps = s.get("bytes_per_second", 0)
            if bps >= 1_048_576:
                bps_str = f"{bps / 1_048_576:.2f} MB/s"
            elif bps >= 1024:
                bps_str = f"{bps / 1024:.2f} KB/s"
            else:
                bps_str = f"{bps:.0f} B/s"

            conn = "YES" if s["connected"] else "NO "

            print(
                f"\n{'═' * 64}\n"
                f"  Recv FPS  : {s.get('recv_fps', 0):5.1f}  │  "
                f"Decode FPS : {s.get('decode_fps', 0):5.1f}  │  "
                f"Decode Time : {s.get('decode_time_ms', 0):5.2f} ms\n"
                f"  JPEG Size : {s.get('jpeg_size_kb', 0):5.1f} KB │  "
                f"Bandwidth  : {bps_str:9} │  "
                f"Frame Age   : {age_ms:5.1f} ms\n"
                f"  Connected : {conn:5}  │  "
                f"Resolution : {s['resolution']:9} │  "
                f"Dropped     : {s['dropped_frames']:5d}\n"
                f"{'═' * 64}",
                flush=True,
            )

    # =========================================================================
    # Debug window  (tcp-window thread)
    # =========================================================================

    def _debug_window_loop(self) -> None:
        """Show a live cv2.imshow() window with a stats overlay."""
        last_frame_ts = 0.0

        while self._running and not stop_event.is_set():
            frame, ts = frame_slot.get()

            if frame is None or ts == last_frame_ts:
                time.sleep(0.01)
                continue

            last_frame_ts = ts
            self._draw_and_show(frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                print("[CameraStream] Q pressed — stopping.", flush=True)
                self._running = False
                stop_event.set()
                break

        cv2.destroyAllWindows()
        print("[CameraStream] Debug window closed.", flush=True)

    def _draw_and_show(self, frame: np.ndarray) -> None:
        """Draw stats overlay on a copy of frame."""
        display = frame.copy()

        s          = stream_stats.snapshot()
        resolution = s["resolution"]
        frame_no   = s["frame_number"]
        connected  = s["connected"]
        age_ms     = frame_slot.get_age_ms()
        timestamp  = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

        color = _COLOR_OK if connected else _COLOR_ERR

        lines = [
            f"Recv FPS    : {s.get('recv_fps', 0):.1f}",
            f"Decode FPS  : {s.get('decode_fps', 0):.1f}",
            f"Decode Time : {s.get('decode_time_ms', 0):.2f} ms",
            f"JPEG Size   : {s.get('jpeg_size_kb', 0):.1f} KB",
            f"Resolution  : {resolution}",
            f"Frame Age   : {age_ms:.1f} ms",
            f"Connected   : {'YES' if connected else 'NO'}",
            f"Frame #     : {frame_no}",
            f"Time        : {timestamp}",
        ]

        line_h  = 20
        panel_h = len(lines) * line_h + 12
        panel_w = 265
        overlay = display.copy()
        cv2.rectangle(overlay, (6, 6), (6 + panel_w, 6 + panel_h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.55, display, 0.45, 0, display)

        for i, text in enumerate(lines):
            y = 22 + i * line_h
            # Shadow
            cv2.putText(
                display, text, (9, y + 1),
                _FONT, _FONT_SCALE, (0, 0, 0),
                _THICKNESS + 1, cv2.LINE_AA,
            )
            # Text
            cv2.putText(
                display, text, (8, y),
                _FONT, _FONT_SCALE, color,
                _THICKNESS, cv2.LINE_AA,
            )

        cv2.imshow(WINDOW_NAME, display)


if __name__ == "__main__":
    stream = CameraStream(tcp_port=DEFAULT_TCP_PORT, show_window=True)
    stream.start()
    try:
        while stream._running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop()
