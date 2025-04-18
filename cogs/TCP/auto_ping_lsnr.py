import socket
import threading
import time
import traceback
from datetime import datetime
from cogs.misc.logger import get_logger
from cogs.handlers.events import stop_event

LOGGER = get_logger()

class AutoPingListener:
    """
    A robust UDP listener for AutoPing messages that runs in its own thread.
    Used to respond to upstream Master Server ping requests, for allocating the closest server to players.
    """

    def __init__(self, config, port):
        self.config = config
        self.port = port
        self.server_address = '0.0.0.0'
        self.running = False
        self.socket = None
        self.thread = None
        self.last_activity = datetime.now()
        self.packet_count = 0
        self.is_healthy = True

    def start_listener(self):
        """
        Starts the UDP listener in a separate thread.
        """
        if self.running:
            LOGGER.info(f"AutoPing listener already running on port {self.port}")
            return

        try:
            # Create and configure the socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Set a reasonable timeout so the thread can check stop_event
            self.socket.settimeout(1.0)
            
            # Bind to the specified address and port
            self.socket.bind((self.server_address, self.port))
            
            # Mark as running and start the listener thread
            self.running = True
            self.thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.thread.start()
            
            LOGGER.highlight(f"[*] AutoPing Responder - Listening on {self.server_address}:{self.port} (PUBLIC)")
            
            # Start the health monitor thread
            self.health_thread = threading.Thread(target=self._health_monitor, daemon=True)
            self.health_thread.start()
            
            return True
        except Exception as e:
            LOGGER.error(f"Failed to start AutoPing listener: {e}")
            LOGGER.error(traceback.format_exc())
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
            return False

    def stop_listener(self):
        """
        Stops the UDP listener.
        """
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(2.0)  # Wait up to 2 seconds for thread to exit
        
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        
        LOGGER.info("AutoPing Responder stopped")

    def _listen_loop(self):
        """
        Main listener loop that runs in a separate thread.
        """
        while self.running and not stop_event.is_set():
            try:
                try:
                    # Wait for a datagram
                    data, addr = self.socket.recvfrom(1024)
                    self._handle_datagram(data, addr)
                except socket.timeout:
                    # This is expected due to the socket timeout
                    continue
                except OSError as e:
                    if self.running:  # Only log if we're supposed to be running
                        LOGGER.error(f"Socket error in AutoPing listener: {e}")
                        # If socket was closed unexpectedly, try to recreate it
                        if "Socket operation on non-socket" in str(e):
                            try:
                                self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                                self.socket.settimeout(1.0)
                                self.socket.bind((self.server_address, self.port))
                                LOGGER.info("Recreated AutoPing listener socket after error")
                            except Exception as re_e:
                                LOGGER.error(f"Failed to recreate socket: {re_e}")
                                self.running = False
                    break
            except Exception as e:
                if self.running:  # Only log if we're supposed to be running
                    LOGGER.error(f"Error in AutoPing listener thread: {e}")
                    LOGGER.error(traceback.format_exc())
                time.sleep(0.1)  # Prevent tight loop if there's a recurring error

    def _handle_datagram(self, data, addr):
        """
        Processes a received datagram and sends a response if needed.
        """
        try:
            # Update activity metrics
            self.last_activity = datetime.now()
            self.packet_count += 1
            
            # Log packet in debug mode (commented out to avoid log spam)
            # packet_hex = ' '.join([f'{b:02X}' for b in data])
            # LOGGER.debug(f"RECEIVED PACKET #{self.packet_count} FROM {addr}")
            
            # Validate packet format
            if len(data) != 46:
                LOGGER.warn(f"Unknown message - wrong length: {len(data)}")
                return
                
            if data[43] != 0xCA:
                LOGGER.warn(f"Unknown message byte at position 43: 0x{data[43]:02X}")
                return

            # Prepare the response
            server_name = self.config["hon_data"]["svr_name"]
            game_version = self.config["hon_data"]["svr_version"]
            message_size = 69 + len(server_name) + len(game_version)
            response = bytearray(message_size)
            
            # Set critical header bytes
            response[42] = 0x01
            response[43] = 0x66
            
            # Copy server details into response
            response[46: 46 + len(server_name)] = server_name.encode()
            response[50 + len(server_name): 50 + len(server_name) + len(game_version)] = game_version.encode()

            # Copy request identifiers
            response[44] = data[44]
            response[45] = data[45]

            # Send the response
            self.socket.sendto(response, addr)
            
        except Exception as e:
            LOGGER.error(f"Error handling datagram: {e}")
            LOGGER.error(traceback.format_exc())

    def _health_monitor(self):
        """
        Monitors listener health and logs status periodically.
        """
        status_interval = 60  # Log status every 60 seconds
        last_count = 0
        
        while self.running and not stop_event.is_set():
            try:
                time.sleep(10)  # Check health every 10 seconds
                
                # Check if we've been idle too long (5 minutes)
                idle_seconds = (datetime.now() - self.last_activity).total_seconds()
                if idle_seconds > 300:  # 5 minutes
                    # Test the listener ourselves
                    if self._self_test():
                        LOGGER.debug(f"AutoPing listener self-test passed after {idle_seconds:.0f}s idle")
                        self.is_healthy = True
                    else:
                        LOGGER.warn(f"AutoPing listener self-test failed after {idle_seconds:.0f}s idle")
                        self.is_healthy = False
                
                # Log status periodically
                status_interval -= 10
                if status_interval <= 0:
                    new_packets = self.packet_count - last_count
                    LOGGER.debug(f"AutoPing status: {new_packets} packets in last minute, total: {self.packet_count}")
                    last_count = self.packet_count
                    status_interval = 60
            except Exception as e:
                LOGGER.error(f"Error in health monitor: {e}")
    
    def _self_test(self):
        """
        Performs a self-test by sending a packet to the listener.
        """
        if not self.running or not self.socket:
            return False
            
        try:
            # Create a separate socket for the test
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            test_sock.settimeout(2.0)
            
            # Prepare a test packet
            test_packet = bytearray(46)
            test_packet[43] = 0xCA
            test_packet[44] = 0xFF  # Special test identifier
            test_packet[45] = 0xFE  # Special test identifier
            
            # Send to our listener
            try:
                # Try localhost first
                test_sock.sendto(test_packet, ('127.0.0.1', self.port))
                data, _ = test_sock.recvfrom(1024)
                # If we get a response, check it's correctly formatted
                if len(data) > 43 and data[43] == 0x66:
                    return True
            except:
                # If localhost fails, try external interface
                try:
                    test_sock.sendto(test_packet, (self.server_address, self.port))
                    data, _ = test_sock.recvfrom(1024)
                    if len(data) > 43 and data[43] == 0x66:
                        return True
                except:
                    pass
            
            return False
        except Exception as e:
            LOGGER.error(f"Error in self-test: {e}")
            return False
        finally:
            try:
                test_sock.close()
            except:
                pass
    
    def check_health(self):
        """
        Public method to check if the listener is healthy.
        Returns True if the listener appears to be working correctly.
        """
        if not self.running:
            return False
            
        # If we've been inactive, do a real self-test
        idle_seconds = (datetime.now() - self.last_activity).total_seconds()
        if idle_seconds > 60:  # If no activity for 1 minute
            return self._self_test()
            
        # Otherwise return cached health status
        return self.is_healthy