import aw_client
import subprocess
import json
import logging
from time import time, sleep
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from termcolor import cprint
import re
import os

from .config import config

## Those should be moved to config.py before releasing.  Possibly renamed.
AW_WARN_THRESHOLD=300 ## the recent data from activity watch should not be elder than this
SLEEP_INTERVAL=3 ## Sleeps between each run when the program is run in real-time
IGNORE_INTERVAL=5 ## ignore any window visits lasting for less than five seconds (TODO: may need tuning if terminal windows change title for every command run)
MIN_RECORDING_INTERVAL=60 ## Never record an activities more frequently than once per minute.
MIN_TAG_RECORDING_INTERVAL=30 ## When recording something, include every tag that has been observed for more than 30s
STICKYNESS_FACTOR=0.25 ## Don't reset everything on each "tick".
MAX_MIXED_INTERVAL=180 ## Any window event lasting for more than three minutes should be considered independently from what you did before and after

GRACE_TIME=float(os.environ.get('GRACE_TIME') or 10)

SPECIAL_TAGS={'manual', 'override', 'not-afk'}

def ts2str(ts, format="%FT%H:%M"):
    return(ts.astimezone().strftime(format))

def ts2strtime(ts):
    if not ts:
        return "XX:XX"
    return ts2str(ts, "%H:%M")

class Exporter:
    def __init__(self):
        self.last_tick = None
        self.aw = aw_client.ActivityWatchClient(client_name="timewarrior_export")
        self.buckets = self.aw.get_buckets()
        self.bucket_by_client = defaultdict(list)
        self.bucket_short = {}
        for x in self.buckets:
            self.buckets[x]['last_updated_dt'] = datetime.fromisoformat(self.buckets[x]['last_updated'])
            client = self.buckets[x]['client']
            self.bucket_by_client[client].append(x)
            bucket_short = x[:x.find('_')]
            assert not bucket_short in self.bucket_short
            self.bucket_short[bucket_short] = self.buckets[x]
        for bucketclient in ('aw-watcher-window', 'aw-watcher-afk'):
            assert bucketclient in self.bucket_by_client
            for b in self.bucket_by_client[bucketclient]:
                check_bucket_updated(self.buckets[b])

    def log(self, msg, ts=None, attrs=[]):
        cprint(f"{ts2strtime(ts)} (tracking from {ts2strtime(self.timew_info['start_dt'])}: {self.timew_info['tags']}): {msg}", attrs=attrs)

    def get_editor_tags(self, window_event):
        ## TODO: can we consolidate common code? I basically copied get_browser_tags and s/browser/editor/ and a little bit editing
        if window_event['data'].get('app', '').lower() not in ('emacs', 'vi', 'vim', ...): ## TODO - complete the list
            return False
        editor = window_event['data']['app'].lower()
        editor_id = self.bucket_short[f"aw-watcher-{editor}"]['id']
        editor_events = self.aw.get_events(editor_id, start=window_event['timestamp'], end=window_event['timestamp']+window_event['duration'])
        
        ## TODO this is maybe too simplistic
        editor_events.sort(key=lambda x: x['duration'])
        if not editor_events:
            ## emacs cruft
            if (re.match(r'^( )?\*.*\*', window_event['data']['title'])):
                return []

            self.log("No editor event found.  Window title: {window_event['data']['title']}", window_event['timestamp'])
            return []
        editor_event = editor_events[-1]

        for editor_rule_name in config.get('rules', {}).get('editor', {}):
            rule = config['rules']['editor'][editor_rule_name]
            for project in rule.get('projects', []):
                if(project == editor_event['data']['project']):
                    ret = set(rule['timew_tags'])
                    ret.add('not-afk')
                    return ret
            if 'path_regexp' in rule:
                match = re.search(rule['path_regexp'], editor_event['data']['file'])
                if match:
                    tags = set(rule['timew_tags'])
                    for tag in tags:
                        if '$1' in tag:
                            ## todo: support for $2, etc
                            tags.remove(tag)
                            tags.add(tag.replace('$1', match.group(1)))
                    tags.add('not-afk')
                    return tags
                
        self.log(f"Unhandled editor event.  File: {editor_event['data']['file']}", window_event['timestamp'], attrs=["bold"])
        return []
        

    def get_browser_tags(self, window_event):
        if not window_event['data'].get('app', '').lower() in ('chromium', 'firefox', 'chrome', ...): ## TODO - complete the list
            return False

        browser = window_event['data']['app'].lower().replace('chromium', 'chrome')
        browser_id = self.bucket_short[f"aw-watcher-web-{browser}"]['id']
        browser_events = self.aw.get_events(browser_id, start=window_event['timestamp'], end=window_event['timestamp']+window_event['duration'])

        if not browser_events:
            self.log(f"No browser event found.  Window title: {window_event['data']['title']}", window_event['timestamp'])
            return []
            
        ## TODO this is maybe too simplistic
        browser_events.sort(key=lambda x: x['duration'])
        browser_event = browser_events[-1]
        
        for browser_rule_name in config.get('rules', {}).get('browser', {}):
            rule = config['rules']['browser'][browser_rule_name]
            if 'url_regexp' in rule:
                match = re.search(rule['url_regexp'], browser_event['data']['url'])
                if match:
                    tags = set(rule['timew_tags'])
                    for tag in tags:
                        if '$1' in tag:
                            ## todo: support for $2, etc
                            tags.remove(tag)
                            try:
                                tags.add(tag.replace('$1', match.group(1)))
                            except IndexError:
                                pass
                    tags.add('not-afk')
                    return tags
        if browser_event['data']['url'] in ('chrome://newtab/', 'about:newtab'):
            return []
        self.log(f"Unhandled browser event.  URL: {browser_event['data']['url']}", window_event['timestamp'], attrs=["bold"])
        return []

    def get_app_tags(self, event):
        for apprulename in config['rules']['app']:
            rule = config['rules']['app'][apprulename]
            group = None
            if event['data'].get('app') in rule['app_names']:
                title_regexp = rule.get('title_regexp')
                if title_regexp:
                    match = re.search(title_regexp, event['data'].get('title'))
                    if match:
                        try:
                            group = match.group(1)
                        except:
                            group = None
                    else:
                        continue
                tags = set()
                for tag in rule['timew_tags']:
                    if tag == '$app':
                        tag = event['data']['app']
                    if tag == '$1':
                        tag = group
                    if tag:
                        tags.add(tag)
                tags.add('not-afk')
                return tags
        return False


    def get_afk_tags(self, event):
        if 'status' in event['data']:
            return { event['data']['status'] }
        else:
            return False

    def find_tags_from_event(self, event):
        if event['duration'].total_seconds() < IGNORE_INTERVAL:
            return

        for method in (self.get_app_tags, self.get_browser_tags, self.get_afk_tags, self.get_editor_tags):
            tags = method(event)
            if tags is not False:
                break
        return tags
    
    def find_next_activity(self):
        afk_id = self.bucket_by_client['aw-watcher-afk'][0]
        window_id = self.bucket_by_client['aw-watcher-window'][0]
        tags_accumulated_time = defaultdict(timedelta)

        afk_events = self.aw.get_events(afk_id, start=self.last_tick)
        ### START WORKAROUND
        ## TODO
        ## workaround for https://github.com/ActivityWatch/aw-watcher-window-wayland/issues/41
        ## assume all gaps are afk
        if len(afk_events) == 0:
            afk_events = [{'data': {'status': 'afk'}, 'timestamp': self.last_tick, 'duration': timedelta(seconds=time()-self.last_tick.timestamp())}]
        elif len(afk_events)>1: #and not any(x for x in afk_events if x['data']['status'] != 'not-afk'):
            afk_events.reverse()
            afk_events.sort(key=lambda x: x['timestamp'])
            for i in range(1, len(afk_events)):
                end = afk_events[i]['timestamp']
                start = afk_events[i-1]['timestamp'] + afk_events[i-1]['duration']
                duration = end-start
                if duration.total_seconds() < MIN_RECORDING_INTERVAL:
                    continue
                afk_events.append({'data': {'status': 'afk'}, 'timestamp': start, 'duration': duration})
        ### END WORKAROUND
        afk_window_events = self.aw.get_events(window_id, start=self.last_tick) + afk_events
        afk_window_events.sort(key=lambda x: x['timestamp'])
        for event in afk_window_events:

            def timew_ensure(tags, since=event['timestamp']):
                if tags != 'not-afk':
                    self.last_known_tick = event['timestamp'] + event['duration']
                self.timew_info = timew_retag(get_timew_info())
                if isinstance(tags, str):
                    tags = { tags }
                if 'override' in self.timew_info['tags']:
                    return
                if 'manual' in self.timew_info['tags'] and 'unknown' in tags:
                    return
                if set(tags).issubset(self.timew_info['tags']):
                    return
                tags = retag_by_rules(tags)
                assert not exclusive_overlapping(tags)
                timew_run(['start'] + list(tags) + [since.astimezone().strftime('%FT%H:%M:%S')])
                self.timew_info = timew_retag(get_timew_info())

            tags = self.find_tags_from_event(event)

            print(f"{self.last_tick.astimezone().strftime("%H:%M")} - {event['duration'].total_seconds()}s duration, {event['data']} - tags found: {tags}")
            
            if tags == { 'not-afk' }:
                self.last_known_tick = event['timestamp']
                tags = []

            ## Ref README, if MAX_MIXED_INTERVAL is met, ignore accumulated minor activity
            ## (the mixed time will be attributed to the previous work task)
            if tags and event['duration'].total_seconds() > MAX_MIXED_INTERVAL:
                tags_accumulated_time = defaultdict(timedelta)
                timew_ensure(tags)

            interval_since_last_known_tick = event['timestamp'] + event['duration'] - self.last_known_tick

            ## Track things in internal accumulator if the focus between windows changes often
            if tags:
                tags = retag_by_rules(tags)
                for tag in tags:
                    tags_accumulated_time[tag] += event['duration']
                
            if interval_since_last_known_tick.total_seconds() > MIN_RECORDING_INTERVAL and any(x for x in tags_accumulated_time if x not in SPECIAL_TAGS and tags_accumulated_time[x].total_seconds()>MIN_RECORDING_INTERVAL):
                tags = set()
                assert not exclusive_overlapping(tags)
                min_tag_recording_interval=MIN_TAG_RECORDING_INTERVAL
                while exclusive_overlapping(set([tag for tag in tags_accumulated_time if  tags_accumulated_time[tag].total_seconds() > min_tag_recording_interval])):
                    min_tag_recording_interval += 1
                for tag in tags_accumulated_time:
                    if tags_accumulated_time[tag].total_seconds() > min_tag_recording_interval:
                        tags.add(tag)
                        if ('oss-contrib' in tags and 'entertainment' in tags):
                            breakpoint()
                            exclusive_overlapping(tags)
                    tags_accumulated_time[tag] *= STICKYNESS_FACTOR
                ## TODO: if `timew start` was run manually, then repopulate tags_accumulated_time to ensure sticiness of manually recorded tags
                timew_ensure(tags, self.last_known_tick)

            self.last_tick = event['timestamp']-timedelta(seconds=1)

            if tags is not False:
                pass
            
            elif event['data'].get('app', '').lower() in ('foot', 'xterm', ...): ## TODO: complete the list
                self.log(f"Unknown terminal event {event['data']['title']}", event['timestamp'], attrs=["bold"])
            else:
                self.log(f"No rules found for event {event['data']}", event['timestamp'], attrs=["bold"])

    def tick(self):
        self.timew_info = timew_retag(get_timew_info())
        if not self.last_tick:
            self.last_tick = self.timew_info['start_dt']
            self.last_known_tick = self.last_tick
        self.find_next_activity()

def check_bucket_updated(bucket: dict):
    if time()-bucket['last_updated_dt'].timestamp() > AW_WARN_THRESHOLD:
        logging.warning(f"Bucket {bucket['id']} seems not to have recent data!")

## TODO: none of this has anything to do with ActivityWatch and can be moved to a separate module
def get_timew_info():
    ## TODO: this will break if there is no active tracking
    current_timew = json.loads(subprocess.check_output(["timew", "get", "dom.active.json"]))
    dt = datetime.strptime(current_timew['start'], "%Y%m%dT%H%M%SZ")
    dt = dt.replace(tzinfo=timezone.utc)
    current_timew['start_dt'] = dt
    current_timew['tags'] = set(current_timew['tags'])
    return current_timew

def timew_run(commands):
    commands = ['timew'] + commands
    print("Running:")
    print(f"   {" ".join(commands)}")
    subprocess.run(commands)
    cprint(f"Use timew undo if you don't agree!  You have {GRACE_TIME} seconds to press ctrl^c", attrs=["bold"])
    sleep(GRACE_TIME)

def exclusive_overlapping(tags):
    for gid in config['exclusive']:
        group = set(config['exclusive'][gid]['tags'])
        if len(group.intersection(tags)) > 1:
            return True
    return False

## not really retag, more like expand tags?
def retag_by_rules(source_tags):
    assert not exclusive_overlapping(source_tags)
    new_tags = source_tags.copy()
    for tag_section in config['tags']:
        retags = config['tags'][tag_section]
        if source_tags.intersection(set(retags['source_tags'])):
            new_tags_ = new_tags.union(set(retags.get('add', [])))
            if exclusive_overlapping(new_tags_):
                logging.warning(f"Excluding expanding tag rule {tag_section} due to exclusivity conflicts")
            else:
                new_tags = new_tags_
    if new_tags != source_tags:
        ## We could end up doing infinite recursion here
        ## TODO: add some recursion-safety here?
        return retag_by_rules(new_tags)
    return new_tags

def timew_retag(timew_info):
    source_tags = set(timew_info['tags'])
    new_tags = retag_by_rules(source_tags)
    if new_tags != source_tags:
        timew_run(["retag"] + list(new_tags))
        timew_info = get_timew_info()
        assert set(timew_info['tags']) == new_tags
        return timew_info
    return timew_info

def main():
    exporter = Exporter()
    while True:
        exporter.tick()
        sleep(SLEEP_INTERVAL)

if __name__ == '__main__':
    main()
