#!/usr/bin/env python3
import pyshark
import os
import matplotlib.pyplot as plt
import seaborn as sns
import matplotlib as mpl

###############################
# Switch => label, color
###############################
legend_mapping = {
    "s5": "Spine SW 1",
    "s6": "Spine SW 2",
    "s7": "Spine SW 3"
}
color_mapping = {
    "s5": "tab:blue",
    "s6": "tab:gray",
    "s7": "tab:orange"
}

def find_global_earliest_time(pcap_dir, spines, display_filter=None):
    """
    1) First pass: find the minimum sniff timestamp among all .pcap for s5, s6, s7.
    Return None if no packets found.
    """
    global_min_time = None

    for file in os.listdir(pcap_dir):
        if not file.endswith(".pcap"):
            continue
        switch_interface = file.split(".")[0]  # e.g. s5-eth1
        if not any(switch_interface.startswith(sp) for sp in spines):
            continue

        pcap_path = os.path.join(pcap_dir, file)
        capture = pyshark.FileCapture(pcap_path, display_filter=display_filter)

        for packet in capture:
            ts = float(packet.sniff_time.timestamp())
            if global_min_time is None or ts < global_min_time:
                global_min_time = ts

        capture.close()

    return global_min_time

def bin_pcap_by_hour(pcap_path, sw_key, global_earliest, hour_duration, traffic_dict,
                     SHIFT=0.0, display_filter=None):
    """
    2) Second pass: parse the pcap, bin each packet's timestamp with:
         elapsed = (ts - global_earliest) - SHIFT
         hour_idx = int(elapsed // hour_duration)
    If hour_idx < 0, we skip it (meaning it fell before the SHIFT).
    Merge results into traffic_dict[sw_key][hour_idx].
    """
    capture = pyshark.FileCapture(pcap_path, display_filter=display_filter)

    for packet in capture:
        ts = float(packet.sniff_time.timestamp())
        if ts >= global_earliest:
            elapsed = (ts - global_earliest) - SHIFT
            if elapsed < 0:
                # If you want to skip traffic that occurs before SHIFT
                continue
            hour_idx = int(elapsed // hour_duration)
            size = int(packet.length)

            if hour_idx not in traffic_dict[sw_key]:
                traffic_dict[sw_key][hour_idx] = 0
            traffic_dict[sw_key][hour_idx] += size

    capture.close()

def plot_traffic_binned(traffic_data_dict, output_file, max_hours=25):
    """
    Plots { 's5': { hour_idx: bytes, ...}, 's6': {...}, 's7': {...} }
    for hour bins 0..(max_hours-1).
    """
    if not traffic_data_dict:
        print("No data to plot.")
        return

    sns.set_theme(style="whitegrid", context="paper", font_scale=1.3)
    mpl.rcParams['figure.figsize'] = (6, 4)
    mpl.rcParams['figure.dpi'] = 300
    mpl.rcParams['axes.labelsize'] = 14
    mpl.rcParams['legend.fontsize'] = 11
    mpl.rcParams['xtick.labelsize'] = 11
    mpl.rcParams['ytick.labelsize'] = 11

    plt.figure()

    for sw_key, hour_map in traffic_data_dict.items():
        # Sort by hour_index
        sorted_hours = sorted(hour_map.items(), key=lambda x: x[0])
        # Filter out hour >= max_hours
        filtered = [(h, vol) for (h, vol) in sorted_hours if h < max_hours]

        hour_indices = [h for (h, _) in filtered]
        traffic_kb  = [vol / 1024.0 for (_, vol) in filtered]

        label = legend_mapping.get(sw_key, sw_key)
        color = color_mapping.get(sw_key, "tab:blue")

        plt.plot(hour_indices, traffic_kb,
                 marker='o', markersize=4, linewidth=1.5,
                 label=label, color=color)

    plt.xlabel("Time (hours)")
    plt.ylabel("Traffic Volume (KB)")
    plt.grid(True, which='major', alpha=0.5)

    ax = plt.gca()
    ax.spines['right'].set_visible(False)
    ax.spines['top'].set_visible(False)

    plt.xlim(0, max_hours - 1)
    plt.legend(loc='upper left', frameon=False)
    plt.tight_layout()

    pdf_file = output_file.replace(".png", ".pdf")
    plt.savefig(pdf_file, format='pdf')
    print(f"Plot saved as {pdf_file}")
    plt.savefig(output_file, dpi=300)
    plt.close()

def main():
    pcap_dir = "./pcaps"
    output_dir = "./plots"
    os.makedirs(output_dir, exist_ok=True)

    # Suppose each "hour" is 10 real seconds
    hour_duration = 10.0
    # up to 25 hours => hour indices 0..24
    max_hours = 25

    # SHIFT: if you see actual traffic starting around 3s,
    # set SHIFT=3.0 to align that to hour 0. Adjust as needed.
    SHIFT = 9.0

    # The spines we care about
    spines = ["s5", "s6", "s7"]

    # 1) First pass: find global earliest time
    # If you suspect non-UDP/TCP traffic, use display_filter=None or "ip"
    display_filter = "udp or tcp"
    #display_filter = "udp"
    global_earliest = find_global_earliest_time(pcap_dir, spines, display_filter=display_filter)
    if global_earliest is None:
        print("No packets found at all. Exiting.")
        return

    print(f"Global earliest packet time = {global_earliest:.3f}")

    # 2) Prepare our final dictionary
    traffic_data_dict = { "s5":{}, "s6":{}, "s7":{} }

    # 3) Second pass: parse each pcap, bin by hour with SHIFT
    for file in os.listdir(pcap_dir):
        if file.endswith(".pcap"):
            switch_interface = file.split(".")[0]
            if any(switch_interface.startswith(s) for s in spines):
                sw_key = switch_interface[:2]
                pcap_path = os.path.join(pcap_dir, file)
                print(f"Binning {file} for {sw_key} ...")

                bin_pcap_by_hour(
                    pcap_path, sw_key,
                    global_earliest,
                    hour_duration,
                    traffic_data_dict,
                    SHIFT=SHIFT,
                    display_filter=display_filter
                )

    # 4) Plot
    output_file = os.path.join(output_dir, "traffic_distribution_24h.png")
    plot_traffic_binned(traffic_data_dict, output_file, max_hours=max_hours)

if __name__ == "__main__":
    main()
