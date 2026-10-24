import socket
import unittest

from tests import NetworkBlocked


class NetworkIsBlocked(unittest.TestCase):
    """A test that opens a socket fails."""

    def test_connect_is_refused(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with self.assertRaises(NetworkBlocked):
                s.connect(("127.0.0.1", 9))
        finally:
            s.close()

    def test_create_connection_is_refused(self):
        with self.assertRaises(NetworkBlocked):
            socket.create_connection(("example.org", 80), timeout=1)

    def test_name_resolution_is_refused(self):
        with self.assertRaises(NetworkBlocked):
            socket.getaddrinfo("example.org", 80)
