#!/usr/bin/env python

#   This file is part of Ansible XEN Inventory.
#
# The Ansible XEN Inventory script is a derivative work of
# XEN Ansible Inventory by Michaul Angelos Simos <www.asimos.tk>
#   https://github.com/mikesimos/xen_ansible_inventory
#
# to allow for using AWX credential management instead
# of .ini configuration.
#
# Modified by:
# Rob Schmidt <rob@robwschmidt.com>

"""
Python script for listing Xen Server Virtual Machines for Ansible inventory
"""

import atexit
from time import time
import os
import errno
import XenAPI

from json import dumps, dump, load
import argparse

class XenServer:
    """
    XenServer acts as an explicit wrapper class over XenAPI XML-RPC API,
    implementing listing (list_inventory) of XenServer resident, running VMs.
    """
    def __init__(self, xenserver_host=None, xenserver_user='', xenserver_password=''):
        """
        xenserver_host: The FQDN of XenServer
        xenserver_user: A XenServer (read only) user
        xenserver_password: XenServer user password
        """
        try:
            session = XenAPI.Session('http://{}'.format(xenserver_host))
            session.xenapi.login_with_password(xenserver_user, xenserver_password)
        except Exception as error:
            print("Could not connect to XenServer: {}".format(error))
            sys.exit(1)
        self.session = session
        atexit.register(session.xenapi.session.logout)

    def list_inventory(self):
        """
        Lists inventory of XenServer virtual machines, grouped by their network names.
        This allows a vm to be reported in multiple groups (result of having multiple NICs)

        Returns an Ansible pluggable dynamic inventory, as a Python json serializable dictionary.
        """
        # do not add these tags as a nested group in AWX
        root_tags = ['production', 'nonproduction', 'linux', 'windows']

        try:
            all_vms = self.session.xenapi.VM.get_all()
            inventory = {
                "all": {"children": ["ungrouped"]}, 
                "ungrouped": {"hosts": []},
                "_meta": { "hostvars": {} }
            }

            for root_tag in root_tags:
                inventory[root_tag] = {'children': []}
                inventory['all']['children'].append(root_tag)

            for vm in all_vms:
                record = self.session.xenapi.VM.get_record(vm)
                # avoid processing dom0 or templates as running VMs within the inventory
                if record["is_control_domain"] or record["is_a_template"]:
                    continue

                for i in record['VIFs']:
                    # add the VM to the groups defined in tags
                    tags = self.session.xenapi.VM.get_tags(vm)
                    if len(tags) > 0:
                        for tag in tags:
                            if tag not in inventory.keys():
                                group = {'children': [], 'hosts': []}
                            else:
                                group = inventory.get(tag)

                            if tag not in root_tags:         # if the current tag isnt prod/nonprod
                                group['hosts'].append(record['name_label'])
                            
                                for new_root in tags:
                                    if new_root in root_tags:
                                        if tag not in inventory[new_root]['children']:
                                            inventory[new_root]['children'].append(tag)

                            inventory[tag] = group
                    else:
                        inventory['ungrouped']['hosts'].append(record['name_label'])

                    # xen_tools don't provide an API reporting FQDN / hostname.
                    # Thus we need to define ansible_host with the reported IP of a vm,
                    # since using a vm name, and enforcing naming conventions through XenCenter
                    #  could cause more trouble...
                    # Let's use first assigned IP.
                    network_gm = self.session.xenapi.VM_guest_metrics.get_record(record['guest_metrics']).get('networks', {})
                    # sometimes the vif device numbering can be incorrect, so get the first ipv4 dict entry as primary IP
                    ip = None
                    for key in network_gm.keys():
                        value = network_gm[key]
                        if value.find(':') != -1:
                            continue
                        ip = value

                    # add to the host vars and put into inventory
                    host_vars = {"ansible_host": ip}
                    inventory["_meta"]["hostvars"][record['name_label']] = host_vars

            return inventory
        except XenAPI.Failure as e:
            print("[Error] : " + str(e))
            exit(1)

    def list_and_save(self, cache_path):
        """
        Cache the inventory
        cache_path: A path for caching inventory list data.
        """
        data = self.list_inventory()
        with open(cache_path, 'w') as fp:
            dump(data, fp)
        return data

    def cached_inventory(self, cache_path=None, cache_ttl=100, refresh=False):
        """
        Wrapper method implementing caching functionality over list_inventory.

        cache_path: A path for caching inventory list data. Quite a necessity for large environments.
        cache_ttl: Integer Inventory list data cache Time To Live. Expiration period.
        refresh: Setting this True, triggers a cache refresh. Fresh data is fetched.
        
        Returns an Ansible pluggable dynamic inventory, as a Python json serializable dictionary.
        """
        if refresh:
            return self.list_and_save(cache_path)
        else:
            if os.path.isfile(cache_path) and time() - os.stat(cache_path).st_mtime < cache_ttl:
                try:
                    with open(cache_path) as f:
                        data = load(f)
                        return data
                except (ValueError, IOError):
                    return self.list_and_save(cache_path)
            else:
                if not os.path.exists(os.path.dirname(cache_path)):
                    try:
                        if cache_path:
                            os.makedirs(os.path.dirname(cache_path))
                        else:
                            raise OSError("cache_path not defined: {}".format(cache_path))
                    # handle race condition
                    except OSError as exc:
                        if exc.errno == errno.EACCES:
                            print("{}".format(str(exc)))
                            exit(1)
                        elif exc.errno != errno.EEXIST:
                            raise
                return self.list_and_save(cache_path)


    def cached_host(self, host, cache_path=None, cache_ttl=100, refresh=False):
        """
        Wrapper method implementing caching functionality over list_inventory.
        
        cache_path: A path for caching inventory list data. Quite a necessity for large environments.
        cache_ttl: Integer Inventory list data cache Time To Live. Expiration period.
        refresh: Setting this True, triggers a cache refresh. Fresh data is fetched.
        
        Returns an Ansible host in an inventory.
        """
        data = self.cached_inventory(cache_path, cache_ttl, refresh)
        vm_data = {}
        for vm_name in data['_meta']['hostvars'].keys():
            for var in data['_meta']['hostvars'][vm_name].keys():
                vm_data[var] = data['_meta']['hostvars'][vm_name][var]

        return vm_data


def get_credentials():
    cache_path = '/tmp/xenserver_inv.cache'
    cache_ttl = 10
    xen_host = os.environ.get('XENSERVER_HOST', '_none_')
    xen_user = os.environ.get('XENSERVER_USER', '_none_')
    xen_pass = os.environ.get('XENSERVER_PASSWORD', '_none_')

    refresh = os.environ.get('XENSERVER_CACHE_REFRESH', False)

    # error if the environment variables were not supplied
    if xen_host == '_none_' or xen_user == '_none_' or xen_pass == '_none_' or refresh == '_none_':
        exit(1)

    # return the credentials tuple
    return (cache_path, cache_ttl, xen_host, xen_user, xen_pass, refresh)


def parse_args():
    parser = argparse.ArgumentParser(description='Get list of VMs within XenServer')
    parser.add_argument('--list', action='store_true', help='List all VMs running in XenServer')
    parser.add_argument('--host', help='Return information about a running guest VM')
    args = parser.parse_args()

    if not args.list and not args.host:
        args.list = True
    
    return args


def main():
    args = parse_args()

    (cache_path, cache_ttl, xen_host, xen_user, xen_pass, refresh) = get_credentials()

    # - Override with arg parameters if defined
    x = XenServer(xen_host, xen_user, xen_pass)
    if args.list:
        data = x.cached_inventory(cache_path=cache_path, cache_ttl=cache_ttl, refresh=refresh)
    elif args.host:
        data = x.cached_host(host=args.host, cache_path=cache_path, cache_ttl=cache_ttl, refresh=refresh)
    print (dumps(data, indent=2))


if __name__ == "__main__":
    main()
