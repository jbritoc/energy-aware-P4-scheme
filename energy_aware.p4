/* -*- P4_16 -*- */
#include <core.p4>
#include <v1model.p4>

const bit<16> TYPE_IPV4 = 0x800;

/*************************************************************************
*********************** H E A D E R S  ***********************************
*************************************************************************/

#define CPU_PORT 254
#define ETHERTYPE_ARP 0x0806

// Device hierarchy
#define LEAF_SWITCH 0
#define SPINE_SWITCH 1
#define AGF_UP 2

// Maximum number of spine switches in the topology.
#define SPINE_SWITCH_COUNT 3

// Number of host-facing ports on leaf switches in this topology.
#define HOST_NUM 2

// Packet-type markers used during packet classification.
#define ARP_PACKET 0
#define SPINE_PATH_PACKET 1

typedef bit<9>  egressSpec_t;
typedef bit<48> macAddr_t;
typedef bit<32> ip4Addr_t;

header ethernet_t {
    macAddr_t dstAddr;
    macAddr_t srcAddr;
    bit<16>   etherType;
}

header arp_t {
    bit<16> hwType;
    bit<16> protoType;
    bit<8> hwAddrLen;
    bit<8> protoAddrLen;
    bit<16> opcode;
    bit<48> srcHwAddr;
    bit<32> srcProtoAddr;
    bit<48> dstHwAddr;
    bit<32> dstProtoAddr;
}

header ipv4_t {
    bit<4>    version;
    bit<4>    ihl;
    bit<8>    diffserv;
    bit<16>   totalLen;
    bit<16>   identification;
    bit<3>    flags;
    bit<13>   fragOffset;
    bit<8>    ttl;
    bit<8>    protocol;
    bit<16>   hdrChecksum;
    ip4Addr_t srcAddr;
    ip4Addr_t dstAddr;
}

header tcp_t {
    bit<16> srcPort;
    bit<16> dstPort;
    bit<32> seqNo;
    bit<32> ackNo;
    bit<4>  dataOffset;
    bit<3>  res;
    bit<3>  ecn;
    bit<1>  urg;
    bit<1>  ack;
    bit<1>  psh;
    bit<1>  rst;
    bit<1>  syn;
    bit<1>  fin;
    bit<16> window;
    bit<16> checksum;
    bit<16> urgentPtr;
}

header udp_t {
    bit<16> srcPort;
    bit<16> dstPort;
    bit<16> length;
    bit<16> checksum;
}

struct metadata {
    /* empty */
}

struct headers {
    ethernet_t ethernet;
    arp_t      arp;
    ipv4_t     ipv4;
    tcp_t      tcp;
    udp_t      udp;
}

/*************************************************************************
*********************** P A R S E R **************************************
*************************************************************************/

parser MyParser(
    packet_in packet,
    out headers hdr,
    inout metadata meta,
    inout standard_metadata_t standard_metadata
) {
    state start {
        transition parse_ethernet;
    }

    state parse_ethernet {
        packet.extract(hdr.ethernet);
        transition select(hdr.ethernet.etherType) {
            TYPE_IPV4:     parse_ipv4;
            ETHERTYPE_ARP: parse_arp;
            default:       accept;
        }
    }

    state parse_arp {
        packet.extract(hdr.arp);
        transition accept;
    }

    state parse_ipv4 {
        packet.extract(hdr.ipv4);
        transition select(hdr.ipv4.protocol) {
            6:       parse_tcp;
            17:      parse_udp;
            default: accept;
        }
    }

    state parse_tcp {
        packet.extract(hdr.tcp);
        transition accept;
    }

    state parse_udp {
        packet.extract(hdr.udp);
        transition accept;
    }
}

/*************************************************************************
************ CHECKSUM VERIFICATION ***************************************
*************************************************************************/

control MyVerifyChecksum(inout headers hdr, inout metadata meta) {
    apply { }
}

/*************************************************************************
************** INGRESS PROCESSING ****************************************
*************************************************************************/

control MyIngress(
    inout headers hdr,
    inout metadata meta,
    inout standard_metadata_t standard_metadata
) {
    // Enables or disables ECMP-based load balancing.
    register<bit<1>>(1) ecmp_mode;

    // Register (c): number of required spine switches.
    register<bit<32>>(1) spine_switches;

    // Register (b): timestamp reference for the measurement window.
    register<bit<48>>(1) epoch_start;

    // Register (a): cumulative traffic observed during the window.
    register<bit<32>>(1) traffic;

    // Register (f): switch role (e.g., leaf, spine).
    register<bit<2>>(1) switch_type;

    // Register (e): measurement window duration.
    register<bit<48>>(1) epoch_length;

    // Register (d): traffic thresholds.
    register<bit<32>>(1) packet_size_threshold1;
    register<bit<32>>(1) packet_size_threshold2;
    register<bit<32>>(1) packet_size_threshold3;

    // Helper register for packet classification.
    register<bit<1>>(5) packet_type;

    // Debug/monitoring register used by the controller.
    register<bit<9>>(1) output_port_register;

    action drop() {
        mark_to_drop(standard_metadata);
    }

    action send_back() {
        hdr.arp.opcode = 2;
        hdr.arp.srcProtoAddr = hdr.arp.dstProtoAddr;
        standard_metadata.egress_spec = standard_metadata.ingress_port;
    }

    action ipv4_forward(macAddr_t dstAddr, egressSpec_t port) {
        standard_metadata.egress_spec = port;
        hdr.ethernet.srcAddr = hdr.ethernet.dstAddr;
        hdr.ethernet.dstAddr = dstAddr;
        hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
    }

    // Compute the number of spine switches required for the current traffic level
    action calculate_required_spine_switches(
        in bit<32> packet_sz_cn,
        in bit<32> packet_th1,
        in bit<32> packet_th2,
        in bit<32> packet_th3,
        out bit<32> required_spine_count
    ) {
        if (packet_sz_cn > packet_th3) {
            required_spine_count = 3;
        } else if (packet_sz_cn > packet_th2) {
            required_spine_count = 2;
        } else {
            required_spine_count = 1;
        }
    }

    action run_ECMP_UDP(in bit<2> type, in bit<32> required_spine_count) {
        bit<16> base = 0;

        if (type == LEAF_SWITCH) {
            base = (bit<16>)(HOST_NUM + 1);
        } else if (type == AGF_UP) {
            base = (bit<16>)1;
        }

        hash(
            standard_metadata.egress_spec,
            HashAlgorithm.crc16,
            base,
            {
                hdr.ipv4.srcAddr,
                hdr.ipv4.dstAddr,
                hdr.ipv4.protocol,
                hdr.udp.srcPort,
                hdr.udp.dstPort
            },
            required_spine_count
        );

        output_port_register.write(0, standard_metadata.egress_spec);
    }

    action run_ECMP_TCP(in bit<2> type, in bit<32> required_spine_count) {
        bit<16> base = 0;

        if (type == LEAF_SWITCH) {
            base = (bit<16>)(HOST_NUM + 1);
        } else if (type == AGF_UP) {
            base = (bit<16>)1;
        }

        hash(
            standard_metadata.egress_spec,
            HashAlgorithm.crc16,
            base,
            {
                hdr.ipv4.srcAddr,
                hdr.ipv4.dstAddr,
                hdr.ipv4.protocol,
                hdr.tcp.srcPort,
                hdr.tcp.dstPort
            },
            required_spine_count
        );

        output_port_register.write(0, standard_metadata.egress_spec);
    }

    action run_ECMP_fallback(in bit<2> type, in bit<32> required_spine_count) {
        bit<16> base = 0;

        if (type == LEAF_SWITCH) {
            base = (bit<16>)(HOST_NUM + 1);
        } else if (type == AGF_UP) {
            base = (bit<16>)1;
        }

        hash(
            standard_metadata.egress_spec,
            HashAlgorithm.crc16,
            base,
            {
                hdr.ipv4.srcAddr,
                hdr.ipv4.dstAddr,
                hdr.ipv4.protocol
            },
            required_spine_count
        );

        output_port_register.write(0, standard_metadata.egress_spec);
    }

    table ipv4_lpm {
        key = {
            hdr.ipv4.dstAddr: lpm;
        }
        actions = {
            ipv4_forward;
            NoAction;
        }
        size = 1024;
    }

    apply {
        bit<2> type;
        bit<1> ecmp_md;

        switch_type.read(type, 0);
        ecmp_mode.read(ecmp_md, 0);

        packet_type.write(ARP_PACKET, 0);
        packet_type.write(SPINE_PATH_PACKET, 0);

        /*********************************************************************
         * Packet classification
         *********************************************************************/
        if (hdr.arp.isValid()) {
            packet_type.write(ARP_PACKET, 1);
        } else {
            ipv4_lpm.apply();

            if (
                ecmp_md == 1 &&
                (
                    (type == LEAF_SWITCH && standard_metadata.egress_spec > HOST_NUM) ||
                    (type == AGF_UP && standard_metadata.egress_spec <= SPINE_SWITCH_COUNT)
                )
            ) {
                packet_type.write(SPINE_PATH_PACKET, 1);
            }
        }

        bit<1> spine_path_packet;
        bit<1> arp_packet;

        packet_type.read(spine_path_packet, SPINE_PATH_PACKET);
        packet_type.read(arp_packet, ARP_PACKET);

        if (arp_packet == 1) {
            send_back();

        } else if (spine_path_packet == 1) {
            bit<32> required_spine_count;
            bit<48> epoch_st;
            bit<48> epoch_ln;
            bit<32> packet_th1;
            bit<32> packet_th2;
            bit<32> packet_th3;
            bit<32> packet_sz_cn;

            bit<48> timestamp = standard_metadata.ingress_global_timestamp;

            epoch_start.read(epoch_st, 0);
            epoch_length.read(epoch_ln, 0);
            packet_size_threshold1.read(packet_th1, 0);
            packet_size_threshold2.read(packet_th2, 0);
            packet_size_threshold3.read(packet_th3, 0);
            traffic.read(packet_sz_cn, 0);

            // When the measurement window expires, update the required number of spine switches.
            if (timestamp >= epoch_st + epoch_ln) {
                calculate_required_spine_switches(
                    packet_sz_cn,
                    packet_th1,
                    packet_th2,
                    packet_th3,
                    required_spine_count
                );

                spine_switches.write(0, required_spine_count);
                epoch_start.write(0, timestamp);
                packet_sz_cn = 0;
            }

            // Update the traffic counter for the current window.
            traffic.write(0, packet_sz_cn + standard_metadata.packet_length);

            // Read the latest required number of spine switches and apply ECMP.
            spine_switches.read(required_spine_count, 0);

            if (hdr.udp.isValid()) {
                run_ECMP_UDP(type, required_spine_count);
            } else if (hdr.tcp.isValid()) {
                run_ECMP_TCP(type, required_spine_count);
            } else {
                run_ECMP_fallback(type, required_spine_count);
            }
        }
    }
}

/*************************************************************************
**************** EGRESS PROCESSING ***************************************
*************************************************************************/

control MyEgress(
    inout headers hdr,
    inout metadata meta,
    inout standard_metadata_t standard_metadata
) {
    apply { }
}

/*************************************************************************
************* CHECKSUM COMPUTATION ***************************************
*************************************************************************/

control MyComputeChecksum(inout headers hdr, inout metadata meta) {
    apply {
        update_checksum(
            hdr.ipv4.isValid(),
            {
                hdr.ipv4.version,
                hdr.ipv4.ihl,
                hdr.ipv4.diffserv,
                hdr.ipv4.totalLen,
                hdr.ipv4.identification,
                hdr.ipv4.flags,
                hdr.ipv4.fragOffset,
                hdr.ipv4.ttl,
                hdr.ipv4.protocol,
                hdr.ipv4.srcAddr,
                hdr.ipv4.dstAddr
            },
            hdr.ipv4.hdrChecksum,
            HashAlgorithm.csum16
        );
    }
}

/*************************************************************************
*********************** DEPARSER *****************************************
*************************************************************************/

control MyDeparser(packet_out packet, in headers hdr) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.arp);
        packet.emit(hdr.ipv4);
        packet.emit(hdr.tcp);
        packet.emit(hdr.udp);
    }
}

/*************************************************************************
*********************** SWITCH *******************************************
*************************************************************************/

V1Switch(
    MyParser(),
    MyVerifyChecksum(),
    MyIngress(),
    MyEgress(),
    MyComputeChecksum(),
    MyDeparser()
) main;
