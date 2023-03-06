import socket
# from cogs.dataManager import mData
import traceback
from datetime import datetime

class Logger():
    def __init__():
        return
    def time():
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    def append_line_to_file(self,file,text,level):
        timenow = Logger.time()
        with open(file, 'a+') as f:
            f.seek(0)
            data = f.read(100)
            if len(data) > 0:
                f.write("\n")
            f.write(f"[{timenow}] [{level}] {text}")
class Listener():
    def __init__():
        return
    def start_listener():
        returnDict = mData().returnDict()
        # listener
        server_address = '0.0.0.0'
        if returnDict['use_proxy'] == 'False':
            server_port = int(returnDict['game_starting_port']) - 1
        else:
            server_port = int(returnDict['game_starting_port']) + 10000 - 1
        bufferSize  = 1460

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        """
            data from server
        """
        try:
            serverName = str.encode(returnDict['svr_hoster'],'utf8')
            version = str.encode(mData().check_hon_version(f"{returnDict['hon_directory']}hon_x64.exe"),'utf8')
        except Exception:
            print(traceback.format_exc())
            Logger().append_line_to_file(f"{returnDict['app_log']}",f"{traceback.format_exc()}","WARNING")
            Logger().append_line_to_file(f"{returnDict['app_log']}",f"Servers may be ineligible for auto-server selection until the above error is resolved.","WARNING")

        """
            response crafting
        """
        response = bytearray(46)
        response[42] = 0x01 # unreliable flag
        response[43] = 0x66 # pong message type
        response.extend(serverName)
        """
        Experimenting with simpler code
        """
        for i in range(4): # 4 zeroes between name and version
            response.append(0)
        response.extend(version)
        for i in range(19): # 19 zeroes after version
            response.append(0)
        """
        working code below, experiementing with simpler version above
        """
        # resp_len=len(response)
        # #    server name needs to be placed at offset 50 + length of server name
        # #    if the bytearray is too short, I'm adding extra bytes until it's 50

        # if resp_len < 50:
        #     t = 50 % resp_len
        #     for i in range(t):
        #         response.append(0)
        #     for i in range(len(serverName)):
        #         response.append(0)
        # # if the bytearray is larger than 50, due to longer server name, then i'm taking a little off the top (the additional values after 50, then adding server length)
        # elif resp_len >= 50:
        #     t = resp_len % 50
        #     for i in range(len(serverName) - t):
        #         response.append(0)

        # # add the length of version
        # response.extend(version)

        # # add additional bytes to bring it to the total expected size
        # remainder = (69-(len(response))) + (len(serverName)+len(version))
        # for i in range(remainder):
        #     response.append(0)
        """"""

        # prepare message for sending
        bytesToSend         = response

        # Create a datagram socket
        UDPServerSocket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)

        # Bind to address and ip
        UDPServerSocket.bind((server_address, server_port))
        print("UDP server up and listening")

        # Listen for incoming datagrams
        while(True):
            try:
                bytesAddressPair = UDPServerSocket.recvfrom(bufferSize)
                message = bytesAddressPair[0]
                address = bytesAddressPair[1]
                clientMsg = "Message from Client:{}".format(message)
                clientIP  = "Client IP Address:{}".format(address)
                
                # print(clientMsg)
                # print(clientIP)

                if len(message) !=46:
                    print("Unknown message - wrong length")
                    continue
                elif message[43] != 0xCA:
                    print("Unknown message - 43")
                    continue
                # Sending a reply to client
                else:
                    # write challenge. Setting values in the response to something expected by the server.
                    response[44] = message[44]
                    response[45] = message[45]
                    UDPServerSocket.sendto(bytesToSend, address)
            except Exception:
                print(traceback.format_exc())
                Logger().append_line_to_file(f"{returnDict['app_log']}",f"{traceback.format_exc()}","WARNING")