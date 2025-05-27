import aw_client
import subprocess
import json
import logging
from time import time, sleep
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import re

from .config import config

## warning threshold for outdated data (TODO: move to the config file, give a better name?)
WARN_THRESHOLD=300
SLEEP_INTERVAL=120
MINIMUM_INTERVAL=20
MAXIMUM_NONCAT_INTERVAL=120

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

    def get_editor_tags(self, window_event):
        ## TODO: can we consolidate common code? I basically copied get_browser_tags and s/browser/editor/ and a little bit editing
        editor = window_event['data']['app'].lower()
        editor_id = self.bucket_short[f"aw-watcher-{editor}"]['id']
        editor_events = self.aw.get_events(editor_id, start=window_event['timestamp'], end=window_event['timestamp']+window_event['duration'])
        
        ## TODO this is maybe too simplistic
        editor_events.sort(key=lambda x: x['duration'])
        if not editor_events:
            ## emacs cruft
            if (re.match('^( )?\*.*\*', window_event['data']['title'])):
                return []

            print(f"No editor event found.  Window title: {window_event['data']['title']}")
            breakpoint()
            return []
        editor_event = editor_events[-1]

        for editor_rule_name in config.get('rules', {}).get('editor', {}):
            rule = config['rules']['editor'][editor_rule_name]
            for project in rule.get('projects', []):
                if(project == editor_event['data']['project']):
                    return rule['timew_tags'] + [ 'not-afk' ]
            if 'path_regexp' in rule:
                match = re.search(rule['path_regexp'], editor_event['data']['file'])
                if match:
                    tags = rule['timew_tags']
                    for tag in tags:
                        if '$1' in tag:
                            ## todo: support for $2, etc
                            tags.remove(tag)
                            tags.append(tag.replace('$1', match.group(1)))
                    return tags  + [ 'not-afk' ]
                
        print(f"Unhandled editor event.  File: {editor_event['data']['file']}")
        breakpoint()
        return []
        

    def get_browser_tags(self, window_event):
        browser = window_event['data']['app'].lower().replace('chromium', 'chrome')
        browser_id = self.bucket_short[f"aw-watcher-web-{browser}"]['id']
        browser_events = self.aw.get_events(browser_id, start=window_event['timestamp'], end=window_event['timestamp']+window_event['duration'])

        if not browser_events:
            print(f"No browser event found.  Window title: {window_event['data']['title']}")
            breakpoint()
            return []
            
        ## TODO this is maybe too simplistic
        browser_events.sort(key=lambda x: x['duration'])
        browser_event = browser_events[-1]
        
        for browser_rule_name in config.get('rules', {}).get('browser', {}):
            rule = config['rules']['browser'][browser_rule_name]
            if 'url_regexp' in rule:
                match = re.search(rule['url_regexp'], browser_event['data']['url'])
                if match:
                    tags = rule['timew_tags']
                    for tag in tags:
                        if '$1' in tag:
                            ## todo: support for $2, etc
                            tags.remove(tag)
                            tags.append(tag.replace('$1', match.group(1)))
                    return tags  + [ 'not-afk' ]
        if browser_event['data']['url'] in ('chrome://newtab/', 'about:newtab'):
            return []
        print(f"Unhandled browser event.  URL: {browser_event['data']['url']}")
        breakpoint()
        return []

    def get_app_tags(self, event):
        for apprulename in config['rules']['app']:
            rule = config['rules']['app'][apprulename]
            if event['data'].get('app') in rule['app_names']:
                title_regexp = rule.get('title_regexp')
                if title_regexp and not re.search(title_regexp, event['data'].get('title')):
                    continue
                tags = set()
                for tag in rule['timew_tags']:
                    if tag == '$app':
                        tag = event['data']['app']
                    tags.add(tag)
                tags.add('not-afk')
                return tags
        return []

    def find_next_activity(self):
        afk_id = self.bucket_by_client['aw-watcher-afk'][0]
        window_id = self.bucket_by_client['aw-watcher-window'][0]

        afk_events = self.aw.get_events(afk_id, start=self.last_tick)
        ## TODO
        ## workaround for https://github.com/ActivityWatch/aw-watcher-window-wayland/issues/41
        ## assume all gaps are afk
        if len(afk_events) == 0:
            afk_events = [{'data': {'status': 'afk'}, 'timestamp': self.last_tick, 'duration': timedelta(seconds=time.time()-self.last_tick)}]
        elif len(afk_events)>1: #and not any(x for x in afk_events if x['data']['status'] != 'not-afk'):
            afk_events.reverse()
            afk_events.sort(key=lambda x: x['timestamp'])
            for i in range(1, len(afk_events)):
                end = afk_events[i]['timestamp']
                start = afk_events[i-1]['timestamp'] + afk_events[i-1]['duration']
                duration = end-start
                if duration < timedelta(seconds=MINIMUM_INTERVAL):
                    continue
                afk_events.append({'data': {'status': 'afk'}, 'timestamp': start, 'duration': duration})
                
        afk_window_events = self.aw.get_events(window_id, start=self.last_tick) + afk_events
        afk_window_events.sort(key=lambda x: x['timestamp'])
        for event in afk_window_events:
            
            ## TODO - refactor better, this is a bit ugly, and references to timew should be abstracted out
            def timew_ensure(tags):
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
                timew_run(['start'] + list(tags) + [event['timestamp'].astimezone().strftime('%FT%H:%M:%S')])
                self.timew_info = timew_retag(get_timew_info())


            ## "overdue" means the current recorded activity may have stopped "long" ago.
            overdue = event['timestamp'] + event['duration'] - self.last_known_tick > timedelta(seconds=MAXIMUM_NONCAT_INTERVAL)

            ## TODO: consider the minimum interval of events yielding the same tags,
            ## so that i.e. frequent switching between editor and browser would not be ignored.
            if event['duration'].total_seconds() < MINIMUM_INTERVAL and not overdue:
                continue
            elif event['data'].get('status') == 'afk':
                if overdue:
                    timew_ensure('afk')
            elif event['data'].get('status') == 'not-afk':
                ## TODO: we should probably have a bit better handling of this one
                timew_ensure('not-afk')
            elif self.get_app_tags(event): ## inelegant - running the algorithm twice
                timew_ensure(self.get_app_tags(event))
            elif event['data'].get('app', '').lower() in ('chromium', 'firefox', 'chrome'):
                timew_ensure(self.get_browser_tags(event))
            elif event['data'].get('app', '').lower() in ('emacs', 'vi', 'vim'): ## todo - complete the list
                timew_ensure(self.get_editor_tags(event))
            elif event['data'].get('app', '').lower() in ('foot', 'xterm', ...): ## TODO: complete the list
                if overdue:
                    import pdb; pdb.set_trace()
                    timew_ensure({'unknown', 'not-afk'})
                ## TODO - can we extract anything from this?  We'd need a terminal watcher?
                pass
            else:
                print("Unrecognized event")
                breakpoint()
            self.last_tick = event['timestamp']-timedelta(seconds=1)
            print(self.last_tick.astimezone().strftime("%H:%M"))

    def tick(self):
        self.timew_info = timew_retag(get_timew_info())
        if not self.last_tick:
            self.last_tick = self.timew_info['start_dt']
            self.last_known_tick = self.last_tick
        self.find_next_activity()

def check_bucket_updated(bucket: dict):
    if time()-bucket['last_updated_dt'].timestamp() > WARN_THRESHOLD:
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
    print("Going to run:")
    print(f"   {" ".join(commands)}")
    subprocess.run(commands)
    print("Use timew undo if you don't agree!")
    breakpoint()

def timew_retag(timew_info):
    source_tags = set(timew_info['tags'])
    new_tags = source_tags.copy()
    for tag_section in config['tags']:
        retags = config['tags'][tag_section]
        if source_tags.intersection(set(retags['source_tags'])):
            new_tags = new_tags.union(set(retags.get('add', [])))

    if new_tags != source_tags:
        print("retagging existing event")
        timew_run(["retag"] + list(new_tags))
        timew_info = get_timew_info()
        assert set(timew_info['tags']) == new_tags
        return timew_retag(timew_info)
    return timew_info

def main():
    exporter = Exporter()
    while True:
        exporter.tick()
        sleep(SLEEP_INTERVAL)

if __name__ == '__main__':
    main()
