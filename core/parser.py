"""Lazy persistent JDK AST worker; no build-system execution and no classpath requirements."""
import hashlib
import os
import struct
import subprocess
import threading
from .java_source import fallback_candidates


class JavaParser:
    def __init__(self, cache_dir, source_path, javac='javac', java='java', mode='javac'):
        self.cache_dir = cache_dir
        self.source_path = source_path
        self.javac = javac
        self.java = java
        self.mode = mode
        self.process = None
        self.lock = threading.Lock()
        self.error = None

    def _start(self):
        if self.process and self.process.poll() is None: return True
        self.process = None
        try:
            with open(self.source_path, 'rb') as stream: data = stream.read()
            stamp = hashlib.sha256(data).hexdigest()
            os.makedirs(self.cache_dir, exist_ok=True)
            classfile = os.path.join(self.cache_dir, 'SmimpParser.class')
            stampfile = os.path.join(self.cache_dir, '.source_hash')
            try:
                with open(stampfile, encoding='ascii') as stream: current = stream.read()
            except OSError: current = ''
            if current != stamp or not os.path.isfile(classfile):
                completed = subprocess.run([self.javac, '-encoding', 'UTF-8', '-d', self.cache_dir, self.source_path],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
                if completed.returncode:
                    raise RuntimeError(completed.stderr.decode('utf-8', 'replace')[:1200])
                with open(stampfile, 'w', encoding='ascii') as stream: stream.write(stamp)
            self.process = subprocess.Popen([self.java, '-cp', self.cache_dir, 'SmimpParser'],
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            self.error = None
            return True
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            self.error = str(exc)
            return False

    @staticmethod
    def _read_exact(stream, length):
        buf = bytearray()
        while len(buf) < length:
            part = stream.read(length - len(buf))
            if not part: raise EOFError('JDK parser process exited')
            buf.extend(part)
        return bytes(buf)

    def analyze(self, source):
        """Return (referenced_type_names, reliable_for_unused_import_cleanup).

        The JDK AST parser marks successful parses explicitly. Lexical fallback is
        useful for adding imports, but is intentionally *not* trusted to remove
        imports because it may miss uncommon Java type positions.
        """
        if self.mode != 'javac':
            return fallback_candidates(source), False
        with self.lock:
            if not self._start():
                return fallback_candidates(source), False
            try:
                data = source.encode('utf-8')
                self.process.stdin.write(struct.pack('>I', len(data)) + data)
                self.process.stdin.flush()
                size = struct.unpack('>I', self._read_exact(self.process.stdout, 4))[0]
                if size > 2_000_000: raise ValueError('Invalid parser response')
                lines = self._read_exact(self.process.stdout, size).decode('utf-8').splitlines()
                if lines and lines[0] == '@SMIMP_OK':
                    return set(lines[1:]), True
                if lines and lines[0] == '@SMIMP_FAIL':
                    return fallback_candidates(source), False
                # Backward compatibility with an already-running pre-0.5 helper.
                return set(lines), False
            except (OSError, ValueError, EOFError):
                self.process = None
                return fallback_candidates(source), False

    def symbols(self, source):
        return self.analyze(source)[0]

    def close(self):
        with self.lock:
            if self.process:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    try: self.process.kill()
                    except OSError: pass
                for stream in (self.process.stdin, self.process.stdout):
                    if stream:
                        try: stream.close()
                        except OSError: pass
                self.process = None
