#!/usr/bin/env python3
import os
import re
import numpy as np
import seaborn as sns
import matplotlib as mpl
import matplotlib.pyplot as plt

############################
# 1) GLOBAL STYLING SETUP  #
############################

# Increase the font sizes a bit more for print legibility.
sns.set_theme(style="whitegrid", context="paper", font_scale=1.4)
mpl.rcParams['axes.labelsize'] = 14
mpl.rcParams['legend.fontsize'] = 12
mpl.rcParams['xtick.labelsize'] = 12
mpl.rcParams['ytick.labelsize'] = 12

##########################################
# 2) PARSE AND LOAD DATA (IN BYTES)      #
##########################################

def parse_data_rate(value):
    """
    Parse traffic rates with optional units (K, M, G, or no unit for bytes)
    and return the numeric value in bytes.
    """
    unit_multipliers = {
        "K": 1e3,   # Kilobytes
        "M": 1e6,   # Megabytes
        "G": 1e9,   # Gigabytes
        "": 1       # Bytes
    }

    match = re.match(r"([\d.]+)\s*([KMG]?)", value.strip().upper())
    if match:
        numeric_part = float(match.group(1))
        unit = match.group(2)
        return numeric_part * unit_multipliers[unit]  # Always bytes internally
    else:
        raise ValueError(f"Invalid data rate format: '{value}'")

def load_data_rates(file_path):
    """
    Load traffic rates from the input file, line by line.
    Each rate is converted to bytes. Returns a list of numeric values in bytes.
    """
    data_rates = []
    try:
        with open(file_path, 'r') as f:
            for line in f:
                if line.strip():
                    data_rates.append(parse_data_rate(line.strip()))
        return data_rates
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.")
        return None
    except ValueError as e:
        print(e)
        return None

##########################################
# 3) PLOT FUNCTION WITH LINE AND AREA COLOR OPTIONS #
##########################################

def plot_traffic_curve_journal(time_intervals, data_rates, original_units, output_file, area_color="lightblue", line_color="blue"):
    """
    Plot the traffic curve for a Q1–Q2 journal style figure with customizable area and line colors.
    """
    # Create the figure with a moderate size, high resolution
    plt.figure(figsize=(6, 4), dpi=300)

    # Plot the curve
    plt.plot(
        time_intervals,
        data_rates,
        marker='o',
        markersize=4,
        linewidth=1.5,
        color=line_color,
        label='Traffic'
    )

    # Subtle fill under the curve with the specified area color
    plt.fill_between(
        time_intervals,
        data_rates,
        color=area_color,
        alpha=0.5  # Adjust transparency if needed
    )

    plt.title("Sunday", fontsize=14)

    # Axis labels
    plt.xlabel("Time (hours)")
    #plt.ylabel(f"Traffic Volume ({original_units})")
    plt.ylabel(f"Traffic Volume (KB)")

    # Remove top/right spines for a cleaner, modern look
    ax = plt.gca()
    ax.spines['right'].set_visible(False)
    ax.spines['top'].set_visible(False)

    # X-axis limits
    plt.xlim(time_intervals[0], time_intervals[-1])

    # X-ticks at fixed intervals (e.g., every 5 hours)
    plt.xticks(np.arange(0, 25, step=5))

    plt.ylim(0, 500)
    plt.yticks([0, 125, 250, 375, 500])


    # Add the legend
    plt.legend(loc='best', frameon=False)

    # Tight layout to avoid clipping
    plt.tight_layout()

    # Save as PDF for vector graphics
    plt.savefig(output_file, format='pdf')
    plt.close()
    print(f"Traffic curve plot saved as '{output_file}'.")

########################
# 4) MAIN LOGIC        #
########################

def main():
    file_path = "data_rates_f_sun.txt"  # example data file
    output_dir = "./plots"

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # 1) Load data in bytes
    data_rates_in_bytes = load_data_rates(file_path)
    if data_rates_in_bytes is None:
        return

    # 2) Determine the *dominant* unit in the file for labeling and scaling
    file_lines = [line.strip().upper() for line in open(file_path) if line.strip()]

    if any("G" in line for line in file_lines):
        original_units = "GB"
        data_rates = [x / 1e9 for x in data_rates_in_bytes]  # Convert from bytes to GB
    elif any("M" in line for line in file_lines):
        original_units = "MB"
        data_rates = [x / 1e6 for x in data_rates_in_bytes]  # Convert from bytes to MB
    elif any("K" in line for line in file_lines):
        original_units = "KB"
        data_rates = [x / 1e3 for x in data_rates_in_bytes]  # Convert from bytes to KB
    else:
        original_units = "B"
        data_rates = data_rates_in_bytes

    # 3) Prepare the x-axis
    num_points = len(data_rates)
    time_intervals = np.arange(num_points)

    # 4) Plot with customizable colors
    output_file = os.path.join(output_dir, "traffic_curve_f_sun_KB.pdf")
    plot_traffic_curve_journal(
        time_intervals,
        data_rates,
        original_units,
        output_file,
        area_color="lightgrey",  # Example: change area color
        line_color="grey"  # Example: change line color
    )

if __name__ == "__main__":
    main()
