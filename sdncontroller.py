#!/usr/bin/env python3

import argparse
import os
import sys
import time
import json
import grpc
import subprocess

from time import sleep
from host import Host, Link, Path, Switch, add_link
import bmpy_utils as utils
from runtime_CLI import RuntimeAPI, load_json_config

# Import P4Runtime libraries from the parent utils directory.
sys.path.append(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '../../utils/'
    )
)

import p4runtime_lib.bmv2
import p4runtime_lib.helper
from p4runtime_lib.error_utils import printGrpcError
from p4runtime_lib.switch import ShutdownAllSwitchConnections


# ============================================================================
# Topology and switch-role constants
# ============================================================================

SWITCH_TO_HOST_PORT = 1
SWITCH_TO_SWITCH_PORT = 2

# Number of devices by role in the Mininet topology
LEAF_SWITCHES = 4
SPINE_SWITCHES = 3
AGF_UP = 1

# Roles identifiers written into the P4 register "switch_type"
LEAF_SWITCH_TYPE = 0
SPINE_SWITCH_TYPE = 1
AGF_UP_TYPE = 2


# ============================================================================
# Runtime state
# ============================================================================

# Tracks the current state of switch interfaces to avoid redundant actions.
switch_interface_states = {}

# Stores the last observed number of required spine switches per switch.
last_spine_switch_values = {}


# ============================================================================
# Register access helpers
# ============================================================================

def ecmpModeControlCLI(switches):
    """
    Simple CLI helper to manually enable or disable ECMP mode on a switch.
    """
    print('ECMP control menu')
    sw_id = int(input('Enter switch ID: '))
    mode = int(input('Enter ECMP mode (0 or 1): '))
    modifyRegister(switches[sw_id - 1], 'ecmp_mode', 0, mode)


def modifyRegister(sw, register_name, index, value):
    """
    Write a value into a BMv2 register through the Thrift CLI.
    """
    sw_port_shift = int(sw.name[1:])
    standard_client, mc_client = utils.thrift_connect(
        'localhost',
        9089 + sw_port_shift,
        RuntimeAPI.get_thrift_services(1)
    )
    load_json_config(standard_client, None)
    runtime_api = RuntimeAPI('SimplePre', standard_client, mc_client)
    runtime_api.do_register_write(f'{register_name} {index} {value}')


def readRegister(sw, register_name, index):
    """
    Read a value from a BMv2 register through the Thrift CLI.
    """
    sw_port_shift = int(sw.name[1:])
    standard_client, mc_client = utils.thrift_connect(
        'localhost',
        9089 + sw_port_shift,
        RuntimeAPI.get_thrift_services(1)
    )
    load_json_config(standard_client, None)
    runtime_api = RuntimeAPI('SimplePre', standard_client, mc_client)
    return runtime_api.do_register_read(f'{register_name} {index}')


# ============================================================================
# Interface power-state control helpers
# ============================================================================

def disable_switch_interfaces(switch_name):
    """
    Disable all switch-to-switch interfaces of a given switch and verify the result.
    """
    for interface_id in range(1, SWITCH_TO_SWITCH_PORT + 1):
        interface_name = f"{switch_name}-eth{interface_id}"
        subprocess.run(["sudo", "ip", "link", "set", interface_name, "down"])
        print(f"Interface {interface_name} has been disabled.")

        if verify_interface_status(interface_name, expected_status="DOWN"):
            print(f"Verified: Interface {interface_name} is DOWN.")
        else:
            print(f"Warning: Failed to disable interface {interface_name}.")


def enable_switch_interfaces(switch_name):
    """
    Enable all switch-to-switch interfaces of a given switch and verify the result.
    """
    for interface_id in range(1, SWITCH_TO_SWITCH_PORT + 1):
        interface_name = f"{switch_name}-eth{interface_id}"
        subprocess.run(["sudo", "ip", "link", "set", interface_name, "up"])
        print(f"Interface {interface_name} has been enabled.")

        if verify_interface_status(interface_name, expected_status="UP"):
            print(f"Verified: Interface {interface_name} is UP.")
        else:
            print(f"Warning: Failed to enable interface {interface_name}.")


def verify_interface_status(interface_name, expected_status):
    """
    Verify whether a Linux interface is currently UP or DOWN.
    """
    result = subprocess.run(
        ["ip", "link", "show", interface_name],
        stdout=subprocess.PIPE,
        text=True
    )
    return expected_status in result.stdout


def update_switch_interfaces(switch, enable, switch_interface_states):
    """
    Enable or disable switch interfaces only if a state change is required.
    """
    if switch.name in switch_interface_states and switch_interface_states[switch.name] == enable:
        return

    if enable:
        enable_switch_interfaces(switch.name)
    else:
        disable_switch_interfaces(switch.name)

    switch_interface_states[switch.name] = enable


# ============================================================================
# P4Runtime programming helpers
# ============================================================================

def addMulticastingGroup(p4_info_helper, switches, links):
    """
    Install a multicast group in the leaf switches.
    """
    for sw in switches[:4]:
        replicas = []
        for i in range(1, 3):
            replicas.append({'egress_port': i, 'instance': 1})

        multicast_entry = p4_info_helper.buildMulticastGroupEntry(1, replicas)
        sw.WritePREEntry(multicast_entry)
        print('Done writing PRE entry')


def writeForwardingRule(p4info_helper, sw, ip_address, mask, mac_address, port):
    """
    Install an IPv4 LPM forwarding rule on a switch.
    """
    table_entry = p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": (ip_address, mask)
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr": mac_address,
            "port": port
        }
    )
    sw.WriteTableEntry(table_entry)
    print("Installed ingress forwarding rule on %s" % sw.name)


def readTableRules(p4info_helper, sw):
    """
    Read all table entries installed on a switch.
    """
    print('\n----- Reading table rules for %s -----' % sw.name)
    for response in sw.ReadTableEntries():
        for entity in response.entities:
            entry = entity.table_entry
            print(entry)
            print('-----')


def printCounter(p4info_helper, sw, counter_name, index):
    """
    Read and print a counter entry from the switch.
    """
    i = 0
    for response in sw.ReadCounters(p4info_helper.get_counters_id(counter_name), index):
        for entity in response.entities:
            counter = entity.counter_entry
            print(
                "%i %s %s %d: %d packets (%d bytes)" % (
                    i,
                    sw.name,
                    counter_name,
                    index,
                    counter.data.packet_count,
                    counter.data.byte_count
                )
            )
            i += 1


def getCounterValues(p4info_helper, sw, counter_name, index):
    """
    Read and return the packet and byte counts for a counter entry.
    """
    for response in sw.ReadCounters(p4info_helper.get_counters_id(counter_name), index):
        for entity in response.entities:
            counter = entity.counter_entry
            return counter.data.packet_count, counter.data.byte_count


# ============================================================================
# Main controller logic
# ============================================================================

def main(p4info_file_path, bmv2_file_path):
    """
    Main controller workflow:
    1. Load topology information.
    2. Build switch and host objects.
    3. Install forwarding rules.
    4. Initialize P4 registers.
    5. Monitor the required number of spine switches and update interface states.
    """
    p4info_helper = p4runtime_lib.helper.P4InfoHelper(p4info_file_path)

    with open('topology.json') as file:
        json_data = json.load(file)

    hosts = []
    for hostid in json_data['hosts']:
        host_data = json_data['hosts'][hostid]
        ipmask = host_data['ip'].split('/')
        host = Host(
            name=hostid,
            ip=ipmask[0],
            mask=int(ipmask[1]),
            mac=host_data['mac']
        )
        hosts.append(host)

    num_of_switches = len(json_data['switches'])
    print('Number of switches:', num_of_switches)

    links = {}
    switches = []

    try:
        # Create a P4Runtime connection for each switch in the topology.
        for i in range(1, num_of_switches + 1):
            s = Switch(
                name=f's{i}',
                address=f'127.0.0.1:5005{i}',
                device_id=i - 1,
                proto_dump_file=f'logs/s{i}-p4runtime-requests.txt'
            )
            switches.append(s)

        # Build topology links.
        for link_data in json_data['links']:
            obj1 = link_data[0]
            obj2 = link_data[1]

            if obj1[0] == 'h':
                obj1 = hosts[int(obj1[1]) - 1]
                srcport = None
            else:
                srcport = int(obj1[4])
                obj1 = switches[int(obj1[1]) - 1]

            if obj2[0] == 'h':
                obj2 = hosts[int(obj2[1]) - 1]
                dstport = None
            else:
                dstport = int(obj2[4])
                obj2 = switches[int(obj2[1]) - 1]

            # Keep s6 and s7 as ECMP-only links in this topology model.
            if obj1.name in ('s6', 's7'):
                add_link(links, obj1, obj2, srcport, dstport)
                continue

            if obj2.name in ('s6', 's7'):
                add_link(links, obj2, obj1, dstport, srcport)
                continue

            add_link(links, obj1, obj2, srcport, dstport)
            add_link(links, obj2, obj1, dstport, srcport)

        # Compute paths and next hops from every switch to every host.
        paths = {}
        nhop = {}

        for s in switches:
            paths[s] = {}
            nhop[s] = {}
            for h in hosts:
                path_info = Path(links, s, h)
                paths[s][h] = path_info.path
                nhop[s][h] = (path_info.nhop, path_info.onehop)

        for s in paths:
            print(s.name, 'next hops:', nhop[s])

        # Push the P4 program and install forwarding rules.
        i = 1
        for s in switches:
            s.MasterArbitrationUpdate()
            s.SetForwardingPipelineConfig(
                p4info=p4info_helper.p4info,
                bmv2_json_file_path=bmv2_file_path
            )
            print(f'Installed P4 Program using SetForwardingPipelineConfig on s{i}')
            i += 1

            rules_installed = set()

            for h in nhop[s]:
                # One-hop path means the host is directly attached to this leaf switch.
                if nhop[s][h][1]:
                    print(
                        f'Installing on {s.name}: ip {h.ip} mask 32 '
                        f'mac_address {h.mac} port {nhop[s][h][0]}'
                    )
                    writeForwardingRule(
                        p4info_helper,
                        sw=s,
                        ip_address=h.ip,
                        mask=32,
                        mac_address=h.mac,
                        port=nhop[s][h][0]
                    )
                else:
                    if (h.mask_ip(), h.mask) not in rules_installed:
                        rules_installed.add((h.mask_ip(), h.mask))
                        print(
                            f'Installing on {s.name}: ip {h.mask_ip()} mask {h.mask} '
                            f'mac_address 08:00:00:00:02:22 port {nhop[s][h][0]}'
                        )
                        writeForwardingRule(
                            p4info_helper,
                            sw=s,
                            ip_address=h.mask_ip(),
                            mask=h.mask,
                            mac_address="08:00:00:00:02:22",
                            port=nhop[s][h][0]
                        )

        addMulticastingGroup(p4info_helper, switches, links)

        # Switch index ranges in the current topology:
        # s1-s4: leaf switches
        # s5-s7: spine switches
        # s8:    AGF UP
        spine_switch_start_id = LEAF_SWITCHES
        spine_switch_end_id = spine_switch_start_id + SPINE_SWITCHES - 1
        agf_up_id = LEAF_SWITCHES + SPINE_SWITCHES

        # Mark spine switches in the P4 register.
        for i in range(spine_switch_start_id, spine_switch_end_id + 1):
            modifyRegister(switches[i], 'switch_type', 0, SPINE_SWITCH_TYPE)

        # Mark the AGF UP in the P4 register.
        modifyRegister(switches[agf_up_id], 'switch_type', 0, AGF_UP_TYPE)

        # Enable ECMP mode on the AGF UP and all leaf switches.
        modifyRegister(switches[agf_up_id], 'ecmp_mode', 0, 1)

        for i in range(0, spine_switch_start_id):
            modifyRegister(switches[i], 'ecmp_mode', 0, 1)

        # Initialize controller-managed P4 registers on all switches.
        for i in range(len(switches)):
            modifyRegister(switches[i], 'epoch_length', 0, 10000000)
            modifyRegister(switches[i], 'packet_size_threshold1', 0, 0)
            modifyRegister(switches[i], 'packet_size_threshold2', 0, 300000)
            modifyRegister(switches[i], 'packet_size_threshold3', 0, 500000)

        # Dynamic power-management loop.
        while True:
            for sw in switches:
                switch_type = readRegister(sw, 'switch_type', 0)

                # Spine switches do not manage their own interface state.
                if switch_type != SPINE_SWITCH_TYPE:
                    spine_switch_value = readRegister(sw, 'spine_switches', 0)
                    port_value = readRegister(sw, 'output_port_register', 0)

                    print(f"Switch {sw.name} 'spine_switches' register value: {spine_switch_value}")
                    print(f"Switch {sw.name} 'output_port_register' register value: {port_value}")

                    # Apply updates only if the number of required spine switches changed.
                    if (
                        sw.name not in last_spine_switch_values
                        or last_spine_switch_values[sw.name] != spine_switch_value
                    ):
                        last_spine_switch_values[sw.name] = spine_switch_value

                        if spine_switch_value != 0:
                            if spine_switch_value == SPINE_SWITCHES:
                                # All spine switches are required.
                                for i in range(spine_switch_start_id, spine_switch_end_id + 1):
                                    update_switch_interfaces(
                                        switches[i],
                                        True,
                                        switch_interface_states
                                    )
                            else:
                                # Enable only the required number of spine switches.
                                for i in range(spine_switch_start_id, spine_switch_end_id + 1):
                                    if i >= spine_switch_start_id + spine_switch_value:
                                        update_switch_interfaces(
                                            switches[i],
                                            False,
                                            switch_interface_states
                                        )
                                    else:
                                        update_switch_interfaces(
                                            switches[i],
                                            True,
                                            switch_interface_states
                                        )

            time.sleep(10)

    except KeyboardInterrupt:
        print("Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='P4Runtime Controller')
    parser.add_argument(
        '--p4info',
        help='p4info proto in text format from p4c',
        type=str,
        action="store",
        required=False,
        default='./build/energy_aware.p4.p4info.txt'
    )
    parser.add_argument(
        '--bmv2-json',
        help='BMv2 JSON file from p4c',
        type=str,
        action="store",
        required=False,
        default='./build/energy_aware.json'
    )
    args = parser.parse_args()

    if not os.path.exists(args.p4info):
        parser.print_help()
        print("\np4info file not found: %s\nHave you run 'make'?" % args.p4info)
        parser.exit(1)

    if not os.path.exists(args.bmv2_json):
        parser.print_help()
        print("\nBMv2 JSON file not found: %s\nHave you run 'make'?" % args.bmv2_json)
        parser.exit(1)

    main(args.p4info, args.bmv2_json)
