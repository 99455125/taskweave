"""Minimal MySQL protocol fixture, not an actual TiDB server."""
import socket
import struct
import threading


def string(value):
    encoded = value.encode()
    return bytes([len(encoded)]) + encoded


class MySQLFixture:
    def __enter__(self):
        self.socket = socket.socket();self.socket.bind(('127.0.0.1', 0));self.socket.listen()
        self.port = self.socket.getsockname()[1];self.queries = [];self.errors = []
        self.thread = threading.Thread(target=self.serve, daemon=True);self.thread.start()
        return self

    def receive(self, conn):
        header = self.exact(conn, 4)
        length = int.from_bytes(header[:3], 'little')
        return self.exact(conn, length)

    def exact(self, conn, length):
        result = b''
        while len(result) < length:
            part = conn.recv(length-len(result))
            if not part: raise EOFError()
            result += part
        return result

    def send(self, conn, payload, sequence):
        conn.sendall(len(payload).to_bytes(3, 'little') + bytes([sequence]) + payload)

    def serve(self):
        try:
            conn, _ = self.socket.accept()
            with conn:
                conn.settimeout(15)
                # protocol 4.1, secure connection and native-password authentication
                capabilities = 1 | 4 | 8 | 512 | 8192 | 32768 | 524288
                handshake = b'\x0a8.0.11-TiDB-fixture\x00' + struct.pack('<I', 1) + b'abcdefgh\x00' + struct.pack('<H', capabilities & 65535) + b'\x21' + struct.pack('<H', 2) + struct.pack('<H', capabilities >> 16) + b'\x15' + b'\x00'*10 + b'ijklmnopqrst\x00mysql_native_password\x00'
                self.send(conn, handshake, 0);self.receive(conn)
                self.send(conn, b'\x00\x00\x00\x02\x00\x00\x00', 2)
                while True:
                    command = self.receive(conn)
                    if command[0] == 1: break
                    sql = command[1:].decode();self.queries.append(sql)
                    if sql.upper().startswith('SELECT'):
                        fields = ['order_no', 'status'];row = ['001', 'SUBMITTED']
                        if 'VERSION()' in sql:
                            fields = ['version', 'database_name'];row = ['8.0.11-TiDB-fixture', 'uat']
                        self.send(conn, bytes([len(fields)]), 1)
                        sequence = 2
                        for field in fields:
                            descriptor = b''.join(string(item) for item in ('def', 'uat', 'orders', 'orders', field, field)) + b'\x0c' + struct.pack('<HIBHB', 33, 256, 253, 0, 0) + b'\x00\x00'
                            self.send(conn, descriptor, sequence);sequence += 1
                        self.send(conn, b'\xfe\x00\x00\x02\x00', sequence);sequence += 1
                        self.send(conn, b''.join(string(value) for value in row), sequence);sequence += 1
                        self.send(conn, b'\xfe\x00\x00\x02\x00', sequence)
                    else:
                        self.send(conn, b'\x00\x00\x00\x02\x00\x00\x00', 1)
        except EOFError:
            pass
        except Exception as exc:
            self.errors.append(exc)

    def __exit__(self, *args):
        self.socket.close();self.thread.join(timeout=2)
