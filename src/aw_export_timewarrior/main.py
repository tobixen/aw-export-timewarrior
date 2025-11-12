import aw_client
import subprocess
import json
import logging
from time import time, sleep
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from collections import defaultdict
from termcolor import cprint
import re
import os

## We have lots of breakpoints in the code.  Remove this line while debugging/developing ...
breakpoint = lambda: None

## TODO: logging sucks a bit and should be rethought thoroughly

from .config import config

## Those should be moved to config.py before releasing.  Possibly renamed.
AW_WARN_THRESHOLD=float(os.environ.get('AW2TW_AW_WARN_THRESHOLD') or 300) ## the recent data from activity watch should not be elder than this
SLEEP_INTERVAL=float(os.environ.get('AW2TW_SLEEP_INTERVAL') or 30) ## Sleeps between each run when the program is run in real-time
IGNORE_INTERVAL=float(os.environ.get('AW2TW_IGNORE_INTERVAL') or 3) ## ignore any window visits lasting for less than five seconds (TODO: may need tuning if terminal windows change title for every command run)
MIN_RECORDING_INTERVAL=float(os.environ.get('AW2TW_MIN_RECORDING_INTERVAL') or 90) ## Never record an activities more frequently than once per minute.
MIN_TAG_RECORDING_INTERVAL=float(os.environ.get('AW2TW_MIN_TAG_RECORDING_INTERVAL') or 50) ## When recording something, include every tag that has been observed for more than 50s
STICKYNESS_FACTOR=float(os.environ.get('AW2TW_STICKYNESS_FACTOR') or 0.2) ## Don't reset everything on each "tick".
MAX_MIXED_INTERVAL=float(os.environ.get('AW2TW_MAX_MIXED_INTERVAL') or 240) ## Any window event lasting for more than four minutes should be considered independently from what you did before and after

GRACE_TIME=float(os.environ.get('AW2TW_GRACE_TIME') or 10)

SPECIAL_TAGS={'manual', 'override', 'not-afk'}

MIN_RECORDING_INTERVAL_ADJ=MIN_RECORDING_INTERVAL*(1+STICKYNESS_FACTOR)
MIN_TAG_RECORDING_INTERVAL_ADJ=MIN_TAG_RECORDING_INTERVAL*(1+STICKYNESS_FACTOR)


def ts2str(ts, format="%FT%H:%M:%S"):
    return(ts.astimezone().strftime(format))

def ts2strtime(ts):
    if not ts:
        return "XX:XX:XX:"
    return ts2str(ts, "%H:%M:%S")

## We keep quite some statistics here, all the counters should be documented
## TODO: Resetting counters should be done through explicit methods in this class and
## not through arbitrary assignments in unrelated methods
@dataclass
class Exporter:
    ## self.tags_accumulated_time is a time counter for each tags that has been observed.
    ## When enough time has been counted, we'll look through and run ensure_tag_exported on the tags that has accumulated most time.
    ## self.tags_accumulated_time is cleared ...
    ## 1) when coming/going afk/not-afk
    ## 3) when some event has been going on for MAX_MIXED_INTERVAL
    ## 4) when some mixed events is recorded, the numbers are reduced - we
    ## spill over some of the content to the next recording interval, to reduce flapping
    tags_accumulated_time: defaultdict = field(default_factory=lambda: defaultdict(timedelta))
    
    ## Last tick is updated all the time.  It's the end time of the last event handled.
    ## Used for determinating when we should start fetching window information
    last_tick: datetime = None

    ## last known tick is the end time of the last event causing tags to be "ensured"
    ## (that is, exported if needed).  Should be set in the ensure algorithm.
    last_known_tick: datetime = None

    ## last known start time is the start time of the last event causing tags to be "ensured".
    ## (that is, exported if needed).  Should be set in the ensure algorithm.
    last_start_time: datetime = None

    ## Assume we're afk when script is started ... but ... why?
    afk: bool = None
    
    ## total_time_known_events is summing up the time spent on
    ## tag-generating activities since last time a tag was
    ## recorded.  So it should be nulled out only when ensure_tag
    ## is run It is useful for debugging; if
    ## total_time_known_events is very low compared to the time
    ## since last known tick, then something is wrong.
    total_time_known_events: timedelta = timedelta(0)

    ## Special case when one has just arrived to the computer.  It's
    ## important that all the not-afk time is tagged up.  Should be
    ## not-None only when the time hasn't been tagged yet.  TODO:
    ## better naming?
    last_not_afk: datetime = None

    ## manual_tracking is set to True whenever you have used timew manually
    manual_tracking: bool = True

    ## Information from timew about the current tagging
    timew_info: dict = None
    
    ## This is not quite reliable
    total_time_unknown_events: timedelta = timedelta(0)

    def __post_init__(self):
        ## data fetching
        self.aw = aw_client.ActivityWatchClient(client_name="timewarrior_export")
        self.buckets = self.aw.get_buckets()
        self.bucket_by_client = defaultdict(list)
        self.bucket_short = {}

        for x in self.buckets:
            lu = self.buckets[x].get('last_updated')
            self.buckets[x]['last_updated_dt'] = datetime.fromisoformat(lu) if lu else None
            client = self.buckets[x]['client']
            self.bucket_by_client[client].append(x)
            bucket_short = x[:x.find('_')]
            assert not bucket_short in self.bucket_short
            self.bucket_short[bucket_short] = self.buckets[x]
        for bucketclient in ('aw-watcher-window', 'aw-watcher-afk'):
            assert bucketclient in self.bucket_by_client
            for b in self.bucket_by_client[bucketclient]:
                check_bucket_updated(self.buckets[b])

    def set_known_tick_stats(self, event=None, start=None, end=None, manual=False, tags=None, reset_accumulator=False, retain_accumulator=True):
        if event and not start:
            start = event['timestamp']
        if event and not end:
            end = event['timestamp'] + event['duration']
        if start and not end:
            end = start
        self.last_known_tick = end
        self.last_tick = end
        self.last_start_time = start
        self.manual_tracking = manual
        self.total_time_unknown_events = timedelta(0)
        if reset_accumulator:
            self.tags_accumulated_time = defaultdict(timedelta)
            if retain_accumulator:
                for tag in tags:
                    self.tags_accumulated_time[tag] = STICKYNESS_FACTOR*MIN_RECORDING_INTERVAL
        self.total_time_known_events = timedelta(0)                


    ## TODO: move all dealings with statistics to explicit statistics-handling methods
    def ensure_tag_exported(self, tags, event, since=None):
        if since is None:
            since = event['timestamp']

        if isinstance(tags, str):
            tags = { tags }

        ## Now, the previously tagged thing has been running (at least) since self.last_known_tick,
        ## no matter if we have activity supporting it or not since self.last_known_tick.
        last_activity_run_time = since - self.last_start_time

        ## We'd like to compare with self.total_time_known_event, but it's counted from the end of the previous event to the end of the current event
        tracked_gap = event['timestamp'] + event['duration'] - self.last_known_tick

        ## if the time tracked is significantly less than the minimum
        ## time we're supposed to track, something is also probably
        ## wrong and should be investigated
        if tags != { 'afk' } and not self.afk and not self.manual_tracking and last_activity_run_time.total_seconds() < MIN_RECORDING_INTERVAL-3:
            breakpoint()

        ## If the tracked time is less than the known events time we've counted
        ## then something is a little bit wrong.
        if tags != { 'afk' } and tracked_gap < self.total_time_known_events:
            breakpoint()

        ## If he time tracked is way longer than the
        ## self.total_time_known_events, something is probably wrong
        ## and should be investigated
        if tags != { 'afk' } and tracked_gap.total_seconds()>MAX_MIXED_INTERVAL and self.total_time_known_events/tracked_gap < 0.3 and not self.manual_tracking:
            breakpoint()

        if 'afk' in tags:
            self.afk = True

        self.set_known_tick_stats(event=event, start=since)
        self.set_timew_info(timew_retag(get_timew_info()))

        ## Special logic with 'override', 'manual' and 'unknown' should be documented or removed!
        if 'override' in self.timew_info['tags']:
            return
        if 'manual' in self.timew_info['tags'] and 'unknown' in tags:
            return
        if set(tags).issubset(self.timew_info['tags']):
            return
        tags = retag_by_rules(tags)
        assert not exclusive_overlapping(tags)
        timew_run(['start'] + list(tags) + [since.astimezone().strftime('%FT%H:%M:%S')])
        self.set_timew_info(timew_retag(get_timew_info()))

    def pretty_accumulator_string(self):
        a = self.tags_accumulated_time
        tags = [x for x in a if a[x].total_seconds() > MIN_TAG_RECORDING_INTERVAL]
        tags.sort(key=lambda x: -a[x])
        return "\n".join([f"{x}: {a[x].total_seconds():5.1f}s" for x in tags])
        
    ## TODO: rethink logging and remove all logging done through "print" everywhere in the code
    ## TODO: some logs are hard-coded to be bold through attrs.  We should rather use the standard loglevel approach.  For printing to the screen, warnings may be bold, errors and criticals blinking, etc
    ## TODO: why not use the python logging library?
    def log(self, msg, tags=None, event=None, ts=None, attrs=[]):
        ## temp!
        #print(self.pretty_accumulator_string())
        if event and not ts:
            ts = event['timestamp']
        dur = ""
        if event:
            dur = f"+ {event['duration'].total_seconds():6.1f}s"
        cprint(f"{ts2strtime(datetime.now())} / {ts2strtime(self.last_tick)} / {ts2strtime(ts)}{dur}: {msg}", attrs=attrs)

    def get_editor_tags(self, window_event):
        ## TODO: can we consolidate common code? I basically copied get_browser_tags and s/browser/editor/ and a little bit editing
        if window_event['data'].get('app', '').lower() not in ('emacs', 'vi', 'vim', ...): ## TODO - complete the list
            return False
        editor = window_event['data']['app'].lower()
        editor_id = self.bucket_short[f"aw-watcher-{editor}"]['id']
        ## emacs cruft
        ignorable = re.match(r'^( )?\*.*\*', window_event['data']['title'])
        editor_event = self.get_corresponding_event(
            window_event, editor_id, ignorable=ignorable)
        
        if not editor_event:
            return []

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
                    for tag in list(tags):
                        if '$1' in tag:
                            ## todo: support for $2, etc
                            tags.remove(tag)
                            if len(match.groups())>0:
                                tags.add(tag.replace('$1', match.group(1)))
                    tags.add('not-afk')
                    return tags
                
        self.log(f"Unhandled editor event.  File: {editor_event['data']['file']}", event=window_event, attrs=["bold"])
        return []

    ## TODO - remove hard coded constants!
    def get_corresponding_event(self, window_event, event_type_id, ignorable=False, retry=6):
        ret = self.aw.get_events(event_type_id, start=window_event['timestamp']-timedelta(seconds=1), end=window_event['timestamp']+window_event['duration'])

        ## If nothing found ... try harder
        if not ret and not ignorable and retry:
            ## Perhaps the event hasn't reached ActivityWatch yet?  Perhaps it helps to sleep?
            ## Obviously, it may only help if the wall clock matches the event time
            if time() - SLEEP_INTERVAL*3 < (window_event['timestamp'] + window_event['duration']).timestamp():
                self.log(f"Event details for {window_event} not in yet, attempting to sleep for a while", event=window_event)
                sleep(SLEEP_INTERVAL*3/retry+0.2)
                retry -= 1
                return self.get_corresponding_event(window_event, event_type_id, ignorable, retry)
        
        if not ret and not ignorable:
            ret = self.aw.get_events(event_type_id, start=window_event['timestamp']-timedelta(seconds=15), end=window_event['timestamp']+window_event['duration']+timedelta(seconds=15))
        if not ret:
            if not ignorable and not window_event['duration']<timedelta(seconds=IGNORE_INTERVAL*4):
                self.log(f"No corresponding {event_type_id} found.  Window title: {window_event['data']['title']}.  If you see this often, you should verify that the relevant watchers are active and running.", event=window_event)
            return None
        if len(ret)>1:
            ret2 = [x for x in ret if x.duration > timedelta(seconds=IGNORE_INTERVAL)]
            if ret2:
                ret = ret2
            ## TODO this is maybe too simplistic
            ret.sort(key=lambda x: -x['duration'])
        return ret[0]

    def get_browser_tags(self, window_event):
        if not window_event['data'].get('app', '').lower() in ('chromium', 'firefox', 'chrome', ...): ## TODO - complete the list
            return False

        browser = window_event['data']['app'].lower().replace('chromium', 'chrome')
        browser_id = self.bucket_short[f"aw-watcher-web-{browser}"]['id']
        browser_event = self.get_corresponding_event(window_event, browser_id)

        if not browser_event:
            ## TODO: deal with this.  There should be a browser event?  It's just the start/end that is misset?
            return []

        for browser_rule_name in config.get('rules', {}).get('browser', {}):
            rule = config['rules']['browser'][browser_rule_name]
            if 'url_regexp' in rule:
                match = re.search(rule['url_regexp'], browser_event['data']['url'])
                if match:
                    tags = set(rule['timew_tags'])
                    for tag in list(tags):
                        if '$1' in tag:
                            ## todo: support for $2, etc
                            tags.remove(tag)
                            if len(match.groups())>0:
                                if match.group(1) is None:
                                    breakpoint()
                                tags.add(tag.replace('$1', match.group(1)))
                    tags.add('not-afk')
                    return tags
            else:
                self.log(f"Weird browser rule {browser_rule_name}")
        if browser_event['data']['url'] in ('chrome://newtab/', 'about:newtab'):
            return []
        self.log(f"Unhandled browser event.  URL: {browser_event['data']['url']}", event=window_event, attrs=["bold"])
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
                        tags.add(event['data']['app'])
                    elif '$1' in tag and group:
                        tags.add(tag.replace('$1', group))
                    elif not '$' in tag:
                        tags.add(tag)
                tags.add('not-afk')
                return tags
        return False


    def get_afk_tags(self, event):
        if 'status' in event['data']:
            return { event['data']['status'] }
        else:
            return False

    def _afk_change_stats(self, afk, tags, event):
        """
        Internal method used from check_and_handle_afk_state_change.
        Reset statistics counters when coming/going afk
        
        TODO: self.afk should ONLY be set here and on initialization
        """
        if tags == { 'afk' }:
            ## This event may overlap other events.
            ## We should ignore all other overlapping events, the afk tag
            ## takes precedence.
            ## By setting last_known_tick to the end of the afk event
            ## we mark up that the activity up until then is known.
            ## (This is redundant, if the afk event is also exported).
            self.last_known_tick = event['timestamp'] + event['duration']
            self.last_tick = self.last_known_tick
        elif tags == { 'not-afk' }:
            ## This event may overlap other events.
            ## The duration of this event should be ignored.
            ## The below statements should be kind of redundant, possibly harmful
            ## if we have extra not-afk events, so they are commented out:
            #self.last_tick = event['timestamp']
            #self.last_known_tick = self.last_tick
            ## All time since the start of the not-afk event should be tracked.
            ## We keep a special counter on this.
            self.last_not_afk = event['timestamp']
            ## TODO: the statistic above should be honored
        self.tags_accumulated_time = defaultdict(timedelta)
        ## TODO - there is more to be done, isn't it?  Or perhaps not?
        self.afk = afk=='afk'

    def check_and_handle_afk_state_change(self, tags, event=None):
        """
        * Checks if I've gone afk or returned to keyboard
        * Resets the statistics that should be reset if I'm coming or leaving
        * Exports the tracking, if applicable
        * Returns False if the event/tags needs further handling
        * Returns True if all logic has been handled in this function, meaning that the event/tags does not need further handling
        """
        if not tags: ## Not much to do here.  Except, we could verify that the event is compatible with the self.afk setting
            return False
        if 'afk' in tags and 'not-afk' in tags:
            ## Those are exclusive, should not happen!
            breakpoint()
        if self.afk is None:
            ## Program has just been started, and we don't know if we're afk or not
            if 'afk' in tags:
                self.afk = True
            if 'not-afk' in tags:
                self.afk = False
            ## unless tags are { 'afk' } or { 'non-afk' } we'll return False
            ## to indicate that we haven't handled any state change, and that
            ## the tags still needs handling
            return self.afk is not None and len(tags) == 1
        if self.afk:
            if tags == { 'afk' }:
                ## This should probably be checked up ... we're already afk, but now
                ## we got a new afk tag?
                ## (possible reason: we had some few tags in between the afk runs, but without any tags)
                breakpoint()
                self._afk_change_stats('afk', tags, event)
                return True
            if not 'afk' in self.timew_info['tags']:
                ## I'm apparently afk, but we're not tracking it in timew?
                ## Something must have gone wrong somewhere?
                breakpoint()
            if 'not-afk' in tags:
                self._afk_change_stats('not-afk', tags, event)
                self.log(f"You have returned to the keyboard after {(event['timestamp']-self.last_start_time).total_seconds()}s absence", event=event)
                if tags != { 'not-afk' }:
                    ## Some possibilities:
                    ## 1) We have returned from the keyboard without the 'not-afk' special event triggered?
                    ## 2) We're catching up some "ghost tracking" of window events while we're afk?
                    ## 3) The 'not-afk' special event is not in the right order in the event queue?
                    ## 4) The data from the afk/not-afk watcher is unreliable
                    ## I think I found out that 3 is normal, but we may want to investigate TODO
                    return False
                else:
                    return True
        else: ## We're not afk
            if tags == { 'not-afk' }:
                ## Check this up manually.  Possibilities:
                ## 1) We're wrongly marked as 'not-afk' while we've actually been afk
                ## 2) The 'not-afk' special event is not in the right order in the event queue?
                ## 3) The data from the afk/not-afk watcher is unreliable
                ## I think I found 2 is normal, but we may want to investigate TODO
                return True
            elif tags == { 'afk' }:
                ## Meaning we've just gone afk.
                self.ensure_tag_exported(tags, event)
                self._afk_change_stats('afk', tags, event)
                self.log(f"You're going to be afk for at least {event['duration']}s", event=event)
                return True
            elif 'afk' in tags:
                ## We've gone afk ... in some weird way?
                self._afk_change_stats('afk', tags, event)
                breakpoint()
                return False
            else:
                ## We're not afk and we've not gone afk
                return False

        return False



    ## TODO: this is a bit messy - this will return None if the event is small
    ## enough to be found "ignorable" and False if no tags are found
    ## Otherwise a set of tags
    def find_tags_from_event(self, event):
        if event['duration'].total_seconds() < IGNORE_INTERVAL:
            return None

        for method in (self.get_afk_tags, self.get_app_tags, self.get_browser_tags, self.get_editor_tags):
            tags = method(event)
            if tags is not False:
                break
        return tags
    
    def find_next_activity(self):
        afk_id = self.bucket_by_client['aw-watcher-afk'][0]
        window_id = self.bucket_by_client['aw-watcher-window'][0]

        ## TODO: move all statistics from internal counters and up to the object
        
        
        ## Skipped events are events that takes so little time that we ignore it completely.
        ## The counter is nulled out when some non-skipped event comes in.
        ## Used only for debug logging.
        num_skipped_events = 0

        ## Unknown events are events lasting for some time, but without any
        ## rules identifying any tags.
        ## Nulled out only at the beginning of the function
        num_unknown_events = 0

        total_time_skipped_events = timedelta(0)

        ## just to make sure we won't lose any events
        #self.last_tick = self.last_tick - timedelta(1)
        
        afk_events = self.aw.get_events(afk_id, start=self.last_tick)
        
        ### START WORKAROUND
        ## TODO
        ## workaround for https://github.com/ActivityWatch/aw-watcher-window-wayland/issues/41
        ## assume all gaps are afk
        #if len(afk_events) == 0:
            #afk_events = [{'data': {'status': 'afk'}, 'timestamp': self.last_tick, 'duration': timedelta(seconds=time()-self.last_tick.timestamp())}]
        if len(afk_events)>1: #and not any(x for x in afk_events if x['data']['status'] != 'not-afk'):
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

        ## afk and window_events
        afk_window_events = self.aw.get_events(window_id, start=self.last_tick) + afk_events
        afk_window_events.sort(key=lambda x: x['timestamp'])
        if len(afk_window_events)<2:
            return False
        ## The last event on the list is unreliable, as it's about non-ended events
        afk_window_events.pop()

        cnt = 0
        for event in afk_window_events[:-1]:
            if event['timestamp'] < self.last_tick or event['timestamp'] < self.last_known_tick:
                self.log(f"skipping event as the timestamp is too old - {event}", event=event)
            tags = self.find_tags_from_event(event)

            ## Handling afk/not-afk
            if self.check_and_handle_afk_state_change(tags, event):
                ## TODO:
                ## Doh!  Some of the point of moving things to a separate
                ## function is to avoid the below logic here
                ## Returning after handling { 'not-afk' }
                ## and we'll come back and pick up the same event again!
                ## continue after handling { 'afk' } and
                ## we will pick up "ghost" events that should be
                ## ignored.  (we could add some logic to skip handled or skippable events)
                if self.afk:
                    return True
                continue

            if tags:
                self.total_time_known_events += event['duration']

            ## tags can be False or None and those means different things.
            ## TODO: Bad design
            ## TODO: duplicated code
            if tags is None:
                num_skipped_events += 1
                total_time_skipped_events += event['duration']
                if total_time_skipped_events.total_seconds()>MIN_RECORDING_INTERVAL:
                    breakpoint()
                continue
            
            if tags is False:
                num_unknown_events += 1
                self.total_time_unknown_events += event['duration']
                if self.total_time_unknown_events.total_seconds()>MAX_MIXED_INTERVAL*2:
                    ## TODO: we should consider to timew tag 'unknown not-afk'
                    breakpoint()
                self.log(f"{self.total_time_unknown_events.total_seconds()}s unknown events.  Data: {event['data']} - ({num_skipped_events} smaller events skipped, total duration {total_time_skipped_events.total_seconds()}s)", event=event)
            else:
                self.log(f"{event['data']} - tags found: {tags} ({num_skipped_events} smaller events skipped, total duration {total_time_skipped_events.total_seconds()}s)")
            num_skipped_events = 0
            total_time_skipped_events = timedelta(0)

            ## Ref README, if MAX_MIXED_INTERVAL is met, ignore accumulated minor activity
            ## (the mixed time will be attributed to the previous work task)
            if tags and event['duration'].total_seconds() > MAX_MIXED_INTERVAL:
                ## Theoretically, we may do lots of different things causing hundred of different independent tags to collect less than the minimum needed to record something.  In practice that doesn't happen.
                #print(f"We're tossing data: {self.tags_accumulated_time}")
                self.ensure_tag_exported(tags, event)

            interval_since_last_known_tick = event['timestamp'] + event['duration'] - self.last_known_tick
            if (interval_since_last_known_tick < timedelta(0)):
                ## Something is very wrong here, it needs investigation.
                breakpoint()
            assert(interval_since_last_known_tick >= timedelta(0))

            ## Track things in internal accumulator if the focus between windows changes often
            if tags:
                tags = retag_by_rules(tags)
                for tag in tags:
                    self.tags_accumulated_time[tag] += event['duration']
                    
            ## Check - if `timew start` was run manually since last "known tick", then reset everything
            self.set_timew_info(timew_retag(get_timew_info()))
            if interval_since_last_known_tick.total_seconds() > MIN_RECORDING_INTERVAL_ADJ and any(x for x in self.tags_accumulated_time if x not in SPECIAL_TAGS and self.tags_accumulated_time[x].total_seconds()>MIN_RECORDING_INTERVAL_ADJ):
                self.log("Emptying the accumulator!")
                tags = set()
                ## TODO: This looks like a bug - we reset tags, and then assert that they are not overlapping?
                assert not exclusive_overlapping(tags)
                min_tag_recording_interval=MIN_TAG_RECORDING_INTERVAL
                while exclusive_overlapping(set([tag for tag in self.tags_accumulated_time if  self.tags_accumulated_time[tag].total_seconds() > min_tag_recording_interval])):
                    min_tag_recording_interval += 1
                for tag in self.tags_accumulated_time:
                    if self.tags_accumulated_time[tag].total_seconds() > min_tag_recording_interval:
                        tags.add(tag)
                    self.tags_accumulated_time[tag] *= STICKYNESS_FACTOR
                if self.manual_tracking:
                    since = event['timestamp']-self.total_time_known_events+event['duration']
                else:
                    since = self.last_known_tick
                self.log(f"Ensuring tags export, tags={tags}")
                self.ensure_tag_exported(tags, event, since)

            self.last_tick = event['timestamp'] + event['duration']
            cnt += 1

            if tags is not False:
                pass
            
            elif event['data'].get('app', '').lower() in ('foot', 'xterm', ...): ## TODO: complete the list
                self.log(f"Unknown terminal event {event['data']['title']}", event=event, attrs=["bold"])
            else:
                self.log(f"No rules found for event {event['data']}", event=event, attrs=["bold"])
        return cnt>1

    def set_timew_info(self, timew_info):
        if self.afk is None and 'afk' in timew_info['tags']:
            self.afk = True
        if self.afk is None and 'not-afk' in timew_info['tags']:
            self.afk = False

        foo = self.timew_info
        self.timew_info = timew_info
        if foo != self.timew_info: ## timew has been run since last
            self.log(f"tracking from {ts2strtime(self.timew_info['start_dt'])}: {self.timew_info['tags']}")
            if not self.last_known_tick or timew_info['start_dt'] > self.last_known_tick:
                self.set_known_tick_stats(start=timew_info['start_dt'], manual=True, tags=timew_info['tags'])

    def tick(self):
        self.set_timew_info(timew_retag(get_timew_info()))
        if not self.last_tick:
            ## TODO: think more through this.  This is in practice program initialization
            self.last_tick = self.timew_info['start_dt']
            self.last_known_tick = self.last_tick
            self.last_start_time = self.last_tick
        if not self.find_next_activity():
            self.log("sleeping, because no events found")
            sleep(SLEEP_INTERVAL)

def check_bucket_updated(bucket: dict):
    if not bucket['last_updated_dt'] or time()-bucket['last_updated_dt'].timestamp() > AW_WARN_THRESHOLD:
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

## not really retag, more like expand tags?  But it's my plan to allow replacement and not only addings
def retag_by_rules(source_tags):
    assert not exclusive_overlapping(source_tags)
    new_tags = source_tags.copy()  ## TODO: bad variable naming.  `revised_tags` maybe?
    for tag_section in config['tags']:
        retags = config['tags'][tag_section]
        intersection = source_tags.intersection(set(retags['source_tags']))
        if intersection:
            new_tags_ = set()
            for tag in retags.get('add', []):
                if "$source_tag" in tag:
                    for source_tag in intersection:
                        new_tags_.add(tag.replace("$source_tag", source_tag))
                else:
                    new_tags_.add(tag)    
            new_tags_ = new_tags.union(new_tags_)
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

if __name__ == '__main__':
    main()
