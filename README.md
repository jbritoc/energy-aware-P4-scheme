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
- `traffic.py` — traffic generation
- `analyze_traffic_24h.py` — traffic analysis and graphic generation

## How It Works

The P4 program monitors traffic over a configurable measurement window and determines how many spine switches are required for the current load. It does so by using registers for traffic volume, timestamps, thresholds, measurement window, switch type, and required spine-switch count.

The SDN controller complements the data plane by:
- installing IPv4 forwarding rules,
- creating multicast groups,
- initializing the P4 registers used by the pipeline,
- and running a dynamic power-management routine.

Based on the value computed by the data plane, the controller periodically reads the required number of spine switches from non-spine devices and enables or disables spine-switch interfaces accordingly. In the emulated environment, interface activation/deactivation is used to approximate switch power management.

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

make
