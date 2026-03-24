#!/usr/bin/env python3
import os
import re
import time
import random
import subprocess
import json
import socket

########################################
# 1) PARSE LINES AS TOTAL BYTES        #
########################################

def parse_total_bytes(line):
    """
    Interpret a line like "38K" as 38,000 total bytes for that hour,
    or "100M" as 100,000,000 bytes, etc.
    """
    line = line.strip().upper()
    match = re.match(r"([\d.]+)\s*([KMG]?)", line)
    if not match:
        raise ValueError(f"Invalid format: '{line}'")

    numeric_part = float(match.group(1))
    unit = match.group(2)  # "K", "M", "G", or ""

    if unit == "K":
        total_bytes = numeric_part * 1e3
    elif unit == "M":
        total_bytes = numeric_part * 1e6
    elif unit == "G":
        total_bytes = numeric_part * 1e9
    else:
        total_bytes = numeric_part  # no suffix => raw bytes

    return total_bytes

def load_hourly_totals(txt_file):
    """
    Read 25 lines from 'txt_file', each line is total bytes for that hour.
    Return a list of length 25: [total_bytes_hour0, ..., total_bytes_hour24].
    """
    totals = []
    with open(txt_file, "r") as f:
        for line in f:
            if line.strip():
                totals.append(parse_total_bytes(line))

    if len(totals) != 25:
        raise ValueError(f"Expected 25 lines in {txt_file}, got {len(totals)}.")
    return totals

########################################
# 2) CONVERT bits/s -> iPerf3 '-b' arg #
########################################

def bits_to_iperf_notation(bits_per_sec):
    """
    Convert bits/s -> e.g. "300K", "2.5M", or "1.20G" for iPerf3's '-b' argument.
    """
    if bits_per_sec < 1e3:
        return f"{bits_per_sec:.1f}"
    elif bits_per_sec < 1e6:
        return f"{bits_per_sec / 1e3:.1f}K"
    elif bits_per_sec < 1e9:
        return f"{bits_per_sec / 1e6:.1f}M"
    else:
        return f"{bits_per_sec / 1e9:.2f}G"

########################################
# 3) RUN IPERF3 FLOWS (NON-BLOCKING)   #
########################################

def run_iperf_flow(server_ip, iperf_rate_str, duration):
    """
    Launch iPerf3 client in parallel (non-blocking).
    We assume we run this script on the local "client" host, so 'iperf3 -c <server_ip>'
    will originate from the local IP automatically (or from default route).

    If you need to force a specific source IP, add '-B <local_ip>' below.
    """
    cmd = [
        "iperf3",
        "-c", server_ip,
        "-u",
        "-b", iperf_rate_str,
        "-t", str(duration)
    ]
    print("Launching:", " ".join(cmd))
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

########################################
# 4) LOAD HOST IPs FROM topology.json  #
########################################

def load_hosts_from_topology(topo_file="topology.json"):
    """
    Parse the 'hosts' section in topology.json, extract IP (stripping out '/24'),
    and return a list of IP strings. e.g. "10.0.1.1/24" -> "10.0.1.1"
    """
    with open(topo_file, "r") as f:
        topo = json.load(f)

    all_ips = []
    for host_name, host_info in topo["hosts"].items():
        ip_cidr = host_info["ip"]     # e.g. "10.0.1.1/24"
        ip_only = ip_cidr.split("/")[0]
        all_ips.append(ip_only)

    return all_ips

########################################
# 5) DETECT LOCAL IP
########################################

def detect_local_ip():
    """
    Attempt to detect the local IP by creating an outgoing UDP socket
    to a dummy address and reading the local socket name.
    This helps us figure out the IP address used by default route.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # connect to a dummy IP; no actual data is sent
        s.connect(("8.8.8.8", 9999))
        local_ip = s.getsockname()[0]
    except Exception:
        # fallback
        local_ip = socket.gethostbyname(socket.gethostname())
    finally:
        s.close()

    return local_ip

########################################
# 6) MAIN LOGIC
########################################

def main():
    """
    Usage scenario:
    - 'topology.json' in same folder, listing h1..h9 IPs.
    - This script runs on whichever host is the "client" (detected by detect_local_ip()).
    - We exclude that local_ip from the random server list.
    - Each hour, pick random subset of the remaining IPs to receive traffic,
      dividing the total bytes among them.
    """
    # 1) Load 25 lines from .txt
    data_file = "data_rates_c_sun.txt"  # or your chosen file
    hourly_totals = load_hourly_totals(data_file)

    # 2) Each "hour" is 10 real seconds
    hour_duration = 10

    # 3) Load host IPs from topology.json
    topo_file = "topology.json"
    all_hosts = load_hosts_from_topology(topo_file)

    # 4) Detect local IP (the client)
    local_ip = detect_local_ip()

    print(f"\nLoaded {len(all_hosts)} hosts from '{topo_file}': {all_hosts}")
    print(f"Local IP detected: {local_ip}")
    if local_ip not in all_hosts:
        print(f"Warning: local IP {local_ip} not found in topology hosts. We'll still exclude it if present.")

    start_time = time.time()

    for hour_idx in range(25):
        total_bytes = hourly_totals[hour_idx]
        bytes_per_sec = total_bytes / hour_duration
        total_bps = bytes_per_sec * 8

        # exclude local_ip from the server list
        possible_servers = [ip for ip in all_hosts if ip != local_ip]
        if not possible_servers:
            print("No possible servers left! Something is off.")
            break

        # randomly choose how many servers
        num_servers = random.randint(1, len(possible_servers))
        chosen_servers = random.sample(possible_servers, num_servers)

        # share the total bps among chosen servers
        bps_per_server = total_bps / num_servers
        iperf_b_str = bits_to_iperf_notation(bps_per_server)

        print(f"\nHour {hour_idx}: total_bytes={total_bytes:.0f} => {bps_per_server:.1f} bps each.")
        print(f"Local client: {local_ip}")
        print(f"{num_servers} servers => {chosen_servers}")

        for srv_ip in chosen_servers:
            run_iperf_flow(srv_ip, iperf_b_str, hour_duration)

        time.sleep(hour_duration)

    elapsed = time.time() - start_time
    print(f"\nAll 25 hours completed in {elapsed:.2f} seconds real time.")

    # Optional: run an analyzer after finishing
    print("Running analyze_traffic_24h.py...")
    analyze_cmd = ["python3", "analyze_traffic_24h.py"]
    subprocess.run(analyze_cmd)

if __name__ == "__main__":
    main()
