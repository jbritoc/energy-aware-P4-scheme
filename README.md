# Energy-Aware P4 Scheme

## Overview

This repository contains an energy-aware traffic management scheme implemented with **P4**, **Python**, and **Mininet**.

The system dynamically adapts the number of active forwarding paths according to the observed traffic load. It combines a programmable data plane, an SDN controller, traffic generation with `iperf3`, and packet-capture analysis.

## Topology

The emulated topology includes:

- 4 **leaf switches**
- 3 **spine switches**
- 1 **AGF UP switch**
- 9 hosts

## Main Files

- `energy_aware.p4` — P4 data-plane program
- `sdncontroller.py` — SDN controller
- `topology.json` — topology description
- `traffic.py`— traffic generation
- `analyze_traffic_24h.py`  — traffic analysis and graphics generation

## How It Works

The P4 program monitors traffic over a configurable measurement window and determines how many spine switches are required for the current load.

The SDN controller complements the data plane by:
- installing IPv4 forwarding rules,
- initializing the P4 registers used by the pipeline,
- and running a dynamic power-management routine.

Based on the value computed by the data plane, the controller periodically reads the required number of spine switches and enables or disables spine-switch interfaces accordingly. In the emulated environment, interface activation/deactivation is used to approximate dynamic power management. 

## Traffic-Profile-Based Evaluation

The evaluation follows the methodology described in the paper using eight traffic profiles derived from four urban clusters:

- **Residential**
- **Public transportation**
- **Business**
- **Recreational**

For each cluster, two daily patterns were considered: **Monday** and **Sunday**. In the repository, the input `.txt` files represent these scenario/day combinations and are used as traffic-profile inputs for the flow generator. The original traffic patterns were scaled down from MB to KB for emulation, and each **10-second** execution slot represents **one hour** of the daily profile. 

During each experiment, traffic is generated from edge hosts toward the AGF UP side, while the controller and data plane adapt the number of active spine switches to the demand level. Packet captures can then be analyzed to visualize traffic distribution across spine switches over the emulated 24-hour period. 

## Requirements

This project is intended to run inside the **P4 tutorial VM** from:

https://github.com/p4lang/tutorials

It requires:

- Python 3
- Mininet
- BMv2
- P4Runtime
- iperf3

## Running the Project

Compile and start the topology with:

```bash
make
