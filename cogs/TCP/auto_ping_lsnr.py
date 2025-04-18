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
    A UDP listener for AutoPing messages that runs in its own thread.
    """
    def __init__(self, config, port):
        self.config = config
        self.port = port
        self.server_address = '0.0.0.0'
        self.socket = None
        self.thread = None
        self.health_thread = None
        self.last_activity = datetime.now()
        self.packet_count = 0
        
        # Simple status tracker - don't use this for critical decisions
        self._should_run = False

    def start_listener(self):
        """
        Starts the UDP listener in a separate thread.
        """
        # If already running, don't start again
        if self.thread and self.thread.is_alive() and self._should_run:
            LOGGER.info(f"AutoPing listener already has an active thread")
            return True

        LOGGER.info(f"Starting AutoPing listener on port {self.port}")
        
        try:
            # Create socket fresh every time
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
            
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.settimeout(1.0)
            
            # Bind to the specified address and port
            self.socket.bind((self.server_address, self.port))
            
            # Signal threads to run
            self._should_run = True
            
            # Start main listener thread
            self.thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.thread.start()
            
            LOGGER.highlight(f"[*] AutoPing Responder - Listening on {self.server_address}:{self.port} (PUBLIC)")
            
            # Let OS and threads stabilize
            time.sleep(0.2)
            
            # Verify the listener is actually working with a quick self-test
            if self._self_test():
                LOGGER.info("AutoPing listener validated with self-test")
                return True
            else:
                LOGGER.error("AutoPing listener failed initial self-test")
                self.stop_listener()
                return False
                
        except Exception as e:
            LOGGER.error(f"Failed to start AutoPing listener: {e}")
            LOGGER.error(traceback.format_exc())
            self._should_run = False
            
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
        LOGGER.info("Stopping AutoPing Responder")
        
        # Signal threads to stop
        self._should_run = False
        
        # Close socket to unblock recvfrom
        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                LOGGER.error(f"Error closing socket: {e}")
        
        # Wait for threads to exit
        if self.thread and self.thread.is_alive():
            try:
                self.thread.join(1.0)
            except:
                pass
        
        self.socket = None
        LOGGER.info("AutoPing Responder stopped")

    def _listen_loop(self):
        """
        Main listener loop that runs in a separate thread.
        """
        LOGGER.info("AutoPing listener thread started")
        
        # Local reference to avoid race conditions
        local_socket = self.socket
        
        while self._should_run and not stop_event.is_set() and local_socket:
            try:
                try:
                    # Wait for a datagram
                    data, addr = local_socket.recvfrom(1024)
                    self._handle_datagram(data, addr, local_socket)
                except socket.timeout:
                    # Expected due to timeout
                    continue
                except OSError:
                    # Socket likely closed
                    break
                except Exception as e:
                    LOGGER.error(f"Error in listener loop: {e}")
                    time.sleep(0.1)
            except:
                break
        
        LOGGER.info("AutoPing listener thread exiting")

    def _handle_datagram(self, data, addr, local_socket):
        """
        Processes a received datagram and sends a response if needed.
        """
        try:
            # Update activity tracking
            self.last_activity = datetime.now()
            self.packet_count += 1
            
            # Validate packet format
            if len(data) != 46:
                return
                
            if data[43] != 0xCA:
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
            try:
                local_socket.sendto(response, addr)
            except:
                # Socket might be closed - nothing we can do
                pass
            
        except Exception as e:
            LOGGER.error(f"Error handling datagram: {e}")
    
    def _self_test(self):
        """
        Performs a self-test by sending a packet to the listener.
        """
        test_sock = None
        try:
            # Create a separate socket for the test
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            test_sock.settimeout(1.0)
            
            # Prepare a test packet
            test_packet = bytearray(46)
            test_packet[43] = 0xCA
            test_packet[44] = 0xFF
            test_packet[45] = 0xFE
            
            # Try both localhost and external interface
            for address in ['127.0.0.1', self.server_address]:
                try:
                    test_sock.sendto(test_packet, (address, self.port))
                    data, _ = test_sock.recvfrom(1024)
                    if len(data) > 43 and data[43] == 0x66:
                        return True
                except:
                    continue
            
            return False
        except Exception as e:
            LOGGER.error(f"Error in self-test: {e}")
            return False
        finally:
            if test_sock:
                try:
                    test_sock.close()
                except:
                    pass
    
    def check_health(self):
        """
        Check if the listener is working by directly testing its functionality.
        """
        # Skip internal state checks and go straight to functional test
        return self._self_test()