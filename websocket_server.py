import sys
import struct
from base64 import b64encode
from hashlib import sha1
from socket import error as SocketError
import socket
import errno
import logging

if sys.version_info[0] < 3:
	from SocketServer import ThreadingMixIn, TCPServer, StreamRequestHandler, BaseServer
else:
	from socketserver import ThreadingMixIn, TCPServer, StreamRequestHandler, BaseServer

'''
+-+-+-+-+-------+-+-------------+-------------------------------+
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-------+-+-------------+-------------------------------+
|F|R|R|R| opcode|M| Payload len |    Extended payload length    |
|I|S|S|S|  (4)  |A|     (7)     |             (16/64)           |
|N|V|V|V|       |S|             |   (if payload len==126/127)   |
| |1|2|3|       |K|             |                               |
+-+-+-+-+-------+-+-------------+ - - - - - - - - - - - - - - -
|     Extended payload length continued, if payload len == 127  |
+ - - - - - - - - - - - - - - - +-------------------------------+
|                     Payload Data continued ...                |
+---------------------------------------------------------------+
'''

FIN    = 0x80
OPCODE = 0x0f
MASKED = 0x80
PAYLOAD_LEN = 0x7f
PAYLOAD_LEN_EXT16 = 0x7e
PAYLOAD_LEN_EXT64 = 0x7f

OPCODE_CONTINUATION = 0x0
OPCODE_TEXT         = 0x1
OPCODE_BINARY       = 0x2
OPCODE_CLOSE_CONN   = 0x8
OPCODE_PING         = 0x9
OPCODE_PONG         = 0xA


class API():
	def run_forever(self):
		try:
			self.serve_forever()
		except KeyboardInterrupt:
			self.server_close()
		except Exception as e:
			exit(1)

	def new_client(self, client, server):
		pass

	def client_left(self, client, server):
		pass

	def message_received(self, client, server, message):
		pass

	def set_fn_new_client(self, fn):
		self.new_client = fn

	def set_fn_client_left(self, fn):
		self.client_left = fn

	def set_fn_message_received(self, fn):
		self.message_received = fn

	def send_message(self, client, msg):
		self._unicast_(client, msg)

	def send_message_to_all(self, msg):
		self._multicast_(msg)


# ------------------------- Implementation -----------------------------

class TCPSSLServer(BaseServer):
	address_family = socket.AF_INET

	socket_type = socket.SOCK_STREAM

	request_queue_size = 5

	allow_reuse_address = False

	def __init__(self, server_address, RequestHandlerClass, bind_and_activate=True):
		BaseServer.__init__(self, server_address, RequestHandlerClass)
		self.socket = socket.socket(self.address_family, self.socket_type)
		
		if bind_and_activate:
			try:
				self.server_bind()
				self.server_activate()
			except:
				self.server_close()
				raise

	def server_bind(self):
		"""Called by constructor to bind the socket.
		May be overridden.
		"""
		self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		self.socket.bind(self.server_address)
		self.server_address = self.socket.getsockname()

	def server_activate(self):
		"""Called by constructor to activate the server.
		May be overridden.
		"""
		self.socket.listen(self.request_queue_size)

	def server_close(self):
		"""Called to clean-up the server.
		May be overridden.
		"""
		self.socket.close()

	def fileno(self):
		"""Return socket file number.
		Interface required by select().
		"""
		return self.socket.fileno()

	def get_request(self):
		"""Get the request and client address from the socket.
		May be overridden.
		"""
		client, address = self.socket.accept()
		return (client, address)

	def shutdown_request(self, request):
		"""Called to shutdown and close an individual request."""
		try:
			#explicitly shutdown.  socket.close() merely releases
			#the socket and waits for GC to perform the actual close.
			request.shutdown(socket.SHUT_WR)
		except socket.error:
			pass #some platforms may raise ENOTCONN here
		self.close_request(request)

	def close_request(self, request):
		"""Called to clean up an individual request."""
		request.close()


class WebsocketServer(ThreadingMixIn, TCPSSLServer, API):
	"""
	A websocket server waiting for clients to connect.
	Args:
		port(int): Port to bind to
		host(str): Hostname or IP to listen for connections. By default 127.0.0.1
			is being used. To accept connections from any client, you should use
			0.0.0.0.
		loglevel: Logging level from logging module to use for logging. By default
			warnings and errors are being logged.
	Properties:
		clients(list): A list of connected clients. A client is a dictionary
			like below.
				{
				 'id'	  : id,
				 'handler' : handler,
				 'address' : (addr, port)
				}
	"""

	allow_reuse_address = True
	daemon_threads = True  # comment to keep threads alive until finished

	clients = []
	id_counter = 0

	def __init__(self, port, host='127.0.0.1', loglevel=logging.WARNING):
		TCPSSLServer.__init__(self, (host, port), WebSocketHandler)
		self.port = self.socket.getsockname()[1]

	def _message_received_(self, handler, msg):
		self.message_received(self.handler_to_client(handler), self, msg)

	def _ping_received_(self, handler, msg):
		handler.send_pong(msg)

	def _pong_received_(self, handler, msg):
		pass

	def _new_client_(self, handler):
		self.id_counter += 1
		client = {
			'id': self.id_counter,
			'handler': handler,
			'address': handler.client_address
		}
		self.clients.append(client)
		self.new_client(client, self)

	def _client_left_(self, handler):
		client = self.handler_to_client(handler)
		self.client_left(client, self)
		if client in self.clients:
			self.clients.remove(client)

	def _unicast_(self, to_client, msg):
		to_client['handler'].send_message(msg)

	def _multicast_(self, msg):
		for client in self.clients:
			self._unicast_(client, msg)

	def handler_to_client(self, handler):
		for client in self.clients:
			if client['handler'] == handler:
				return client


class WebSocketHandler(StreamRequestHandler):

	def __init__(self, socket, addr, server):
		self.server = server
		StreamRequestHandler.__init__(self, socket, addr, server)

	def setup(self):
		StreamRequestHandler.setup(self)
		self.keep_alive = True
		self.handshake_done = False
		self.valid_client = False

	def handle(self):
		while self.keep_alive:
			if not self.handshake_done:
				self.handshake()
			elif self.valid_client:
				self.read_next_message()

	def read_bytes(self, num):
		# python3 gives ordinal of byte directly
		bytes = self.rfile.read(num)
		if sys.version_info[0] < 3:
			return map(ord, bytes)
		else:
			return bytes

	def read_next_message(self):
		try:
			b1, b2 = self.read_bytes(2)
		except SocketError as e:  # to be replaced with ConnectionResetError for py3
			if e.errno == errno.ECONNRESET:
				logger.info("Client closed connection.")
				print("Error: {}".format(e))
				self.keep_alive = 0
				return
			b1, b2 = 0, 0
		except ValueError as e:
			b1, b2 = 0, 0

		fin	= b1 & FIN
		opcode = b1 & OPCODE
		masked = b2 & MASKED
		payload_length = b2 & PAYLOAD_LEN

		if opcode == OPCODE_CLOSE_CONN:
			print("Client asked to close connection.")
			self.keep_alive = 0
			return
		if not masked:
			print("Client must always be masked.")
			self.keep_alive = 0
			return
		if opcode == OPCODE_CONTINUATION:
			print("Continuation frames are not supported.")
			return
		elif opcode == OPCODE_BINARY:
			print("Binary frames are not supported.")
			return
		elif opcode == OPCODE_TEXT:
			opcode_handler = self.server._message_received_
		elif opcode == OPCODE_PING:
			opcode_handler = self.server._ping_received_
		elif opcode == OPCODE_PONG:
			opcode_handler = self.server._pong_received_
		else:
			logger.warn("Unknown opcode %#x." % opcode)
			self.keep_alive = 0
			return

		if payload_length == 126:
			payload_length = struct.unpack(">H", self.rfile.read(2))[0]
		elif payload_length == 127:
			payload_length = struct.unpack(">Q", self.rfile.read(8))[0]

		masks = self.read_bytes(4)
		message_bytes = bytearray()
		for message_byte in self.read_bytes(payload_length):
			message_byte ^= masks[len(message_bytes) % 4]
			message_bytes.append(message_byte)
		opcode_handler(self, message_bytes.decode('utf8'))

	def send_message(self, message):
		self.send_text(message)

	def send_pong(self, message):
		self.send_text(message, OPCODE_PONG)

	def send_text(self, message, opcode=OPCODE_TEXT):
		"""
		Important: Fragmented(=continuation) messages are not supported since
		their usage cases are limited - when we don't know the payload length.
		"""

		# Validate message
		if isinstance(message, bytes):
			message = try_decode_UTF8(message)  # this is slower but ensures we have UTF-8
			if not message:
				logger.warning("Can\'t send message, message is not valid UTF-8")
				return False
		elif sys.version_info < (3,0) and (isinstance(message, str) or isinstance(message, unicode)):
			pass
		elif isinstance(message, str):
			pass
		else:
			logger.warning('Can\'t send message, message has to be a string or bytes. Given type is %s' % type(message))
			return False

		header  = bytearray()
		payload = encode_to_UTF8(message)
		payload_length = len(payload)

		# Normal payload
		if payload_length <= 125:
			header.append(FIN | opcode)
			header.append(payload_length)

		# Extended payload
		elif payload_length >= 126 and payload_length <= 65535:
			header.append(FIN | opcode)
			header.append(PAYLOAD_LEN_EXT16)
			header.extend(struct.pack(">H", payload_length))

		# Huge extended payload
		elif payload_length < 18446744073709551616:
			header.append(FIN | opcode)
			header.append(PAYLOAD_LEN_EXT64)
			header.extend(struct.pack(">Q", payload_length))

		else:
			raise Exception("Message is too big. Consider breaking it into chunks.")
			return

		self.request.send(header + payload)

	def read_http_headers(self):
		headers = {}
		# first line should be HTTP GET
		http_get = self.rfile.readline().decode().strip()
		assert http_get.upper().startswith('GET')
		# remaining should be headers
		while True:
			header = self.rfile.readline().decode().strip()
			if not header:
				break
			head, value = header.split(':', 1)
			headers[head.lower().strip()] = value.strip()
		return headers

	def handshake(self):
		headers = self.read_http_headers()

		try:
			assert headers['upgrade'].lower() == 'websocket'
		except AssertionError:
			self.keep_alive = False
			return

		try:
			key = headers['sec-websocket-key']
		except KeyError:
			logger.warning("Client tried to connect but was missing a key")
			self.keep_alive = False
			return

		response = self.make_handshake_response(key)
		self.handshake_done = self.request.send(response.encode())
		self.valid_client = True
		self.server._new_client_(self)

	@classmethod
	def make_handshake_response(cls, key):
		return \
		  'HTTP/1.1 101 Switching Protocols\r\n'\
		  'Upgrade: websocket\r\n'			  \
		  'Connection: Upgrade\r\n'			 \
		  'Sec-WebSocket-Accept: %s\r\n'		\
		  '\r\n' % cls.calculate_response_key(key)

	@classmethod
	def calculate_response_key(cls, key):
		GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
		hash = sha1(key.encode() + GUID.encode())
		response_key = b64encode(hash.digest()).strip()
		return response_key.decode('ASCII')

	def finish(self):
		self.server._client_left_(self)


def encode_to_UTF8(data):
	try:
		return data.encode('UTF-8')
	except UnicodeEncodeError as e:
		logger.error("Could not encode data to UTF-8 -- %s" % e)
		return False
	except Exception as e:
		raise(e)
		return False


def try_decode_UTF8(data):
	try:
		return data.decode('utf-8')
	except UnicodeDecodeError:
		return False
	except Exception as e:
		raise(e)


