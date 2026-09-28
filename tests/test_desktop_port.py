"""Durable interval scheduling, task operations and desktop API evidence."""
import socket
import unittest
from taskweave.desktop.launcher import select_local_port

class DesktopPortTests(unittest.TestCase):
    def test_selected_port_can_bind_exact_server_address(self):
        port = select_local_port()
        self.assertGreater(port, 0)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", port))
