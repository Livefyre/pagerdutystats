#!/usr/bin/env python

USAGE= \
"""
Usage:
    pagerduty.py <api-token> <policy> (all|wakeups|flakes) [--top=<top> --no-thurs --email] [--start=<start> [--end=<end>] | --last=<last>]
    pagerduty.py mtr [--start=<start> [--end=<end>] | --last=<last>]

Options:
    --top=INTEGER Count of top-ranked offenders to return.
    --start=DATETIME Start of report period (Pacific time)
    --end=DATETIME End of report period (Pacific time)
    --last=INTEGER Number of previous minutes for the report period.
"""

from docopt import docopt
import pygerduty.v2
from datetime import datetime, timedelta
from dateutil.tz import *
import dateutil.parser
from collections import Counter

import sys

class Incident(pygerduty.Incident):

    def get_description(self):
        try:
            desc = self.title
        except AttributeError:
            try:
                desc = self.description
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

    def __init__(self, pagerduty, policy):
        pygerduty.Incidents.__init__(self, pagerduty)
        self.container = Incident
        self.ops_policy = policy


    def all(self, **kwargs):
        for incident in self.list(**kwargs):
            import pdb; pdb.set_trace()
            if incident.escalation_policy.id == self.ops_policy:
                yield incident

    def wakeups(self, **kwargs):
        for incident in self.all(**kwargs):
            time = incident.pacific_time("created_at")
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
            created_at  = incident.pacific_time("created_at")
            last_status = incident.pacific_time("last_status_change_at")
            if last_status - created_at < timedelta(minutes=10) and not incident.last_status_change_by:
                if not [entry for entry in incident.log_entries.list() if entry.type == 'acknowledge']:
                    yield incident


class PagerDuty(pygerduty.v2.PagerDuty):

    def __init__(self, api_token, policy):
        pygerduty.v2.PagerDuty.__init__(self, api_token)
        self.incidents = Incidents(self, policy)

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
            created_at = incident.pacific_time("created_at")
            rslv_time  = incident.pacific_time("last_status_change_at")
            ttr = (rslv_time - created_at).total_seconds()
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
        created_at = incident.pacific_time("created_at")
        if not created_at.weekday() == 3:
            yield incident

def pprint_incidents(incidents):
    for incident in sorted(incidents, key=lambda x: x.pacific_time("created_at")):
        created = incident.iso_pac_time("created_at")
        interesting = tuple([incident.id, created, incident.get_description()])
        print "\t".join(interesting)

def pprint_rankings(rankings):
    for (desc, count) in sorted(rankings.keys(), key=lambda x: -x[1]):
        print "%s\t%s" % (str(count), desc)

def generate_html_ranking_file(rankings_prod, rankings_staging):
    tmp_file = open('tmp.txt', 'w')
    tmp_file.write("<html><p>Statistics for Prod Servers</p><table><thead><th>Count</th><th>Alarm</th><th>Incidents</th><th></th></thead><tbody>")
    for (desc, count) in sorted(rankings_prod.keys(), key=lambda x: -x[1]):
        incidents = rankings_prod[(desc,count)]
        tmp_file.write("<tr><td>" + "</td><td>".join((str(count), desc)) + "</td><td>" +
            incidents[0].link() + "</td><td>" + incidents[0].friendly_pac_time("created_at") + "</td></tr>")
        for incident in incidents[1:]:
            tmp_file.write("<tr><td></td><td></td><td>" + incident.link() + "</td><td>" +
                incident.friendly_pac_time("created_at") + "</td></tr>")
    tmp_file.write("</tbody></table>")
    tmp_file.write("<br><br><br><p>Statistics for Staging Servers</p><table><thead><th>Count</th><th>Alarm</th><th>Incidents</th><th></th></thead><tbody>")
    for (desc, count) in sorted(rankings_staging.keys(), key=lambda x: -x[1]):
        incidents = rankings_staging[(desc,count)]
        tmp_file.write("<tr><td>" + "</td><td>".join((str(count), desc)) + "</td><td>" +
            incidents[0].link() + "</td><td>" + incidents[0].friendly_pac_time("created_at") + "</td></tr>")
        for incident in incidents[1:]:
            tmp_file.write("<tr><td></td><td></td><td>" + incident.link() + "</td><td>" +
                incident.friendly_pac_time("created_at") + "</td></tr>")
    tmp_file.write("</tbody></table></html>")
    return tmp_file

def segregation(incidents):
   incident_list_staging = list()
   incident_list_prod = list()
   for incident in incidents:
        desc = incident.get_description()
        if ("staging" in desc):
            incident_list_staging.append(incident)
        else:
            incident_list_prod.append(incident)
   return (incident_list_prod, incident_list_staging)

def email_output(incident_prod, incident_staging, top_count=None):
    rankings_staging = top(incident_staging, top_count)
    rankings_prod = top(incident_prod, top_count)
    tmp_file = generate_html_ranking_file(rankings_prod, rankings_staging)
    print("Report-1: Statistics for Production Servers")
    pprint_incidents(incident_prod)
    print("\n")
    print("Report-2: Statistics for Staging Servers")
    pprint_incidents(incident_staging)


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

    pager = PagerDuty(argv['<api-token>'], argv['<policy>'])
    for command in ['all','wakeups','flakes']:
        if argv[command]:
            incidents = pager.do_list(command, argv['--no-thurs'], since=start, until=end)
            incident_list = list(incidents)
            (incident_list_prod, incident_list_staging)=segregation(incident_list)
            if incidents:
                if argv['--email']:
                    email_output(incident_list_prod, incident_list_staging, argv['--top'])
                elif argv['--top']:
                    pprint_rankings(top(incident_list_prod, argv['--top']))
                    pprint_rankings(top(incident_list_staging, argv['--top']))
                else:
                    pprint_incidents(incident_list_prod)
                    pprint_incidents(incident_list_staging)


    if argv['mtr']:
        print pager.get_mtr(since=start, until=end)

