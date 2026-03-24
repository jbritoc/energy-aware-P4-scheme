## Introduction

This is an implementation of P4Green, a system to reduce the number of active switches in a data center and to send workloads towards servers with renewable energy.

To repeat the experiment, clone into the tutorials/exercises/ directory of P4 tutorial virtual machine (https://github.com/p4lang/tutorials) and run make.

The emulator generates a data center topology with a core switch, three aggregation switches, 4 access switches and 9 hosts. 
Each access switch is connected to 2 hosts. A core switch is connected to one host (i.e. outside network).
RuntimeAPI calculates shortest paths to each host for each switch and initializes all the registers.
The P4 program includes an "arp_fool"-type action that returns a fake MAC address per each arp reply.


