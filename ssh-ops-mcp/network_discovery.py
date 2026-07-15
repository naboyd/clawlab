#!/usr/bin/env python3
"""
Network discovery for ssh-ops MCP admin (vendored from hannai-ops tools/network-discovery.py).

Discovers Cisco devices via CDP, LLDP, or CIDR scan and stages results for import
into hosts.yaml.
"""

import argparse
import ipaddress
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Set

try:
    from netmiko import ConnectHandler
    from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException
except ImportError:
    ConnectHandler = None  # type: ignore[misc, assignment]
    NetmikoAuthenticationException = Exception  # type: ignore[misc, assignment]
    NetmikoTimeoutException = Exception  # type: ignore[misc, assignment]

import yaml

logger = logging.getLogger(__name__)

enable_restconf_on_device = None


class NetworkDiscovery:
    """Network discovery using CDP, LLDP, or IP range scanning."""

    def __init__(
        self,
        username: str,
        password: str,
        enable_password: Optional[str] = None,
        device_type: str = "cisco_ios",
        enable_restconf: bool = False,
        interactive: bool = True,
    ):
        """
        Initialize network discovery.

        Args:
            username: SSH username
            password: SSH password
            enable_password: Enable password (if different from password)
            device_type: Netmiko device type (default: cisco_ios)
            enable_restconf: Whether to enable RESTCONF on discovered IOS-XE devices
            interactive: Whether to prompt user for RESTCONF enablement
        """
        self.username = username
        self.password = password
        self.enable_password = enable_password or password
        self.device_type = device_type
        self.enable_restconf = enable_restconf
        self.interactive = interactive
        self.discovered_devices: Dict[str, Dict] = {}
        self.visited_ips: Set[str] = set()

    def connect_device(self, ip: str) -> Optional[ConnectHandler]:
        """
        Connect to a device via SSH.

        Args:
            ip: Device IP address

        Returns:
            Netmiko connection object or None if failed
        """
        if ConnectHandler is None:
            raise RuntimeError("netmiko is not installed")

        device = {
            "device_type": self.device_type,
            "host": ip,
            "username": self.username,
            "password": self.password,
            "secret": self.enable_password,
            "timeout": 15,
            "conn_timeout": 15,
            "auth_timeout": 15,
            "session_timeout": 20,
            "fast_cli": False,
        }

        try:
            logger.info(f"Connecting to {ip}...")
            connection = ConnectHandler(**device)
            try:
                if not connection.check_enable_mode():
                    connection.enable()
            except Exception as exc:
                logger.warning("Enable failed for %s: %s", ip, exc)
                if not connection.check_enable_mode():
                    connection.disconnect()
                    return None
            return connection
        except NetmikoAuthenticationException:
            logger.error(f"Authentication failed for {ip}")
            return None
        except NetmikoTimeoutException:
            logger.warning(f"Connection timeout for {ip}")
            return None
        except Exception as e:
            logger.error(f"Error connecting to {ip}: {e}")
            return None

    def get_device_info(self, connection: ConnectHandler, ip: str) -> Dict:
        """
        Get device information.

        Args:
            connection: Netmiko connection
            ip: Device IP

        Returns:
            Device info dictionary
        """
        try:
            # Get hostname
            hostname = connection.send_command("show running-config | include hostname")
            hostname = hostname.replace("hostname ", "").strip() if hostname else ip

            # Get version info
            version_output = connection.send_command("show version")
            
            # Parse version
            version = "unknown"
            model = "unknown"
            serial = "unknown"
            ios_type = "unknown"
            
            for line in version_output.splitlines():
                if "Version" in line and "Cisco IOS" in line:
                    version = line.split(",")[0].split("Version ")[-1].strip()
                    # Detect IOS type - check for multiple IOS-XE formats
                    line_upper = line.upper()
                    if "IOS-XE" in line_upper or "IOS XE" in line_upper or "IOSXE" in line_upper or "[IOSXE]" in line or "IOS XE" in line:
                        ios_type = "ios-xe"
                    elif "Cisco IOS Software" in line:
                        ios_type = "ios"
                elif "Model number" in line or "Model Number" in line:
                    model = line.split(":")[-1].strip()
                elif "Processor board ID" in line:
                    serial = line.split("ID")[-1].strip()
            
            # Additional check: C9300, C9800, and similar models are always IOS-XE
            if model and any(x in model.upper() for x in ["C9300", "C9800", "C9500", "C9400", "C9200", "ISR4", "ASR1"]):
                ios_type = "ios-xe"
            
            # Check for Access Points - exclude from IOS-XE inventory
            is_access_point = False
            if "AP Running Image" in version_output or "Cisco AP Software" in version_output:
                ios_type = "access-point"
                is_access_point = True
                logger.info(f"  → Detected as Cisco Access Point, will be excluded from IOS-XE inventory")
            
            # Check for AP models
            if model and any(x in model.upper() for x in ["AIR-", "AP", "CW9", "C9115", "C9117", "C9120", "C9124", "C9130", "C9166", "C9176"]):
                ios_type = "access-point"
                is_access_point = True
                logger.info(f"  → Detected as Cisco Access Point (model: {model})")
            
            # Check for ISE appliances - exclude from IOS-XE inventory
            is_ise = False
            if "Identity Services Engine" in version_output or "Cisco ISE" in version_output:
                ios_type = "ise-appliance"
                is_ise = True
                logger.info(f"  → Detected as Cisco ISE appliance, will be excluded from IOS-XE inventory")

            # Check if RESTCONF is enabled (only for IOS-XE devices)
            restconf_enabled = False
            if ios_type == "ios-xe":
                try:
                    restconf_check = connection.send_command(
                        "show platform software yang-management process"
                    )
                    if "Running" in restconf_check:
                        restconf_enabled = True
                except:
                    pass

            # Determine management capabilities
            management_type = "unknown"
            if ios_type == "access-point":
                management_type = "wlc_managed"  # Managed via WLC
            elif ios_type == "ise-appliance":
                management_type = "ise_admin"  # Managed via ISE Admin Portal
            elif restconf_enabled:
                management_type = "restconf"
            elif ios_type == "ios-xe":
                management_type = "restconf_capable"  # Can be enabled
            elif ios_type == "ios":
                management_type = "cli_ssh"  # Legacy IOS - CLI only
            
            capabilities = []
            if ios_type == "access-point":
                capabilities = ["wlc", "snmp"]
            elif ios_type == "ise-appliance":
                capabilities = ["ise-api", "ssh"]
            else:
                capabilities = ["ssh"]
                if restconf_enabled:
                    capabilities.append("restconf")
                if ios_type == "ios-xe":
                    capabilities.append("netconf")
                # Assume SNMP is available on most Cisco devices
                capabilities.append("snmp")

            device_info = {
                "ip": ip,
                "hostname": hostname,
                "version": version,
                "model": model,
                "serial": serial,
                "device_type": self.device_type,
                "ios_type": ios_type,
                "management_type": management_type,
                "restconf_enabled": restconf_enabled,
                "capabilities": capabilities,
            }

            logger.info(f"✓ Discovered: {hostname} ({ip}) - {model} - {ios_type.upper()} {version}")
            return device_info

        except Exception as e:
            logger.error(f"Error getting device info from {ip}: {e}")
            return {
                "ip": ip,
                "hostname": ip,
                "version": "unknown",
                "model": "unknown",
                "serial": "unknown",
                "device_type": self.device_type,
                "restconf_enabled": False,
            }

    def discover_via_cdp(
        self, seed_ip: str, max_hops: int = 5, visited: Optional[Set[str]] = None
    ) -> None:
        """
        Discover devices using CDP (hop by hop).

        Args:
            seed_ip: Starting device IP
            max_hops: Maximum hops to traverse
            visited: Set of already visited IPs
        """
        if visited is None:
            visited = set()

        if seed_ip in visited or max_hops <= 0:
            return

        visited.add(seed_ip)
        self.visited_ips.add(seed_ip)

        connection = self.connect_device(seed_ip)
        if not connection:
            return

        try:
            # Get device info
            device_info = self.get_device_info(connection, seed_ip)
            self.discovered_devices[seed_ip] = device_info

            # Get CDP neighbors
            logger.info(f"Getting CDP neighbors for {seed_ip}...")
            cdp_output = connection.send_command("show cdp neighbors detail")

            # Parse CDP neighbors
            neighbors = self._parse_cdp_neighbors(cdp_output)
            logger.info(f"Found {len(neighbors)} CDP neighbors")

            connection.disconnect()

            # Recursively discover neighbors
            for neighbor_ip in neighbors:
                if neighbor_ip not in visited:
                    logger.info(
                        f"Following CDP neighbor: {neighbor_ip} (hops remaining: {max_hops - 1})"
                    )
                    self.discover_via_cdp(neighbor_ip, max_hops - 1, visited)

        except Exception as e:
            logger.error(f"Error during CDP discovery from {seed_ip}: {e}")
            if connection:
                connection.disconnect()

    def _parse_cdp_neighbors(self, cdp_output: str) -> List[str]:
        """Parse CDP neighbors output and extract IP addresses."""
        neighbor_ips = []
        lines = cdp_output.splitlines()

        for i, line in enumerate(lines):
            if "IP address:" in line or "Management address" in line:
                ip = line.split(":")[-1].strip()
                # Validate IP
                try:
                    ipaddress.ip_address(ip)
                    neighbor_ips.append(ip)
                except ValueError:
                    pass

        return neighbor_ips

    def discover_via_lldp(
        self, seed_ip: str, max_hops: int = 5, visited: Optional[Set[str]] = None
    ) -> None:
        """
        Discover devices using LLDP (hop by hop).

        Args:
            seed_ip: Starting device IP
            max_hops: Maximum hops to traverse
            visited: Set of already visited IPs
        """
        if visited is None:
            visited = set()

        if seed_ip in visited or max_hops <= 0:
            return

        visited.add(seed_ip)
        self.visited_ips.add(seed_ip)

        connection = self.connect_device(seed_ip)
        if not connection:
            return

        try:
            # Get device info
            device_info = self.get_device_info(connection, seed_ip)
            self.discovered_devices[seed_ip] = device_info

            # Get LLDP neighbors
            logger.info(f"Getting LLDP neighbors for {seed_ip}...")
            lldp_output = connection.send_command("show lldp neighbors detail")

            # Parse LLDP neighbors
            neighbors = self._parse_lldp_neighbors(lldp_output)
            logger.info(f"Found {len(neighbors)} LLDP neighbors")

            connection.disconnect()

            # Recursively discover neighbors
            for neighbor_ip in neighbors:
                if neighbor_ip not in visited:
                    logger.info(
                        f"Following LLDP neighbor: {neighbor_ip} (hops remaining: {max_hops - 1})"
                    )
                    self.discover_via_lldp(neighbor_ip, max_hops - 1, visited)

        except Exception as e:
            logger.error(f"Error during LLDP discovery from {seed_ip}: {e}")
            if connection:
                connection.disconnect()

    def _parse_lldp_neighbors(self, lldp_output: str) -> List[str]:
        """Parse LLDP neighbors output and extract IP addresses."""
        neighbor_ips = []
        lines = lldp_output.splitlines()

        for line in lines:
            if "Management Address:" in line or "Management address:" in line:
                ip = line.split(":")[-1].strip()
                # Validate IP
                try:
                    ipaddress.ip_address(ip)
                    neighbor_ips.append(ip)
                except ValueError:
                    pass

        return neighbor_ips

    def discover_via_ip_range(self, ip_range: str, max_workers: int = 10) -> None:
        """
        Discover devices by scanning an IP range.

        Args:
            ip_range: IP range in CIDR notation (e.g., 192.168.1.0/24)
            max_workers: Maximum parallel connections
        """
        try:
            network = ipaddress.ip_network(ip_range, strict=False)
            logger.info(f"Scanning IP range: {ip_range} ({network.num_addresses} addresses)")

            # Use thread pool for parallel scanning
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(self._scan_single_ip, str(ip)): str(ip)
                    for ip in network.hosts()
                }

                for future in as_completed(futures):
                    ip = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        logger.debug(f"Error scanning {ip}: {e}")

        except ValueError as e:
            logger.error(f"Invalid IP range: {ip_range} - {e}")

    def _scan_single_ip(self, ip: str) -> None:
        """Scan a single IP address."""
        if ip in self.visited_ips:
            return

        self.visited_ips.add(ip)
        connection = self.connect_device(ip)

        if connection:
            try:
                device_info = self.get_device_info(connection, ip)
                self.discovered_devices[ip] = device_info
                connection.disconnect()
            except Exception as e:
                logger.debug(f"Error getting info from {ip}: {e}")
                if connection:
                    connection.disconnect()

    def enable_restconf_on_devices(self) -> None:
        """Enable RESTCONF on discovered IOS-XE devices that don't have it enabled."""
        if not self.enable_restconf or enable_restconf_on_device is None:
            return

        devices_needing_restconf = [
            (ip, device)
            for ip, device in self.discovered_devices.items()
            if not device.get("restconf_enabled", False) 
            and device.get("ios_type") == "ios-xe"
            and device.get("management_type") == "restconf_capable"
        ]

        if not devices_needing_restconf:
            logger.info("✓ All discovered devices have RESTCONF enabled or are not IOS-XE")
            return

        print(f"\n{'='*80}")
        print(f"RESTCONF CONFIGURATION")
        print(f"{'='*80}")
        print(f"Found {len(devices_needing_restconf)} IOS-XE device(s) without RESTCONF")
        print(f"{'='*80}\n")

        for ip, device_info in devices_needing_restconf:
            connection = self.connect_device(ip)
            if not connection:
                logger.warning(f"Could not reconnect to {ip} for RESTCONF configuration")
                continue

            try:
                success = enable_restconf_on_device(
                    device_info,
                    self.username,
                    self.password,
                    connection,
                    self.interactive,
                )

                if success:
                    # Update device info
                    self.discovered_devices[ip]["restconf_enabled"] = True
                    logger.info(f"✓ {device_info.get('hostname', ip)}: RESTCONF enabled")
                else:
                    logger.warning(f"⚠️  {device_info.get('hostname', ip)}: RESTCONF not enabled")

            except Exception as e:
                logger.error(f"Error enabling RESTCONF on {ip}: {e}")

            finally:
                if connection:
                    connection.disconnect()

    def export_hosts_file(self, output_file: str = "hosts.yaml", format: str = "yaml") -> None:
        """
        Export discovered devices to a hosts file.

        Args:
            output_file: Output file name
            format: Output format (yaml or json)
        """
        if not self.discovered_devices:
            logger.warning("No devices discovered. Nothing to export.")
            return

        hosts_data = {
            "discovered_devices": list(self.discovered_devices.values()),
            "total_devices": len(self.discovered_devices),
            "credentials": {
                "username": self.username,
                "password": "REPLACE_ME",  # Don't save actual password
            },
        }

        output_path = Path(output_file)

        if format == "yaml":
            with open(output_path, "w") as f:
                yaml.dump(hosts_data, f, default_flow_style=False, sort_keys=False)
            logger.info(f"✓ Exported {len(self.discovered_devices)} devices to {output_file}")
        elif format == "json":
            with open(output_path, "w") as f:
                json.dump(hosts_data, f, indent=2)
            logger.info(f"✓ Exported {len(self.discovered_devices)} devices to {output_file}")

        # Calculate statistics
        total_devices = len(self.discovered_devices)
        iosxe_devices = sum(1 for d in self.discovered_devices.values() if d.get('ios_type') == 'ios-xe')
        ios_devices = sum(1 for d in self.discovered_devices.values() if d.get('ios_type') == 'ios')
        access_points = sum(1 for d in self.discovered_devices.values() if d.get('ios_type') == 'access-point')
        ise_appliances = sum(1 for d in self.discovered_devices.values() if d.get('ios_type') == 'ise-appliance')
        restconf_enabled = sum(1 for d in self.discovered_devices.values() if d.get('restconf_enabled'))
        restconf_capable = sum(1 for d in self.discovered_devices.values() if d.get('management_type') == 'restconf_capable')
        cli_only = sum(1 for d in self.discovered_devices.values() if d.get('management_type') == 'cli_ssh')
        
        # Print summary
        print("\n" + "=" * 80)
        print(f"DISCOVERY SUMMARY")
        print("=" * 80)
        print(f"Total devices discovered: {total_devices}")
        print(f"  - IOS-XE devices: {iosxe_devices}")
        print(f"  - Legacy IOS devices: {ios_devices}")
        print(f"  - Access Points (excluded): {access_points}")
        print(f"  - ISE Appliances (excluded): {ise_appliances}")
        print(f"  - RESTCONF enabled: {restconf_enabled}")
        print(f"  - RESTCONF capable (not enabled): {restconf_capable}")
        print(f"  - CLI/SSH only (legacy): {cli_only}")
        print(f"\nOutput file: {output_file}")
        print("=" * 80)
        print("\nDiscovered Devices:")
        print(f"{'Hostname':<30} {'IP':<15} {'Model':<20} {'Type':<10} {'Management'}")
        print("-" * 80)
        for device in self.discovered_devices.values():
            ios_type = device.get('ios_type', 'unknown')
            mgmt_type = device.get('management_type', 'unknown')
            
            # Format ios_type for display
            if ios_type == 'ios-xe':
                ios_type_display = 'IOS-XE'
            elif ios_type == 'ios':
                ios_type_display = 'IOS'
            elif ios_type == 'access-point':
                ios_type_display = 'AP'
            elif ios_type == 'ise-appliance':
                ios_type_display = 'ISE'
            else:
                ios_type_display = ios_type.upper()
            
            if device.get('restconf_enabled'):
                mgmt_status = "✓ RESTCONF"
            elif mgmt_type == 'restconf_capable':
                mgmt_status = "⚠ RESTCONF-Ready"
            elif mgmt_type == 'cli_ssh':
                mgmt_status = "⚙ CLI/SSH Only"
            elif mgmt_type == 'wlc_managed':
                mgmt_status = "📡 WLC-Managed"
            elif mgmt_type == 'ise_admin':
                mgmt_status = "🔐 ISE Admin"
            else:
                mgmt_status = "? Unknown"
            
            print(f"{device['hostname']:<30} {device['ip']:<15} {device['model']:<20} {ios_type_display:<10} {mgmt_status}")
        print("=" * 80)


def run_discovery(
    *,
    method: str,
    username: str,
    password: str,
    seed: str = "",
    ip_range: str = "",
    enable_password: Optional[str] = None,
    max_hops: int = 5,
    max_workers: int = 10,
) -> List[Dict]:
    """
    Run discovery and return device dicts (for MCP admin import).

    method: cdp | lldp | range
    """
    if ConnectHandler is None:
        raise RuntimeError("netmiko is not installed")

    discovery = NetworkDiscovery(
        username=username,
        password=password,
        enable_password=enable_password,
        enable_restconf=False,
        interactive=False,
    )

    if method == "cdp":
        if not seed:
            raise ValueError("Seed IP is required for CDP discovery")
        discovery.discover_via_cdp(seed, max_hops=max_hops)
    elif method == "lldp":
        if not seed:
            raise ValueError("Seed IP is required for LLDP discovery")
        discovery.discover_via_lldp(seed, max_hops=max_hops)
    elif method == "range":
        target = ip_range or seed
        if not target:
            raise ValueError("IP range (CIDR) is required for range discovery")
        discovery.discover_via_ip_range(target, max_workers=max_workers)
    else:
        raise ValueError(f"Unknown discovery method: {method}")

    return list(discovery.discovered_devices.values())


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Network Discovery Tool for Enterprise Identity Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # CDP discovery from seed device
  python network-discovery.py --seed 192.168.1.1 --method cdp --username admin --password Cisco123!
  
  # IP range scan
  python network-discovery.py --range 192.168.1.0/24 --username admin --password Cisco123!
  
  # LLDP discovery
  python network-discovery.py --seed 192.168.1.1 --method lldp --username admin --password Cisco123!
  
  # Export to JSON
  python network-discovery.py --seed 192.168.1.1 --method cdp --username admin --password Cisco123! --output hosts.json --format json
        """,
    )

    parser.add_argument("--seed", help="Seed device IP address for CDP/LLDP discovery")
    parser.add_argument(
        "--range", help="IP range for scanning (CIDR notation, e.g., 192.168.1.0/24)"
    )
    parser.add_argument(
        "--method",
        choices=["cdp", "lldp", "range"],
        default="cdp",
        help="Discovery method (default: cdp)",
    )
    parser.add_argument("--username", required=True, help="SSH username")
    parser.add_argument("--password", required=True, help="SSH password")
    parser.add_argument("--enable-password", help="Enable password (if different from SSH password)")
    parser.add_argument(
        "--max-hops", type=int, default=5, help="Maximum hops for CDP/LLDP discovery (default: 5)"
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=10,
        help="Maximum parallel connections for IP range scan (default: 10)",
    )
    parser.add_argument(
        "--output",
        default="hosts.yaml",
        help="Output file name (default: hosts.yaml)",
    )
    parser.add_argument(
        "--format",
        choices=["yaml", "json"],
        default="yaml",
        help="Output format (default: yaml)",
    )
    parser.add_argument(
        "--device-type",
        default="cisco_ios",
        help="Netmiko device type (default: cisco_ios)",
    )
    parser.add_argument(
        "--enable-restconf",
        action="store_true",
        help="Automatically enable RESTCONF on discovered IOS-XE devices (with prompts)",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Skip prompts and enable RESTCONF on all eligible devices automatically",
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.seed and not args.range:
        parser.error("Either --seed or --range must be specified")

    if args.method in ["cdp", "lldp"] and not args.seed:
        parser.error(f"--seed is required for {args.method} discovery")

    if args.method == "range" and not args.range:
        parser.error("--range is required for range discovery")

    # Create discovery instance
    discovery = NetworkDiscovery(
        username=args.username,
        password=args.password,
        enable_password=args.enable_password,
        device_type=args.device_type,
        enable_restconf=args.enable_restconf,
        interactive=not args.no_interactive,
    )

    print("\n" + "=" * 80)
    print("NETWORK DISCOVERY TOOL")
    print("=" * 80)
    print(f"Method: {args.method.upper()}")
    if args.seed:
        print(f"Seed Device: {args.seed}")
    if args.range:
        print(f"IP Range: {args.range}")
    print(f"Username: {args.username}")
    print(f"Output: {args.output} ({args.format})")
    print("=" * 80 + "\n")

    # Run discovery
    try:
        if args.method == "cdp":
            discovery.discover_via_cdp(args.seed, max_hops=args.max_hops)
        elif args.method == "lldp":
            discovery.discover_via_lldp(args.seed, max_hops=args.max_hops)
        elif args.method == "range":
            discovery.discover_via_ip_range(args.range, max_workers=args.max_workers)

        # Enable RESTCONF on devices if requested
        if args.enable_restconf:
            discovery.enable_restconf_on_devices()

        # Export results
        discovery.export_hosts_file(output_file=args.output, format=args.format)

    except KeyboardInterrupt:
        logger.info("\nDiscovery interrupted by user")
        if discovery.discovered_devices:
            logger.info("Exporting partial results...")
            discovery.export_hosts_file(output_file=args.output, format=args.format)
    except Exception as e:
        logger.error(f"Discovery failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
