#!/usr/bin/python3
import socket

print("start server")

# create a socket object
serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# get local machine name
# host = socket.gethostname()
host = "localhost"
count = 0

port = 9999

# bind to the port
serversocket.bind((host, port))

# queue up to 5 requests
serversocket.listen(5)
print("waiting connection...")

while True:
    # establish a connection
    clientsocket, addr = serversocket.accept()
    print(f"Got a connection from {addr}")
    count += 1
    msg = "Thank you for connecting" + str(count) + "\r\n"
    clientsocket.send(msg.encode("ascii"))
    clientsocket.close()
