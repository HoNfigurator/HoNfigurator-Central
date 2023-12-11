import asyncio
import socket
import traceback
import struct
from packet_parser import ManagerChatParser, GameChatParser, ClientChatParser

async def get_headers(data, src, dst, src_name, dst_name):
    msg_len = int.from_bytes(data[0:2], byteorder='little')
    if len(data) == 2:  #   this means we have the len only.
        next_packet_data = await src.readexactly(msg_len)    # receive the message in full
        msg_type = int.from_bytes(next_packet_data[0:2], byteorder='little')
        dst.write(data)   # send the packet size
        dst.write(next_packet_data)   # send the message
        await dst.drain()
        return msg_len, msg_type, data, next_packet_data,False

    msg_type = int.from_bytes(data[2:4], byteorder='little')


    modified_packet = data[2:]

    return msg_len, msg_type, data, modified_packet,True

manager_chat_parser = ManagerChatParser()
game_chat_parser = GameChatParser()
client_chat_parser = ClientChatParser()


async def handle_gameserver_to_chatserver_packet(msg_len, msg_type, original_packet, new_packet):
    # Use the game_chat_parser to parse the packet
    await game_chat_parser.handle_packet(msg_type, msg_len, new_packet, "sending")

async def handle_client_to_chatserver_packet(msg_len, msg_type, original_packet, new_packet):
    # Use the game_chat_parser to parse the packet
    await client_chat_parser.handle_packet(msg_type, msg_len, new_packet, "sending")

async def handle_manager_to_chatserver_packet(msg_len, msg_type, original_packet, new_packet):
    # Use the manager_chat_parser to parse the packet
    await manager_chat_parser.handle_packet(msg_type, msg_len, new_packet, "sending")
    
async def handle_chatserver_to_gameserver_packet(msg_len, msg_type, original_packet, new_packet):
    # Use the game_chat_parser to parse the packet
    await game_chat_parser.handle_packet(msg_type, msg_len, new_packet, "receiving")

async def handle_chatserver_to_client_packet(msg_len, msg_type, original_packet, new_packet):
    # Use the game_chat_parser to parse the packet
    await client_chat_parser.handle_packet(msg_type, msg_len, new_packet, "receiving")

async def handle_chatserver_to_manager_packet(msg_len, msg_type, original_packet, new_packet):
    # Use the manager_chat_parser to parse the packet
    await manager_chat_parser.handle_packet(msg_type, msg_len, new_packet, "receiving")


    
async def transfer_data(src_reader, dst_writer, handle_packet_fn, src_name, dst_name):
    while True:
        data = await src_reader.read(4096)
        if len(data) == 0:
            break

        msg_len, msg_type, original_packet, new_packet, process_next = await get_headers(data, src_reader, dst_writer, src_name, dst_name)
        await handle_packet_fn(msg_len, msg_type, original_packet, new_packet)

        if process_next:
            dst_writer.write(data)
            await dst_writer.drain()

async def handle_game_connection(reader, writer):
    remote_writer = None
    try:
        remote_reader, remote_writer = await asyncio.open_connection(remote_host, game_traffic_port)

        send_task = asyncio.create_task(transfer_data(reader, remote_writer, handle_gameserver_to_chatserver_packet, "gameserver", "chatserver"))
        recv_task = asyncio.create_task(transfer_data(remote_reader, writer, handle_chatserver_to_gameserver_packet, "chatserver", "gameserver"))

        await asyncio.gather(send_task, recv_task)

    except ConnectionResetError:
        print(f"ConnectionResetError: {traceback.format_exc()}")
    except Exception:
        print(f"An error occurred: {traceback.format_exc()}")
    finally:
        if remote_writer:
            remote_writer.close()
            await remote_writer.wait_closed()
        writer.close()
        await writer.wait_closed()

async def handle_manager_connection(reader, writer):
    remote_writer = None
    try:
        remote_reader, remote_writer = await asyncio.open_connection(remote_host, manager_traffic_port)

        send_task = asyncio.create_task(transfer_data(reader, remote_writer, handle_manager_to_chatserver_packet, "manager", "chatserver"))
        recv_task = asyncio.create_task(transfer_data(remote_reader, writer, handle_chatserver_to_manager_packet, "chatserver", "manager"))

        await asyncio.gather(send_task, recv_task)

    except ConnectionResetError:
        print(f"ConnectionResetError: {traceback.format_exc()}")
    except Exception:
        print(f"An error occurred: {traceback.format_exc()}")
    finally:
        if remote_writer:
            remote_writer.close()
            await remote_writer.wait_closed()
        writer.close()
        await writer.wait_closed()

async def handle_client_connection(reader, writer):
    remote_writer = None
    try:
        remote_reader, remote_writer = await asyncio.open_connection(remote_host, client_traffic_port)

        send_task = asyncio.create_task(transfer_data(reader, remote_writer, handle_client_to_chatserver_packet, "client", "chatserver"))
        recv_task = asyncio.create_task(transfer_data(remote_reader, writer, handle_chatserver_to_client_packet, "chatserver", "client"))

        await asyncio.gather(send_task, recv_task)

    except ConnectionResetError:
        print(f"ConnectionResetError: {traceback.format_exc()}")
    except Exception:
        print(f"An error occurred: {traceback.format_exc()}")
    finally:
        if remote_writer:
            remote_writer.close()
            await remote_writer.wait_closed()
        writer.close()
        await writer.wait_closed()


async def main(game_traffic_port, manager_traffic_port, client_traffic_port):
    game_server = await asyncio.start_server(handle_game_connection, '0.0.0.0', game_traffic_port)
    manager_server = await asyncio.start_server(handle_manager_connection, '0.0.0.0', manager_traffic_port)
    client_server = await asyncio.start_server(handle_client_connection, '0.0.0.0', client_traffic_port)

    print(f"Game server started on port {game_traffic_port}")
    print(f"Manager server started on port {manager_traffic_port}")
    print(f"Client server started on port {client_traffic_port}")

    async with game_server, manager_server, client_server:
        await asyncio.gather(game_server.serve_forever(), manager_server.serve_forever(), client_server.serve_forever())

if __name__ == "__main__":
    game_traffic_port = 11032
    manager_traffic_port = 11033
    client_traffic_port = 11031
    remote_host = '104.251.123.39'
    try:
        asyncio.run(main(game_traffic_port, manager_traffic_port, client_traffic_port))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error running proxy: {e}")

