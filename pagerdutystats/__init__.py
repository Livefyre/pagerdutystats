#!/usr/bin/env python

USAGE= \
"""
Usage:
    pagerduty.py <subdomain> <api-token> (all|wakeups|flakes) [--top=<top> --no-thurs --email] [--start=<start> [--end=<end>] | --last=<last>]
    pagerduty.py mtr [--start=<start> [--end=<end>] | --last=<last>]

Options:
    --top=INTEGER Count of top-ranked offenders to return.
    --start=DATETIME Start of report period (Pacific time)
    --end=DATETIME End of report period (Pacific time)
    --last=INTEGER Number of previous minutes for the report period.
"""

from docopt import docopt
import pygerduty
from datetime import datetime, timedelta
from dateutil.tz import *
import dateutil.parser
from collections import Counter

import sys

class Incident(pygerduty.Incident):

    def get_description(self):
        data = self.trigger_summary_data
        try:
            if data.SERVICEDESC and data.SERVICESTATE:
                desc = " - ".join((data.SERVICEDESC, data.SERVICESTATE))
            elif data.HOSTNAME and data.HOSTSTATE:
                desc = " - ".join((data.HOSTNAME, data.HOSTSTATE))
        except AttributeError:
            try:
                desc = data.description
            except AttributeError:
                try:
                    desc = data.subject
                except:
                    desc = ''
        return desc

    def pacific_time(self, timeattr):
        aware_utc = parse_timestamp(getattr(self,timeattr))
        ptz_time = datetime.astimezone(aware_utc, gettz('America/Los_Angeles'))
        return ptz_time

    def iso_pac_time(self, timeattr):
        return datetime.isoformat(self.pacific_time(timeattr))

    def friendly_pac_time(self, timeattr):
        return datetime.strftime(self.pacific_time(timeattr), "%m-%d %H:%M:%S")

    def link(self):
        return "<a href='%s'>#%s</a>" % (self.html_url, self.incident_number)


class Incidents(pygerduty.Incidents):

    def __init__(self, pagerduty):
        pygerduty.Incidents.__init__(self, pagerduty)
        self.container = Incident

    ops_policy = "PKOFU92"

    def all(self, **kwargs):
        for incident in self.list(**kwargs):
            if incident.escalation_policy.id == self.ops_policy:
                yield incident

    def wakeups(self, **kwargs):
        for incident in self.all(**kwargs):
            time = incident.pacific_time("created_on")
            night = time.replace(hour=23, minute=0, second=0)
            morning = time.replace(hour=8, minute=0, second=0)
            if time > night or time < morning:
                yield incident

    def resolved(self, **kwargs):
        for incident in self.all(**kwargs):
            if incident.status == "resolved":
                yield incident

    #  flakes: resolved by API in under 10 minutes and never acknowledged
    def flakes(self, **kwargs):
        for incident in self.resolved(**kwargs):
            created_on  = incident.pacific_time("created_on")
            last_status = incident.pacific_time("last_status_change_on")
            if last_status - created_on < timedelta(minutes=10) and not incident.resolved_by_user:
                if not [entry for entry in incident.log_entries.list() if entry.type == 'acknowledge']:
                    yield incident


class PagerDuty(pygerduty.PagerDuty):

    def __init__(self, subdomain, api_token):
        pygerduty.PagerDuty.__init__(self, subdomain, api_token)
        self.incidents = Incidents(self)

    def do_list(self, command, no_thurs, **kwargs):
        if no_thurs:
            for incident in strip_thursday(getattr(self.incidents, command)(**kwargs)):
                yield incident
        else:
            for incident in getattr(self.incidents, command)(**kwargs):
                yield incident

    # mean time to resolution
    def get_mtr(self, **kwargs):
        #  list of times to resolution
        ttrs = list()
        for incident in self.incidents.resolved(**kwargs):
            created_on = incident.pacific_time("created_on")
            rslv_time  = incident.pacific_time("last_status_change_on")
            ttr = (rslv_time - created_on).total_seconds()
            ttrs.append(int(ttr))
        return sum(ttrs)/len(ttrs) if ttrs else 0

def top(incidents, count=None):
    if not count:
        count = 25
    descriptions = list()
    incidents_by_desc = dict()
    for incident in incidents:
        desc = incident.get_description()
        descriptions.append(desc)
        incidents_by_desc.setdefault(desc,[]).append(incident)

    counter = Counter(descriptions)
    rankings = counter.most_common(int(count))
    ranking_with_incidents = dict()
    for desc, quant in rankings:
        ranking_with_incidents[(desc,quant)] = incidents_by_desc[desc]

    return ranking_with_incidents

def strip_thursday(incidents):
    for incident in incidents:
        created_on = incident.pacific_time("created_on")
        if not created_on.weekday() == 3:
            yield incident

def pprint_incidents(incidents):
    for incident in sorted(incidents, key=lambda x: x.pacific_time("created_on")):
        created = incident.iso_pac_time("created_on")
        interesting = tuple([incident.id, created, incident.get_description()])
        print "\t".join(interesting)

def pprint_rankings(rankings):
    for (desc, count) in sorted(rankings.keys(), key=lambda x: -x[1]):
        print "%s\t%s" % (str(count), desc)

def generate_html_ranking_file(rankings):
    tmp_file = open('tmp.txt', 'w')
    tmp_file.write("<html><table><thead><th>Count</th><th>Alarm</th><th>Incidents</th><th></th></thead><tbody>")
    for (desc, count) in sorted(rankings.keys(), key=lambda x: -x[1]):
        incidents = rankings[(desc,count)]
        tmp_file.write("<tr><td>" + "</td><td>".join((str(count), desc)) + "</td><td>" +
            incidents[0].link() + "</td><td>" + incidents[0].friendly_pac_time("created_on") + "</td></tr>")
        for incident in incidents[1:]:
            tmp_file.write("<tr><td></td><td></td><td>" + incident.link() + "</td><td>" +
                incident.friendly_pac_time("created_on") + "</td></tr>")
    tmp_file.write("</tbody></table></body></html>")

def email_output(incidents, top_count=None):
    incident_list = list(incidents)
    generate_html_ranking_file(top(incident_list, top_count))
    pprint_incidents(incident_list)

def pacific_to_utc(naive_timestamp):
    aware_time = parse_timestamp(naive_timestamp,gettz('America/Los_Angeles'))
    utc_time = datetime.astimezone(aware_time, tzutc())
    return datetime.strftime(utc_time, "%Y-%m-%dT%H:%M:%SZ")

def parse_timestamp(timestamp,zone=tzutc()):
    dt = dateutil.parser.parse(timestamp, None, yearfirst=True)
    return dt.replace(tzinfo=zone)

def main():
    argv = docopt(USAGE)
    if argv["--start"]:
        start = pacific_to_utc(argv["--start"])
    elif argv["--last"]:
        start = datetime.strftime(
                datetime.utcnow() - timedelta(minutes=int(argv["--last"])), "%Y-%m-%dT%H:%M:%SZ")
    else:
        start = datetime.strftime(datetime.utcnow() - timedelta(days=7), "%Y-%m-%dT%H:%M:%SZ")

    if argv["--end"]:
        end = pacific_to_utc(argv["--end"])
    else:
        end = datetime.strftime(datetime.utcnow(),"%Y-%m-%dT%H:%M:%SZ")

    pager = PagerDuty(argv['<subdomain>'], argv['<api-token>'])

    for command in ['all','wakeups','flakes']:
        if argv[command]:
            incidents = pager.do_list(command, argv['--no-thurs'], since=start, until=end)

            if incidents:
                if argv['--email']:
                    email_output(incidents, argv['--top'])
                elif argv['--top']:
                    pprint_rankings(top(incidents, argv['--top']))
                else:
                    pprint_incidents(incidents)

    if argv['mtr']:
        print pager.get_mtr(since=start, until=end)

