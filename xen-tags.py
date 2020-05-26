#!/usr/bin/env python3

import XenAPI
import atexit
import os
import sys

class XenServer:
    def __init__(self, xenserver_host=None, xenserver_user='', xenserver_password=''):
        """
        xenserver_host: The FQDN of XenServer
        xenserver_user: A XenServer user
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

    def add_tag(self, vm_name_label, tag_name):
        try:
            vm = self.session.xenapi.VM.get_by_name_label(vm_name_label)[0]
            self.session.xenapi.VM.add_tags(vm, tag_name)
        except XenAPI.Failure as e:
            print('[ERROR]: {}'.format(e))
            return False

        return True

    def remove_tag(self, vm_name_label, tag_name):
        try:
            vm = self.session.xenapi.VM.get_by_name_label(vm_name_label)[0]
            self.session.xenapi.VM.remove_tags(vm, tag_name)
        except XenAPI.Failure as e:
            print('[ERROR]: {}'.format(e))
            return False

        return True


def get_credentials():
    xen_host = os.environ.get('XENSERVER_HOST', '_none_')
    xen_user = os.environ.get('XENSERVER_USER', '_none_')
    xen_pass = os.environ.get('XENSERVER_PASSWORD', '_none_')

    # error if the environment variables were not supplied
    if xen_host == '_none_' or xen_user == '_none_' or xen_pass == '_none_':
        exit(1)

    # return the credentials tuple
    return (xen_host, xen_user, xen_pass)

if __name__ == '__main__':
    (hostname, user, password) = get_credentials()
    xs = XenServer(hostname, user, password)
    if sys.argv[1] == 'add':
        if xs.add_tag(sys.argv[2], sys.argv[3]):
            exit()
    elif sys.argv[1] == 'rm':
        if xs.remove_tag(sys.argv[2], sys.argv[3]):
            exit()
    exit(1)
