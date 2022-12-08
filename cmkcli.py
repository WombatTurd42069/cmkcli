#!/usr/bin/env python3

# coding=utf-8

"""

This is free and unencumbered software released into the public domain.

Anyone is free to copy, modify, publish, use, compile, sell, or
distribute this software, either in source code form or as a compiled
binary, for any purpose, commercial or non-commercial, and by any
means.

In jurisdictions that recognize copyright laws, the author or authors
of this software dedicate any and all copyright interest in the
software to the public domain. We make this dedication for the benefit
of the public at large and to the detriment of our heirs and
successors. We intend this dedication to be an overt act of
relinquishment in perpetuity of all present and future rights to this
software under copyright law.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.

"""

"""

    check-mk-cli - command line management of Check_MK

    2019-04-20 - Version 2.1
    2021-01-06 - Version 2.2 (for Check_MK 2.0+)

"""

from datetime import datetime
from tabulate import tabulate
from html.parser import HTMLParser

import re
import sys
import pwd
import socket
import colored
import fnmatch
import getpass
import argparse
import requests
import textwrap
import urllib.parse

if sys.version_info < (3, 0):
    raise RuntimeError('Python 2 is unsupported. Use Python 3.')

CHECK_MK_BASE_URL = ''
CHECK_MK_API_USER = ''
CHECK_MK_API_SECRET = ''

DOWNTIME_DEFAULT_MINUTES = 30

IP_REGEXP = r'^\b(?:\d{1,3}\.){3}\d{1,3}\b$'


class CheckMk:

    def __init__(self):
        self.print_colour = True

    def set_colour(self, colour):
        self.print_colour = colour

    def request_view(self, url):
        return requests.get('{}view.py?_username={}&_secret={}{}'.format(CHECK_MK_BASE_URL, CHECK_MK_API_USER, CHECK_MK_API_SECRET, url))

    def request_wato(self, url):
        return requests.get('{}wato.py?_username={}&_secret={}{}'.format(CHECK_MK_BASE_URL, CHECK_MK_API_USER, CHECK_MK_API_SECRET, url))

    def request_webapi(self, url):
        return requests.get('{}webapi.py?_username={}&_secret={}{}'.format(CHECK_MK_BASE_URL, CHECK_MK_API_USER, CHECK_MK_API_SECRET, url))

    def request_webapi_post(self, url, post):
        return requests.post('{}webapi.py?_username={}&_secret={}{}'.format(CHECK_MK_BASE_URL, CHECK_MK_API_USER, CHECK_MK_API_SECRET, url), post)

    def downtime_bulk_add(self, hostname, service, lazy, comment, minutes, period):
        if lazy:
            match_string = '{}'
        else:
            match_string = '*{}*'
        user = get_username()
        if minutes and not comment:
            comment = 'downtime for {0} minutes'.format(minutes)
        if period and not comment:
            comment = 'downtime from {0} to {1}'.format(period[0], period[1])
        user_comment = '{}: {}'.format(user, comment)
        if minutes and period:
            raise ValueError('error: both a duration and a date range was specified for downtime…')
        hosts = self.get_hosts()
        for i in hosts:
            if fnmatch.fnmatchcase(i, match_string.format(hostname)):
                if minutes:
                    self.downtime_add_minutes(i, service, user_comment, minutes)
                if period:
                    self.downtime_add_period(i, service, user_comment, period)

    def downtime_base_url(self, hostname, comment):
        return '&output_format=JSON&_do_confirm=yes&_transid=-1&_do_actions=yes&host={}&site=&_down_comment={}'.format(urllib.parse.quote(hostname, safe=''), urllib.parse.quote(comment, safe=''))

    def downtime_add_minutes(self, hostname, service, comment, minutes):
        url = self.downtime_base_url(hostname, comment)
        url = url + '&_down_from_now=From+now+for&_down_minutes={}'.format(minutes)

        if service:
            url = url + '&view_name=service&service={0}'.format(urllib.parse.quote(service, safe=''))
        else:
            url = url + '&view_name=hoststatus'
        r = self.request_view(url)
        if 'MESSAGE: Successfully sent' in r.text:
            if service:
                print('service {} on host {} successfully placed in downtime for {} minutes'.format(self.str_green(service), self.str_green(hostname), minutes))
            else:
                print('host {} successfully placed in downtime for {} minutes'.format(self.str_green(hostname), minutes))

    def downtime_add_period(self, hostname, service, comment, period):
        url = self.downtime_base_url(hostname, comment)
        url = url + '&_down_custom=Custom+time+range&_down_from_date={}&_down_from_time={}&_down_to_date={}&_down_to_time={}'.format(period[0].date(), urllib.parse.quote(period[0].strftime('%H:%M'), safe=''), period[1].date(), urllib.parse.quote(period[1].strftime('%H:%M'), safe=''))

        if service:
            url = url + '&view_name=service&service={0}'.format(urllib.parse.quote(service, safe=''))
        else:
            url = url + '&view_name=hoststatus'
        r = self.request_view(url)
        if 'MESSAGE: Successfully sent' in r.text:
            downtime_date_format = '%Y-%m-%d %H:%M'
            downtime_period = 'from {} to {}'.format(period[0].strftime(downtime_date_format), period[1].strftime(downtime_date_format))
            if service:
                print('service {} on host {} successfully placed in downtime {}'.format(self.str_green(service), self.str_green(hostname), downtime_period))
            else:
                print('host {} successfully placed in downtime {}'.format(self.str_green(hostname), downtime_period))

    def downtime_bulk_remove(self, hostname, service, lazy):
        if lazy:
            match_string = '{}'
        else:
            match_string = '*{}*'
        hosts = self.get_hosts()
        for i in hosts:
            if fnmatch.fnmatchcase(i, match_string.format(hostname)):
                self.downtime_remove(i, service)

    def downtime_remove(self, hostname, service):
        url = '&output_format=JSON&_do_confirm=yes&_transid=-1&_do_actions=yes&host={}&site=&_remove_downtimes=Remove'.format(urllib.parse.quote(hostname, safe=''))
        if service:
            url = url + '&view_name=downtimes_of_service&service={0}'.format(urllib.parse.quote(service, safe=''))
        else:
            url = url + '&view_name=downtimes_of_host'
        r = self.request_view(url)
        if 'MESSAGE: Successfully sent' in r.text:
            if service:
                print('service {} on host {} successfully removed from downtime'.format(self.str_green(service), self.str_green(hostname)))
            else:
                print('host {} successfully removed from downtime '.format(self.str_green(hostname)))
        else:
            if service:
                print('could not remove downtime on service {} on host {}. it probably was not in downtime to begin with.'.format(self.str_red(service), self.str_red(hostname)))
            else:
                print('could not remove downtime on host {}. it probably was not in downtime to begin with.'.format(self.str_red(hostname)))

    def downtime_list(self, hosts, services):
        r = self.request_view('&view_name=downtimes&output_format=json').json()
        downtimes_headers = r[0]
        r.pop(0)
        if len(r) == 0:
            print('there are no hosts or services in downtime')
            return
        for index, item in enumerate(downtimes_headers):
            downtimes_headers[index] = self.str_bold(item)
        host_downtimes_headers = list(downtimes_headers)
        service_downtimes_headers = list(downtimes_headers)
        host_downtimes = []
        service_downtimes = []
        for i in r:
            if i[1] == '':  # if service is blank, it's a host
                host_downtimes.append(i)
            else:
                service_downtimes.append(i)
        del host_downtimes_headers[1]
        del host_downtimes_headers[1]
        del host_downtimes_headers[5]
        del host_downtimes_headers[5]
        del host_downtimes_headers[5]
        for row in host_downtimes:
            del row[1]  # service_description
            del row[1]  # downtime_origin
            del row[5]  # downtime_fixed
            del row[5]  # downtime_duration
            del row[5]  # downtime_recurring (not supported in Check_MK Raw Edition)
        del service_downtimes_headers[2]
        del service_downtimes_headers[6]
        del service_downtimes_headers[6]
        del service_downtimes_headers[6]
        for row in service_downtimes:
            del row[2]  # downtime_origin
            del row[6]  # downtime_fixed
            del row[6]  # downtime_duration
            del row[6]  # downtime_recurring (not supported in Check_MK Raw Edition)
        if hosts and not services or not hosts and not services or hosts and services:
            if len(host_downtimes) > 0:
                print()
                print(self.str_bold('host downtimes'))
                print()
                print(tabulate(host_downtimes, headers=host_downtimes_headers))
        if services and not hosts or not hosts and not services or hosts and services:
            if len(service_downtimes) > 0:
                print()
                print(self.str_bold('service downtimes'))
                print()
                print(tabulate(service_downtimes, headers=service_downtimes_headers))
        print()

    def refresh_bulk(self, hostname, confirm, activate, lazy):
        hosts = self.get_hosts()
        if lazy:
            match_string = '{}'
        else:
            match_string = '*{}*'
        refresh_hosts = []
        for i in hosts:
            if fnmatch.fnmatchcase(i, match_string.format(hostname)):
                refresh_hosts.append(i)
        if len(refresh_hosts) == 0:
            print('no hosts found matching {}'.format(hostname))
            sys.exit(0)
        if confirm:
            print()
            for i in refresh_hosts:
                print(self.str_green(i))
            print()
            if not yes_no('do you wish to proceed with the configuration refresh of these hosts?'):
                return
        for i in refresh_hosts:
            self.refresh(i)
        if activate:
            self.activate()

    def refresh(self, hostname):
        print('refreshing host check configuration on {}: '.format(self.str_green(hostname)), end='')
        r = self.request_webapi('&action=discover_services&mode=refresh&hostname={}'.format(hostname)).json()['result']
        if 'Service discovery successful' in r:
            print(r.lower())
        else:
            print('service discovery unsuccessful. ensure that {} exists, it is reachable via the Internet, and is not disabled in WATO'.format(self.str_red(hostname)))

    def unknown_refresh(self, confirm, activate):
        problems = self.get_service_problems(False, None)
        refresh_hosts = set()
        for alert in problems:
            if alert[0] == 'UNKN':
                refresh_hosts.add(alert[1])
        if len(refresh_hosts) == 0:
            print('there are currently no services in the \'Unknown\' state')
            return
        refresh_hosts = sorted(refresh_hosts)
        if confirm:
            print()
            for i in refresh_hosts:
                print(self.str_green(i))
            print()
            if not yes_no('do you wish to proceed with the refresh of these hosts?'):
                return
        for i in refresh_hosts:
            self.refresh(i)
        if activate:
            self.activate()

    def unmonitored_refresh(self, confirm, activate):
        problems = self.get_service_problems(False, None)
        refresh_hosts = set()
        for alert in problems:
            if alert[2] == 'Check_MK inventory' and re.match('.*unmonitored.*', alert[4]):
                refresh_hosts.add(alert[1])
        if len(refresh_hosts) == 0:
            print('there are currently no hosts with un-monitored services')
            return
        refresh_hosts = sorted(refresh_hosts)
        if confirm:
            print()
            for i in refresh_hosts:
                print(self.str_green(i))
            print()
            if not yes_no('do you wish to proceed with the refresh of these hosts?'):
                return
        for i in refresh_hosts:
            self.refresh(i)
        if activate:
            self.activate()

    def activate(self):
        print('activating changes, this may take some time…')
        r = self.request_webapi('&action=activate_changes&mode=dirty&allow_foreign_changes=1')
        if r.json()['result_code'] == 0:
            sites = ''
            for i in r.json()['result']['sites']:
                sites = sites + i + ' '
            print('changes activated successfully on these sites: ' + sites)
        else:
            print(re.sub('Check_MK exception: ', '', r.json()['result']).lower())

    def get_problems(self, ignore_status, problem_type, folder):
        url = '&output_format=json&filled_in=filter'
        if not problem_type or problem_type == 'service':
            url = url + '&view_name=svcproblems'
            if ignore_status:
                url = url + '&is_service_acknowledged=-1&is_in_downtime=-1'
            else:
                url = url + '&is_service_acknowledged=0&is_in_downtime=0'
        elif problem_type == 'host':
            url = url + '&view_name=hostproblems'
            if ignore_status:
                url = url + '&filled_in=filter&is_host_acknowledged=-1&is_host_scheduled_downtime_depth=-1'
            else:
                url = url + '&filled_in=filter&is_host_acknowledged=0&is_host_scheduled_downtime_depth=0'
        if folder:
            folders = self.get_folders()
            if folder not in folders:
                print('the folder {} does not exist.\nspecify the full path of the folder. see the \'folders\' command for a list'.format(self.str_red(folder)))
            url = url + '&wato_folder=' + folder
        r = self.request_view(url).json()
        return r

    def get_host_problems(self, ignore_status, folder):
        return self.get_problems(ignore_status, 'host', folder)

    def get_service_problems(self, ignore_status, folder):
        return self.get_problems(ignore_status, 'service', folder)

    def get_host_problems_table(self, ignore_status, folder):
        host_problems = self.get_host_problems(ignore_status, folder)
        host_problems.pop(0)  # ignore header
        host_problems_table = []
        for i in host_problems:
            host = i[0]
            address = i[1]
            icons = i[2]
            if i[3] == u'DOWN':
                state = self.str_red(i[3])
            elif i[3] == u'UNKN':
                state = self.str_orange(i[3])
            else:
                state = i[3]
            ack = ''
            if 'ack' in icons:
                ack = ack + '(acknowledged) '
            if 'downtime' in icons:
                ack = ack + '(downtime)'
            ack = self.str_blue(ack)
            detail = i[4]
            detail = re.sub('^(CRIT|WARN|UNKNOWN) - ', '', detail)
            detail = textwrap.fill(detail, 100)
            srv_ok = int(i[5])
            srv_warn = int(i[6])
            srv_crit = int(i[7])
            srv_unkn = int(i[8])
            srv_pend = int(i[9])
            if srv_ok > 0:
                srv_ok = self.str_green(str(srv_ok))
            if srv_warn > 0:
                srv_warn = self.str_yellow(str(srv_warn))
            if srv_crit > 0:
                srv_crit = self.str_red(str(srv_crit))
            if srv_unkn > 0:
                srv_unkn = self.str_orange(str(srv_unkn))
            host_problems_table.append([state, host, address, detail, ack, srv_ok, srv_warn, srv_crit, srv_unkn, srv_pend])
        return host_problems_table

    def host_problem_table_headers(self):
        headers = []
        for i in ['state', 'host', 'address', 'detail', 'acknowledged', 'srv_ok', 'srv_warn', 'srv_crit', 'srv_unkn', 'srv_pend']:
            headers.append(self.str_bold(i))
        return headers

    def list_host_problems_table(self, ignore_status, folder):
        host_problems_table = self.get_host_problems_table(ignore_status, folder)
        headers = self.host_problem_table_headers()
        if not ignore_status:
            del headers[4]
            for row in host_problems_table:
                del row[4]
        if len(host_problems_table) > 0:
            print()
            print(self.str_bold('host problems'))
            print()
            print(tabulate(host_problems_table, headers=headers))
        return host_problems_table

    def list_host_problems(self, ignore_status, folder):
        host_problems = self.get_host_problems(ignore_status, folder)
        host_problems.pop(0)  # ignore header
        for i in host_problems:
            host = i[0]
            address = i[1]
            icons = i[2]
            if i[3] == u'DOWN':
                state = self.str_red(i[3])
            elif i[3] == u'UNKN':
                state = self.str_orange(i[3])
            else:
                state = i[3]
            ack = ''
            if 'ack' in icons:
                ack = ack + '(acknowledged) '
            if 'downtime' in icons:
                ack = ack + '(downtime)'
            ack = self.str_blue(ack)
            detail = i[4]
            detail = re.sub('^(CRIT|WARN|UNKNOWN) - ', '', detail)
            print(u'{} - {} - {} - {} {}'.format(state, host, address, detail, ack))

    def get_service_problems_table(self, ignore_status, folder):
        service_problems = self.get_service_problems(ignore_status, folder)
        service_problems.pop(0)  # ignore header
        service_problems_table = []
        for i in service_problems:
            if i[0] == u'CRIT':
                state = self.str_red(i[0])
            elif i[0] == u'WARN':
                state = self.str_yellow(i[0])
            elif i[0] == u'UNKN':
                state = self.str_orange(i[0])
            else:
                state = i[0]
            host = i[1]
            service = i[2]
            service = textwrap.fill(service, 70)
            icons = i[3]
            ack = ''
            if 'ack' in icons:
                ack = ack + '(acknowledged) '
            if 'downtime' in icons:
                ack = ack + '(downtime)'
            ack = self.str_blue(ack)
            detail = i[4]
            detail = re.sub('^(CRIT|WARN|UNKNOWN) - ', '', detail)
            detail = textwrap.fill(detail, 100)
            state_age = i[5]
            service_problems_table.append([state, host, service, detail, state_age, ack])
        return service_problems_table

    def service_problem_table_headers(self):
        headers = []
        for i in ['state', 'host', 'service', 'detail', 'state age', 'acknowledged']:
            headers.append(self.str_bold(i))
        return headers

    def list_service_problems_table(self, ignore_status, folder):
        service_problems_table = self.get_service_problems_table(ignore_status, folder)
        headers = self.service_problem_table_headers()
        if not ignore_status:
            del headers[5]
            for row in service_problems_table:
                del row[5]
        if len(service_problems_table) > 0:
            print()
            print(self.str_bold('service problems'))
            print()
            print(tabulate(service_problems_table, headers=headers))
        return service_problems_table

    def list_service_problems(self, ignore_status, folder):
        service_problems = self.get_service_problems(ignore_status, folder)
        service_problems.pop(0)  # ignore header
        for i in service_problems:
            if i[0] == u'CRIT':
                state = self.str_red(i[0])
            elif i[0] == u'WARN':
                state = self.str_yellow(i[0])
            elif i[0] == u'UNKN':
                state = self.str_orange(i[0])
            else:
                state = i[0]
            host = i[1]
            service = i[2]
            icons = i[3]
            ack = ''
            if 'ack' in icons:
                ack = ack + '(acknowledged) '
            if 'downtime' in icons:
                ack = ack + '(downtime)'
            ack = self.str_blue(ack)
            detail = i[4]
            detail = re.sub('^(CRIT|WARN|UNKNOWN) - ', '', detail)
            state_age = i[5]
            print(u'{} - {} - {} - {} - {} {}'.format(state, host, service, detail, state_age, ack))

    def get_hosts(self):
        hosts = []
        r = self.request_webapi('&action=get_all_hosts&effective_attributes=1').json()['result']
        for i in r:
            hosts.append(i)
        hosts.sort()
        return hosts

    def list_hosts(self):
        hosts = self.get_hosts()
        for i in hosts:
            print(i)

    def check_site_exists(self, site):
        sites = self.get_sites()
        for i in sites:
            if i[0] == site:
                return True
        return False

    def get_sites(self):
        r = self.request_wato('&mode=sites')
        sites_parser = WatoSitesHtmlParser()
        sites_parser.feed(r.text)
        sites = sites_parser.get_sites()
        return sites

    def list_sites(self):
        sites = self.get_sites()
        print(tabulate(sites, headers=['site_id', 'site_name', 'socket']))

    def get_ip_bulk(self, hostname, lazy):
        if lazy:
            match_string = '{}'
        else:
            match_string = '*{}*'
        hosts = self.get_hosts()
        for i in hosts:
            if fnmatch.fnmatchcase(i, match_string.format(hostname)):
                self.get_ip(i)

    def get_ip(self, hostname):
        r = self.request_webapi_post('&action=get_host&effective_attributes=1', 'request={{"hostname": "{}"}}'.format(hostname)).json()
        ip = r[u'result'][u'attributes'][u'ipaddress']
        try:
            if not re.match(IP_REGEXP, ip):
                if not ip:
                    ip = hostname
                ip = socket.gethostbyname(ip)
            print('{}: {}'.format(self.str_green(hostname), ip))
        except socket.gaierror:
            print('error: unable to resolve hostname: {}'.format(self.str_red(ip)))

    def get_folders(self):
        folders = []
        r = self.request_webapi('&action=get_all_folders&effective_attributes=1').json()['result']
        for i in r:
            folders.append(i)
        folders.sort()
        return folders

    def list_folders(self):
        folders = self.get_folders()
        folders.pop(0)  # ignore root folder
        for i in folders:
            print(i)

    def add_host_preflight_check(self, hostname, folder, folder_create, site, ip, ignore_dns):
        if not self.check_site_exists(site):
            print('error: the Check_MK site {} does not exist\nuse the \'sites\' command for a list.'.format(self.str_red(site)))
            sys.exit(1)
        if not ip and not ignore_dns:
            try:
                socket.gethostbyname(hostname)
            except socket.gaierror:
                print('error: unable to resolve hostname: {}\nthe hostname must be DNS resolvable, or the IP address (or resolvable FQDN) must be specified using (-i|--ip)'.format(self.str_red(hostname)))
                sys.exit(1)
        if ip and not ignore_dns:
            if not re.match(IP_REGEXP, ip):
                try:
                    socket.gethostbyname(ip)
                except socket.gaierror:
                    print('error: the IP parameter must be either an IP address or a resolvable FQDN, but {} does not appear to be either of these…'.format(self.str_red(ip)))
                    sys.exit(1)
        if folder:
            if folder not in self.get_folders():
                if folder_create:
                    print('the folder {} does not exist. it will be created.'.format(self.str_green(folder)))
                else:
                    print('error: the folder {} does not exist\nuse the \'folders\' command for a list.'.format(self.str_red(folder)))
                    sys.exit(1)

    def add_host(self, hostname, folder, site, ip, activate, mode):
        url = '&action=add_host'
        attr_str = '"site": "{}"'.format(site)
        if mode and mode == 'testing':
            attr_str = attr_str + ', "tag_criticality": "criticality-test"'
        elif mode and mode == 'disabled':
            attr_str = attr_str + ', "tag_criticality": "criticality-offline"'
        if ip:
            attr_str = attr_str + ', "ipaddress": "{}"'.format(ip)
        if not folder:
            folder = ''
        post = 'request={{ "hostname": "{}", "folder": "{}", "attributes": {{ {} }} }}'.format(hostname, folder, attr_str)
        r = self.request_webapi_post(url, post)
        if r.json()['result_code'] == 0:
            print('host {} successfully added.'.format(self.str_green(hostname)), end='')
            if not mode == 'disabled':
                print(' discovering services…')
                self.refresh(hostname)
            else:
                print()
            if activate:
                self.activate()
        else:
            print('error: ' + re.sub(r'Check_MK exception: ', '', r.json()['result']).lower())
            exit(1)

    def acknowledge(self):
        host_problems = self.get_host_problems_table(False, None)
        service_problems = self.get_service_problems_table(False, None)
        total_problems = len(host_problems) + len(service_problems)
        if total_problems == 0:
            print('there are no un-acknowledged host or service problems.')
            sys.exit(0)
        i = 0
        if len(host_problems) > 0:
            headers = self.host_problem_table_headers()
            del headers[4]
            headers.insert(0, ' ')
            for row in host_problems:
                del row[4]
                row.insert(0, '[ ' + str(i + 1).rjust(3) + ' ]')
                i += 1
            print()
            print(self.str_bold('host problems'))
            print()
            print(tabulate(host_problems, headers=headers))
        if len(service_problems) > 0:
            headers = self.service_problem_table_headers()
            del headers[5]  # acknowledged
            headers.insert(0, ' ')
            print()
            print(self.str_bold('service problems'))
            print()
            for row in service_problems:
                del row[5]  # acknowledged
                row.insert(0, '[ ' + str(i+1).rjust(3) + ' ]')
                i += 1
            print(tabulate(service_problems, headers=headers))
        print()
        problem_id = self.get_problem_id(True, total_problems)
        if not problem_id:
            return
        if problem_id <= len(host_problems):
            self.prompt_acknowledge_problem(host_problems[problem_id - 1][1], host_problems[problem_id - 1][2], None, host_problems[problem_id - 1][4])
        else:
            self.prompt_acknowledge_problem(service_problems[problem_id - len(host_problems) - 1][1], service_problems[problem_id - len(host_problems) - 1][2], service_problems[problem_id - len(host_problems) - 1][3], service_problems[problem_id - len(host_problems) - 1][4])

    def unacknowledge(self):
        acknowledged_host_problems = self.get_acknowledged_hosts()
        acknowledged_service_problems = self.get_acknowledged_services()
        total_problems = len(acknowledged_host_problems) + len(acknowledged_service_problems )
        if total_problems == 0:
            print('there are no acknowledged host or service problems.')
            sys.exit(0)
        i = 0
        if len(acknowledged_host_problems) > 0:
            headers = self.acknowledged_hosts_table_headers()
            headers.insert(0, ' ')
            for row in acknowledged_host_problems:
                row.insert(0, '[ ' + str(i + 1).rjust(3) + ' ]')
                i += 1
            print()
            print(self.str_bold('acknowledged host problems'))
            print()
            print(tabulate(acknowledged_host_problems, headers=headers))
        if len(acknowledged_service_problems) > 0:
            headers = self.acknowledged_services_headers()
            headers.insert(0, ' ')
            print()
            print(self.str_bold('acknowledged service problems'))
            print()
            for row in acknowledged_service_problems:
                row.insert(0, '[ ' + str(i+1).rjust(3) + ' ]')
                i += 1
            print(tabulate(acknowledged_service_problems, headers=headers))
        print()
        problem_id = self.get_problem_id(False, total_problems)
        if not problem_id:
            return
        if problem_id <= len(acknowledged_host_problems):
            self.print_acknowledgement(acknowledged_host_problems[problem_id - 1][1], acknowledged_host_problems[problem_id - 1][2], None, acknowledged_host_problems[problem_id - 1][4], None)
            if not yes_no('do you wish to un-acknowledge this host problem?'):
                return
            self.unacknowledge_problem(acknowledged_host_problems[problem_id - 1][2], None)
        else:
            self.print_acknowledgement(acknowledged_service_problems[problem_id - len(acknowledged_host_problems) - 1][1], acknowledged_service_problems[problem_id - len(acknowledged_host_problems) - 1][2], acknowledged_service_problems[problem_id - len(acknowledged_host_problems) - 1][3], acknowledged_service_problems[problem_id - len(acknowledged_host_problems) - 1][4], None)
            if not yes_no('do you wish to un-acknowledge this service problem?'):
                return
            self.unacknowledge_problem(acknowledged_service_problems[problem_id - len(acknowledged_host_problems) - 1][2], acknowledged_service_problems[problem_id - len(acknowledged_host_problems) - 1][3])

    def get_problem_id(self, ack, total_problems):
        if not ack:
            prefix = 'un-'
        else:
            prefix = ''
        try:
            problem_id = int(input('select a host or service problem to {}acknowledge [ 1 - {} ]: '.format(prefix, total_problems)))
        except ValueError:
            return self.get_problem_id(ack, total_problems)
        except (KeyboardInterrupt, EOFError):
            print()
            return
        if 1 <= problem_id <= total_problems:
            return problem_id
        else:
            return self.get_problem_id(ack, total_problems)

    def get_acknowledge_comment(self):
        try:
            comment = str(input('enter a comment for the acknowledgement: ')).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return
        if not comment == '':
            comment = re.sub(';', ':', comment)  # semi-colons not allowed in comments
            return comment
        else:
            return self.get_acknowledge_comment()

    def print_acknowledgement(self, state, host, service, detail, comment):
        margin = 10
        detail = re.sub(r'\n', '\n' + ' ' * margin, detail)
        print()
        print('{}{}'.format(self.str_bold('state: '.rjust(margin)), state))
        print('{}{}'.format(self.str_bold('host: '.rjust(margin)), host))
        if service:
            print('{}{}'.format(self.str_bold('service: '.rjust(margin)), service))
        print('{}{}'.format(self.str_bold('detail: '.rjust(margin)), detail))
        if comment:
            print('{}{}'.format(self.str_bold('comment: '.rjust(margin)), comment))
        print()

    def prompt_acknowledge_problem(self, state, host, service, detail):
        print()
        comment = self.get_acknowledge_comment()
        if not comment:
            return
        self.print_acknowledgement(state, host, service, detail, comment)
        if service:
            if not yes_no('do you wish to acknowledge this service problem?'):
                return
        else:
            if not yes_no('do you wish to acknowledge this host problem?'):
                return
        self.acknowledge_problem(host, service, comment)

    def acknowledge_problem(self, host, service, comment):
        user_comment = u'{}: {}'.format(get_username(), comment)
        url = '&output_format=json&filled_in=confirm&_acknowledge=Acknowledge&_transid=-1&site=&_do_actions=yes&_ack_notify=on&host={}&_ack_comment={}&_do_confirm=Yes'.format(urllib.parse.quote(host), urllib.parse.quote(user_comment))
        if service:
            url = url + '&view_name=service&service={}'.format(urllib.parse.quote(service))
        else:
            url = url + '&view_name=hoststatus'
        url = url + '&output_format=json&filled_in=confirm&_acknowledge=Acknowledge&_transid=-1&site=&_do_actions=yes&_ack_notify=on&host={}&_ack_comment={}&_do_confirm=Yes'.format(urllib.parse.quote(host), urllib.parse.quote(user_comment))
        r = self.request_view(url)
        if 'MESSAGE: Successfully sent' in r.text:
            if service:
                print('service problem {} on host {} was acknowledged.'.format(self.str_green(service), self.str_green(host)))
            else:
                print('host problem on {} was acknowledged.'.format(self.str_green(host)))
        else:
            if service:
                print('unable to acknowledge service problem {} on host {}\nyou probably specified a host or service which does not exist'.format(self.str_red(service), self.str_red(host)))
            else:
                print('unable to acknowledge host problem on {}.\nyou probably specified a host which does not exist'.format(self.str_red(host)))

    def unacknowledge_problem(self, host, service):
        if service:
            url = '&view_name=service&service={}'.format(urllib.parse.quote(service))
        else:
            url = '&view_name=hoststatus'
        url = url + '&output_format=json&filled_in=confirm&_remove_ack=Remove+Acknowledgement&_transid=-1&site=&_do_actions=yes&_ack_notify=on&host={}&_do_confirm=Yes'.format(urllib.parse.quote(host))
        r = self.request_view(url)
        if 'MESSAGE: Successfully sent' in r.text:
            if service:
                print('service problem {} on host {} was un-acknowledged.'.format(self.str_green(service), self.str_green(host)))
            else:
                print('host problem on {} was un-acknowledged.'.format(self.str_green(host)))
        else:
            if service:
                print('unable to un-acknowledge service problem {} on host {}\nyou probably specified a host or service which does not exist'.format(self.str_red(service), self.str_red(host)))
            else:
                print('unable to un-acknowledge host problem on {}.\nyou probably specified a host which does not exist'.format(self.str_red(host)))

    def get_acknowledged_hosts(self):
        host_problems = self.get_host_problems(True, None)
        acknowledged_host_problems = []
        comments = self.get_comments()
        for i in host_problems:
            if u'ack' in i[2]:
                comment = self.get_comment(comments, i[0], None)
                if comment:
                    author = comment[0]
                    comment = textwrap.fill(comment[1], 60)
                else:
                    comment = ''
                    author = ''
                if i[3] == u'DOWN':
                    state = self.str_red(i[3])
                elif i[3] == u'UNKN':
                    state = self.str_orange(i[3])
                else:
                    state = i[3]
                host = i[0]
                address = i[1]
                detail = textwrap.fill(i[4], 60)
                problem = [
                    state,
                    host,
                    address,
                    detail,
                    author,
                    comment,
                ]
                acknowledged_host_problems.append(problem)
        return acknowledged_host_problems

    def get_acknowledged_services(self):
        service_problems = self.get_service_problems(True, None)
        acknowledged_service_problems = []
        comments = self.get_comments()
        for i in service_problems:
            if u'ack' in i[3]:
                comment = self.get_comment(comments, i[1], i[2])
                if comment:
                    author = comment[0]
                    comment = textwrap.fill(comment[1], 60)
                else:
                    comment = ''
                    author = ''
                if i[0] == u'CRIT':
                    state = self.str_red(i[0])
                elif i[0] == u'WARN':
                    state = self.str_yellow(i[0])
                elif i[0] == u'UNKN':
                    state = self.str_orange(i[0])
                else:
                    state = i[0]
                host = i[1]
                service = i[2]
                detail = textwrap.fill(i[4], 60)
                since = i[5]
                problem = [
                    state,
                    host,
                    service,
                    detail,
                    since,
                    author,
                    comment,
                ]
                acknowledged_service_problems.append(problem)
        return acknowledged_service_problems

    def acknowledged_hosts_table_headers(self):
        headers = []
        for i in ['state', 'host', 'address', 'detail', 'acknowledged by', 'comment']:
            headers.append(self.str_bold(i))
        return headers

    def acknowledged_services_headers(self):
        headers = []
        for i in ['state', 'host', 'service', 'detail', 'since', 'acknowledged by', 'comment']:
            headers.append(self.str_bold(i))
        return headers

    def list_acknowledged_hosts(self):
        acknowledged_host_problems = self.get_acknowledged_hosts()
        if len(acknowledged_host_problems) > 0:
            print()
            print(self.str_bold('acknowledged host problems'))
            print()
            print(tabulate(acknowledged_host_problems, headers=self.acknowledged_hosts_table_headers()))

    def list_acknowledged_services(self):
        acknowledged_service_problems = self.get_acknowledged_services()
        if len(acknowledged_service_problems) > 0:
            print()
            print(self.str_bold('acknowledged service problems'))
            print()
            print(tabulate(acknowledged_service_problems, headers=self.acknowledged_services_headers()))

    def get_comment(self, comments, host, service):
        for i in comments:
            if host and not service and i[2] == host:
                return [i[0], i[4]]
            elif host and service and i[2] == host and i[3] == service:
                return [i[0], i[4]]
        return None

    def get_comments(self):
        r = self.request_view('&view_name=comments&output_format=json').json()
        r.pop(0)
        comments = []
        for i in r:
            if not i[0] == u'(Nagios Process)':
                comment = [
                    i[0],  # comment_author
                    i[1],  # comment_time
                    i[5],  # comment_host
                    i[6],  # service_description
                    textwrap.fill(i[4], 100),  # comment_comment
                ]
                comments.append(comment)
        return comments

    def list_comments(self):
        comments = self.get_comments()
        if len(comments) > 0:
            headers = []
            for i in ['author', 'time', 'host', 'service', 'comment']:
                headers.append(self.str_bold(i))
            print()
            print(tabulate(comments, headers=headers))
            print()

    def str_red(self, s):
        return ''.join([colored.fg('red'), s, colored.attr('reset')]) if self.print_colour else s

    def str_yellow(self, s):
        return ''.join([colored.fg('yellow'), s, colored.attr('reset')]) if self.print_colour else s

    def str_blue(self, s):
        return ''.join([colored.fg('blue'), s, colored.attr('reset')]) if self.print_colour else s

    def str_green(self, s):
        return ''.join([colored.fg('green'), s, colored.attr('reset')]) if self.print_colour else s

    def str_orange(self, s):
        return ''.join([colored.fg('dark_orange'), s, colored.attr('reset')]) if self.print_colour else s

    def str_bold(self, s):
        return ''.join([colored.attr('bold'), s, colored.attr('reset')]) if self.print_colour else s


def yes_no(question):
    try:
        a = str(input("{} [Y/n] ".format(question))).lower().strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return
    if a[:1] == 'y' or a == '':
        return True
    elif a[:1] == 'n':
        return False
    else:
        return yes_no(question)


def downtime_date_past_error(date):
    print('error: cannot set downtime on a date that is in the past ({})… specify a future date'.format(date))
    sys.exit(1)


def downtime_date_check(period):
    if (datetime.now() - period[0]).total_seconds() > 1:
        downtime_date_past_error(period[0])
    if (datetime.now() - period[1]).total_seconds() > 1:
        downtime_date_past_error(period[1])
    if period[1] <= period[0]:
        print('error: end date precedes start date… check your inputs and re-try')
        sys.exit(1)


def date_parse_error(start_end, date):
    print('''error: could not understand the downtime {0} date/time: '{1}'

try something like:
    '2018-12-31'
    '2018-12-31 10:15'
    'August 14, 2015 EST'
    'July 4, 2013 PST'
    '21 July 2013 10:15 pm +0500'

…or see here for formatting examples: https://dateparser.readthedocs.io'''.format(start_end, date))
    sys.exit(1)


def get_username():
    return pwd.getpwnam(getpass.getuser())[4]


class WatoSitesHtmlParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.output = []
        self.row_index = -1
        self.column_index = 0
        self.header_found = False

    def handle_starttag(self, tag, attrs):
        if not self.header_found:
            return
        else:
            if tag == 'tr':
                self.row_index += 1
                self.column_index = 0
                self.output.append([])
            if tag == 'td':
                self.column_index += 1

    def handle_endtag(self, tag):
        if tag == 'table':
            if not self.header_found:
                self.header_found = True

    def handle_data(self, data):
        if self.column_index == 2:
            self.output[self.row_index].append(data)
        elif self.column_index == 3:
            self.output[self.row_index].append(data)
        elif self.column_index == 4:
            self.output[self.row_index].append(data)

    def get_sites(self):
        self.output.pop()
        self.output.pop(0)
        return self.output


def positive_integer(i):
    i = int(i)
    if i <= 0:
        raise argparse.ArgumentTypeError('invalid positive integer value: {}'.format(i))
    return i


def main():
    parser = argparse.ArgumentParser(description='check-mk-cli - command line management of Check_MK')
    parser.add_argument('--plain', action='store_true', help='don\'t use colour in terminal output')

    subparsers = parser.add_subparsers(title='commands', dest='command')

    hostname_help = 'name of the host(s) -- finds all hosts containing the specified string. for more restrictive matching, use --lazy mode.'
    lazy_hostname_help = 'lazy hostname matching. in this mode, you must specify the entire hostname, or use *wildcards*'

    parser_ack = subparsers.add_parser('acknowledge', aliases=['ack'], help='add, remove, or view acknowledgements on hosts and services')
    parser_ack_subparsers = parser_ack.add_subparsers(dest='ack_action')

    parser_ack_list = parser_ack_subparsers.add_parser('list', help='list acknowledged host or service problems')
    parser_ack_list.add_argument('--hosts', action='store_true', help='list acknowledged host problems')
    parser_ack_list.add_argument('--services', action='store_true', help='list acknowledged service problems')

    parser_ack_add = parser_ack_subparsers.add_parser('add', help='acknowledge a host or service problem')
    parser_ack_add.add_argument('--host', help='add acknowledgement on this host (required, if a service is specified)')
    parser_ack_add.add_argument('--service', help='add acknowledgement on this service problem')
    parser_ack_add.add_argument('--comment', help='comment (required, if a host or service is specified)')

    parser_ack_remove = parser_ack_subparsers.add_parser('remove', help='un-acknowledge a host or service problem')
    parser_ack_remove.add_argument('--host', help='remove acknowledgement on this host (required, if a service is specified)')
    parser_ack_remove.add_argument('--service', help='remove acknowledgement on this service problem')

    parser_downtime = subparsers.add_parser('downtime', help='add, remove, or view downtime on hosts and services')
    parser_downtime_subparsers = parser_downtime.add_subparsers(dest='downtime_action')

    parser_downtime_add = parser_downtime_subparsers.add_parser('add', help='place a host into downtime')
    parser_downtime_add.add_argument('hostname', help=hostname_help)
    parser_downtime_add_time_group = parser_downtime_add.add_mutually_exclusive_group()
    parser_downtime_add_time_group.add_argument('-m', '--minutes', type=positive_integer, help='duration of downtime status (default: {0} minutes)'.format(DOWNTIME_DEFAULT_MINUTES))
    parser_downtime_add_time_group.add_argument('--hours', type=positive_integer, help='duration of downtime status')
    parser_downtime_add_time_group.add_argument('-d', '--days', type=positive_integer, help='duration of downtime status')
    parser_downtime_add_time_group.add_argument('-p', '--period', nargs=2, type=str, help='schedule downtime for time period', metavar=('START', 'END'))
    parser_downtime_add.add_argument('-s', '--service', type=str, help='set downtime status for a service (rather than the entire host)')
    parser_downtime_add.add_argument('-c', '--comment', type=str, help='add a comment')
    parser_downtime_add.add_argument('--lazy', action='store_true', help=lazy_hostname_help)

    parser_downtime_remove = parser_downtime_subparsers.add_parser('remove', help='remove a host or service from downtime')
    parser_downtime_remove.add_argument('hostname', help=hostname_help)
    parser_downtime_remove.add_argument('-s', '--service', type=str, help='remove downtime status for a service (rather than the entire host)')
    parser_downtime_remove.add_argument('--lazy', action='store_true', help='lazy hostname matching. in this mode, you must specify the entire hostname, or use *wildcards*')

    parser_downtime_remove = parser_downtime_subparsers.add_parser('list', help='list hosts and service currently in downtime')
    parser_downtime_remove.add_argument('--hosts', action='store_true', help='list hosts in downtime')
    parser_downtime_remove.add_argument('--services', action='store_true', help='list services in downtime')

    parser_add_host = subparsers.add_parser('add_host', help='add a new host')
    parser_add_host.add_argument('hostname', help='name of the new host')
    parser_add_host.add_argument('-s', '--site', required=True, help='ID of the site that the new host will be monitored from (use the \'sites\' command to get a list)')
    parser_add_host.add_argument('-f', '--folder', help='folder that the new host will reside in (use the \'folders\' command to get a list). if no folder is specified, the host will be added to the WATO root')
    parser_add_host.add_argument('--folder-create', action='store_true', help='if the specified folder does not exist, it will be created')
    parser_add_host.add_argument('-i', '--ip', help='optional IP address (or resolvable FQDN). if this is not supplied, the host name must be DNS resolvable. if you wish, you can set the VMware name (or some other canonical name) as the \'hostname\' and set this parameter to the resolvable FQDN')
    parser_add_host.add_argument('-a', '--activate', action='store_true', help='activate changes after adding')

    parser_add_host_mode_group = parser_add_host.add_mutually_exclusive_group()
    parser_add_host_mode_group.add_argument('--testing', action='store_true', help='place the new host in test mode. the host will not alert to on-call staff.')
    parser_add_host_mode_group.add_argument('--disabled', action='store_true', help='disable the host. the host will not be monitored.')

    parser_add_host.add_argument('--ignore-dns', action='store_true', help='do not perform DNS resolution checks prior to adding the host (if DNS resolution is local only to the monitoring site, for example)')

    parser_refresh = subparsers.add_parser('refresh', help='refresh host check configuration')
    parser_refresh_host_group = parser_refresh.add_mutually_exclusive_group()
    parser_refresh_host_group.add_argument('--host', help=hostname_help)
    parser_refresh_host_group.add_argument('--unknown', action='store_true', help='refresh configuration for hosts with \'Unknown\' checks')
    parser_refresh_host_group.add_argument('--unmonitored', action='store_true', help='refresh configuration for hosts with newly discovered unmonitored checks')
    parser_refresh.add_argument('-y', '--yes', action='store_true', help='proceed without confirming')
    parser_refresh.add_argument('-a', '--activate', action='store_true', help='activate changes after refreshing')
    parser_refresh.add_argument('--lazy', action='store_true', help=lazy_hostname_help)

    subparsers.add_parser('activate', help='activate all pending changes')

    parser_problems = subparsers.add_parser('problems', help='list service problems')
    parser_problems.add_argument('-a', '--all', action='store_true', help='include acknowledged problems, and services in downtime')
    parser_problems.add_argument('-l', '--list', action='store_true', help='format output in a list (not a table)')
    parser_problems_filter_group = parser_problems.add_mutually_exclusive_group()
    parser_problems_filter_group.add_argument('--hosts', action='store_true', help='list host problems')
    parser_problems_filter_group.add_argument('--services', action='store_true', help='list service problems')
    parser_problems_folder_group = parser_problems.add_mutually_exclusive_group()
    parser_problems_folder_group.add_argument('-f', '--folder', help='list problems for specified WATO folder')

    subparsers.add_parser('hosts', help='list hosts')
    subparsers.add_parser('sites', help='list sites')
    subparsers.add_parser('folders', help='list folders')
    subparsers.add_parser('comments', help='list host/service comments')

    parser_ip = subparsers.add_parser('ip', help='get IP address of host')
    parser_ip.add_argument('hostname', help=hostname_help)
    parser_ip.add_argument('--lazy', action='store_true', help=lazy_hostname_help)

    args = parser.parse_args()

    cmk = CheckMk()

    if args.plain:
        cmk.set_colour(False)

    if args.command == 'acknowledge' or args.command == 'ack':
        if args.ack_action == 'list':
            if args.hosts:
                cmk.list_acknowledged_hosts()
            elif args.services:
                cmk.list_acknowledged_services()
            else:
                cmk.list_acknowledged_hosts()
                cmk.list_acknowledged_services()
        elif args.ack_action == 'add':
            if not args.host and not args.service:
                cmk.acknowledge()
            if (args.host or args.service) and not args.comment:
                parser_ack.error('--comment must be specified when acknowledging a host or service problem')
            elif args.host and not args.service:
                cmk.acknowledge_problem(args.host, None, args.comment)
            elif args.service and not args.host:
                parser_ack.error('--host must also be specified when acknowledging a service problem')
            elif args.service and args.host:
                cmk.acknowledge_problem(args.host, args.service, args.comment)
        elif args.ack_action == 'remove':
            if not args.host and not args.service:
                cmk.unacknowledge()
            elif args.host and args.service:
                cmk.unacknowledge_problem(args.host, args.service)
            elif args.host and not args.service:
                cmk.unacknowledge_problem(args.host, None)
            else:
                parser_ack.error('--host must also be specified when un-acknowledging a service problem')
        else:
            parser_ack.print_help(sys.stderr)
            sys.exit(2)
    elif args.command == 'add_host':
        if args.testing:
            mode = 'testing'
        elif args.disabled:
            mode = 'disabled'
        else:
            mode = None
        cmk.add_host_preflight_check(args.hostname, args.folder, args.folder_create, args.site, args.ip, args.ignore_dns)
        cmk.add_host(args.hostname, args.folder, args.site, args.ip, args.activate, mode)
    elif args.command == 'downtime':
        if args.downtime_action == 'add':
            if args.minutes:
                minutes = args.minutes
            elif args.hours:
                minutes = args.hours * 60
            elif args.days:
                minutes = args.days * 24 * 60
            else:
                minutes = None
            if args.period:
                import dateparser  # slow, lazy import
                start_str = args.period[0]
                end_str = args.period[1]
                start = dateparser.parse(start_str)
                if not start:
                    date_parse_error('start', start_str)
                end = dateparser.parse(end_str)
                if not end:
                    date_parse_error('end', end_str)
                period = [start, end]
                downtime_date_check(period)
            else:
                period = None
            if not minutes and not period:
                minutes = DOWNTIME_DEFAULT_MINUTES
            cmk.downtime_bulk_add(args.hostname, args.service, args.lazy, args.comment, minutes, period)
        elif args.downtime_action == 'remove':
            cmk.downtime_bulk_remove(args.hostname, args.service, args.lazy)
        elif args.downtime_action == 'list':
            cmk.downtime_list(args.hosts, args.services)
        else:
            parser_downtime.print_help(sys.stderr)
            sys.exit(2)
    elif args.command == 'refresh':
        if args.host:
            cmk.refresh_bulk(args.host, not args.yes, args.activate, args.lazy)
        elif args.unknown:
            cmk.unknown_refresh(not args.yes, args.activate)
        elif args.unmonitored:
            cmk.unmonitored_refresh(not args.yes, args.activate)
        else:
            parser_refresh.print_help(sys.stderr)
    elif args.command == 'activate':
        cmk.activate()
    elif args.command == 'problems':
        if args.folder:
            folder = args.folder
        else:
            folder = None
        if args.hosts:
            if args.list:
                cmk.list_host_problems(args.all, folder)
            else:
                cmk.list_host_problems_table(args.all, folder)
        elif args.services:
            if args.list:
                cmk.list_service_problems(args.all, folder)
            else:
                cmk.list_service_problems_table(args.all, folder)
        else:
            if args.list:
                cmk.list_host_problems(args.all, folder)
                cmk.list_service_problems(args.all, folder)
            else:
                cmk.list_host_problems_table(args.all, folder)
                cmk.list_service_problems_table(args.all, folder)
    elif args.command == 'hosts':
        cmk.list_hosts()
    elif args.command == 'sites':
        cmk.list_sites()
    elif args.command == 'folders':
        cmk.list_folders()
    elif args.command == 'comments':
        cmk.list_comments()
    elif args.command == 'ip':
        cmk.get_ip_bulk(args.hostname, args.lazy)
    else:
        parser.print_help(sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        sys.exit(0)
