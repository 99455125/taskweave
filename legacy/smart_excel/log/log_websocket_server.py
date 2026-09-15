import asyncio
import logging
import queue
import websockets

log_queue = queue.Queue(maxsize=1000)

connected_clients = set()

class QueueLogHandler(logging.Handler):
    def emit(self, record):
        try:
            log_queue.put_nowait(self.format(record))
        except queue.Full:
            pass


async def send_to_clients(message):
    for client in list(connected_clients):
        try:
            await client.send(message)
        except websockets.exceptions.ConnectionClosed:
            connected_clients.remove(client)
        except Exception as e:
            # 避免在这里使用 logging，以防日志系统本身出错导致无限循环
            print(f"Error sending log to client: {e}")


async def log_forwarder():
    while True:
        try:
            message = log_queue.get_nowait()
            await send_to_clients(message)
        except queue.Empty:
            await asyncio.sleep(0.1)


async def connection_handler(websocket):
    connected_clients.add(websocket)
    logging.info(f"New client connected: {websocket.remote_address}")
    try:
        # 保持连接打开，直到客户端断开
        # wait_closed() 是一个更简单的方法来等待连接关闭
        await websocket.wait_closed()
    finally:
        # 确保客户端从集合中移除
        logging.info(f"Client disconnected: {websocket.remote_address}")
        connected_clients.remove(websocket)



async def start_websocket_server(socket_port=None):
    asyncio.create_task(log_forwarder())
    server_host = "localhost"
    async with websockets.serve(connection_handler, server_host, socket_port):
        logging.info(f"WebSocket log server started on ws://{server_host}:{socket_port}")
        await asyncio.Future()  # 保持服务器运行