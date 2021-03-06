#!/usr/bin/env python

# import datetime		# time stamp
import os			# check sudo
import netaddr		# ipv4/6 addresses, address space: 192.168.5.0/24, pinger
import pprint as pp # display info
import commands		# arp-scan
import requests		# mac api
import socket		# get hostname and pinger
import sys			# get platform (linux or linux2 or darwin)
import argparse     # handle command line
import json         # save data
import subprocess	# use commandline
import random		# Pinger uses it when creating ICMP packets

# from awake import wol # wake on lan
from lib import *
from getvendor import *
from gethostname import *

####################################################


class ArpScan(Commands):
	def scan(self,dev):
		"""
		brew install arp-scan

		arp-scan -l -I en1
		 -l use local networking info
		 -I use a specific interface

		 return {mac: mac_addr, ipv4: ip_addr}

		 Need to invest the time to do this myself w/o using commandline
		"""
		arp = self.getoutput("arp-scan -l -I %s"%(dev))
		a = arp.split('\n')
		print a
		ln = len(a)

		d = []
		# for i in range(2,ln-3):
		for i in range(2,ln-4):
			b = a[i].split()
			d.append( {'mac': b[1],'ipv4': b[0]} )

		return d

class IP(object):
	"""
	Gets the IP and MAC addresses for the localhost
	"""
	ip = 'x'
	mac = 'x'

	def __init__(self):
		"""Everything is done in init(), don't call any methods, just access ip or mac."""
		self.mac = self.getHostMAC()
		self.ip = self.getHostIP()

	def getHostIP(self):
		"""
		Need to get the localhost IP address
		in: none
		out: returns the host machine's IP address
		"""
		host_name = socket.gethostname()
		if '.local' not in host_name: host_name = host_name + '.local'
		ip = socket.gethostbyname(host_name)
		return ip

	def getHostMAC(self,dev='en1'):
		"""
		Major flaw of NMAP doesn't allow you to get the localhost's MAC address, so this
		is a work around.
		in: none
		out: string of hex for MAC address 'aa:bb:11:22..' or empty string if error
		"""
		# this doesn't work, could return any network address (en0, en1, bluetooth, etc)
		#return ':'.join(re.findall('..', '%012x' % uuid.getnode()))
		mac = commands.getoutput("ifconfig " + dev + "| grep ether | awk '{ print $2 }'")

		# double check it is a valid mac address
		if len(mac) == 17 and len(mac.split(':')) == 6: return mac

		# nothing found
		return ''

class Pinger(object):
	"""
	Determine if host is up.

	ArpScan is probably better ... get MAC info from it

	this uses netaddr and random ... can remove if not using
	"""
	def __init__(self):
		comp = IP()
		self.sniffer = socket.socket(socket.AF_INET, socket.SOCK_RAW,socket.IPPROTO_ICMP)
		self.sniffer.bind((comp.ip,1))
		self.sniffer.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
		self.sniffer.settimeout(1)

		self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

	def createICMP(self,msg):
		echo = dpkt.icmp.ICMP.Echo()
		echo.id = random.randint(0, 0xffff)
		echo.seq = random.randint(0, 0xffff)
		echo.data = msg

		icmp = dpkt.icmp.ICMP()
		icmp.type = dpkt.icmp.ICMP_ECHO
		icmp.data = echo
		return str(icmp)

	def ping(self,ip):
		#print 'Ping',ip
		try:
			msg = self.createICMP('test')
			self.udp.sendto(msg,(ip, 10))
		except socket.error as e:
			print e,'ip:',ip

		try:
			self.sniffer.settimeout(0.01)
			raw_buffer = self.sniffer.recvfrom(65565)[0]
		except socket.timeout:
			return ''

		return raw_buffer

	def scanNetwork(self,subnet):
		"""
		For our scanner, we are looking for a type value of 3 and a code value of 3, which
		are the Destination Unreachable class and Port Unreachable errors in ICMP messages.
		"""
		net = {}

		# continually read in packets and parse their information
		for ip in netaddr.IPNetwork(subnet).iter_hosts():
			raw_buffer = self.ping(str(ip))

			if not raw_buffer:
				continue

			ip = dpkt.ip.IP(raw_buffer)
			src = socket.inet_ntoa(ip.src)
			# dst = socket.inet_ntoa(ip.dst)
			icmp = ip.data

			# ICMP_UNREACH = 3
			# ICMP_UNREACH_PORT = 3
			# type 3 (unreachable) code 3 (destination port)
			# type 5 (redirect) code 1 (host) - router does this
			if icmp.type == dpkt.icmp.ICMP_UNREACH and icmp.code == dpkt.icmp.ICMP_UNREACH_PORT:
				net[src] = 'up'

		return net



class PortScanner(object):
	"""
	Scans a single host and finds all open ports with in its range (1 ... n).
	"""
	def __init__(self,ports=range(1,1024)):
		self.ports = ports

	def openPort(self,ip,port):
		try:
			self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			socket.setdefaulttimeout(0.01)
			self.sock.connect((ip, port))
			return True
# 		except KeyboardInterrupt:
# 			exit("You pressed Ctrl+C, killing PortScanner")
		except:
			self.sock.close()
			return False

	def scan(self,ip):
		tcp = []

		for port in self.ports:
			good = self.openPort(ip,port)
			if good:
				svc = ''
				try:
					svc = socket.getservbyport(port).strip()
				except:
					svc = 'unknown'
				tcp.append( (port,svc) )
#			if banner and good:
#				ports[str(port)+'_banner'] = self.getBanner(ip,port)

		self.sock.close()
		return tcp

class ActiveMapper(object):
	"""
	Actively scans a network (arp-scan) and then pings each host for open ports.
	"""
	def __init__(self,ports=range(1,1024)):
		self.ports = ports

	def scan(self,dev):
		"""
		arpscan - {'mac': mac,'ipv4': ip}

		in: device for arp-scan to use (ie. en1)
		out: [host1,host2,...]
		      where host is: {'mac': '34:62:98:03:b6:b8', 'hostname': 'Airport-New.local', 'ipv4': '192.168.18.76' 'tcp':[(port,svc),...)]}
		"""
		arpscanner = ArpScan()
		arp = arpscanner.scan(dev)
		print 'Found '+str(len(arp))+' hosts'

		ports = []
		portscanner = PortScanner(self.ports)
		counter = 0
		for host in arp:
			# find the hostname
			host['hostname'] = GetHostName( host['ipv4'] ).name

			# get vendor info
			host['vendor'] = MacLookup(host['mac']).vendor

			# scan the host for open tcp ports
			p = portscanner.scan( host['ipv4'] )
			host['tcp'] = p

			counter+=1
# 			print 'host['+str(counter)+']: ' # need something better
			print 'host[%d]: %s %s with %d open ports'%(counter,host['hostname'],host['ipv4'],len(host['tcp']))

		return arp


########################################################

def handleArgs():
	description = """A simple active network recon program. It conducts an arp
	ping to get MAC addresses and IPv4 addresses. Avahi or dig are used to get host
	names. It also scans for open ports on each host. The information is printed to the
	screen, saved to a json file, or sent to another computer

	examples:

		sudo netscan -i en1 -s network.json -r 5000
		sudo netscan -j http://localhost:9000/json
	"""
	parser = argparse.ArgumentParser(description)
# 	parser.add_argument('-j', '--json', help='name of json file', default='')
# 	parser.add_argument('-w', '--webpage', help='name of webpage', default='')
# 	parser.add_argument('-c', '--pcap', help='pcap file name', default='')
# 	parser.add_argument('-a', '--active', help='scan active', action='store_true', default=False)
# 	parser.add_argument('-p', '--passive', help='scan passive, how many packets to look for', default=0)
# 	parser.add_argument('-n', '--network', help='network: 10.1.1.0/24 or 10.1.1.1-10', default='192.168.1.0/24')
# 	parser.add_argument('-y', '--yaml', help='yaml file to store network in', default='./network.yaml')
	parser.add_argument('-i', '--interface', help='network interface to use', default='en1')
# 	parser.add_argument('-d', '--display', help='print to screen', action='store_true', default=False)
	parser.add_argument('-s', '--save', help='save output to a file', default='')
	parser.add_argument('-r', '--range', help='range of active port scan: 1..n', default='1024')
	args = vars(parser.parse_args())

	return args

def main():
	# handle inputs
	args = handleArgs()

	# check for sudo/root privileges
	if os.geteuid() != 0:
		exit('You need to be root/sudo ... exiting')

	try:
		am = ActiveMapper(range(1,int(args['range'])))
		hosts = am.scan(args['interface'])
		pp.pprint( hosts )

		# save file
		if args['save']:
			with open(args['save'], 'w') as fp:
				json.dump(hosts, fp)

		return hosts
	except KeyboardInterrupt:
		exit('You hit ^C, exiting PassiveMapper ... bye')
	except:
		print "Unexpected error:", sys.exc_info()
		exit('bye ... ')


if __name__ == "__main__":
	main()
