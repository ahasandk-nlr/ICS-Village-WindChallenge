import matplotlib.pyplot as plt
import struct
import time
import socket
import os

time_data = []
power_data = []

lower_bound = 1.2
upper_bound = 1.8

power_target = 500

def start_server(start_time):
    fig, ax = plt.subplots()
    ax.set_xlabel('Time')
    ax.set_ylabel('Power (Watts)')
    ax.set_xlim(0, 10)  # Adjust the time window as needed
    plt.axhline(y=lower_bound * 1000, color='red', linestyle='--', label='Lower Bound')
    plt.axhline(y=upper_bound * 1000, color='red', linestyle='--', label='Upper Bound')

    line, = ax.plot([], [], label='Power Data')
    # Bind on all interfaces so this is reachable regardless of the host's
    # IP (DHCP lease, wifi vs. ethernet, different venue network, etc.).
    # The rtu container reaches this via HMI_HOST (see rtu/rtu-speaker.py
    # and docker-compose.yml), not via a hardcoded address here.
    server_ip = os.environ.get('HMI_BIND_HOST', '0.0.0.0')
    server_port = int(os.environ.get('HMI_PORT', '8888'))
    speaker_port = int(os.environ.get('HMI_SPEAKER_PORT', '8889'))

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((server_ip, server_port))
    server_socket.listen(1)
    speaker_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    speaker_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    speaker_socket.bind((server_ip, speaker_port))
    speaker_socket.listen(1)
    print(f"Servers are listening on {server_ip}:{server_port} (data) and {server_ip}:{speaker_port} (speaker)...")

    while True:
        client_socket, address = server_socket.accept()
        print(f"Connection from {address} has been established.")

        client_speaker_socket, speaker_address = speaker_socket.accept()
        print(f"Connection from {speaker_address} has been established.")

        while True:
            received_bytes = client_socket.recv(1024)
            if not received_bytes:
                break
            received_data = struct.unpack('!f', received_bytes)[0]
            if received_data > upper_bound or received_data < lower_bound:
                print('fault')
                data = b'fault'
            else:
                data = b'no fault'
            client_speaker_socket.sendall(data)
            
            power_data.append(received_data * 1000)
            current_time = time.time()
            time_data.append(current_time - start_time)
            received_data = struct.unpack('!f', received_bytes)[0]
            power_data.append(received_data * 1000)
            current_time = time.time() - start_time
            time_data.append(current_time)

            x_vals = time_data
            y_vals = power_data

            line.set_data(x_vals, y_vals)
            ax.relim()
            ax.autoscale_view()
            ax.set_xlim(0, current_time)
            ax.relim()
            plt.pause(0.1)
            fig.canvas.flush_events()
        client_socket.close()

if __name__ == '__main__':
    start_server(time.time())
