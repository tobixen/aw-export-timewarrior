"""Anonymize sample ActivityWatch data for testing."""
import json
import sys
from pathlib import Path


def anonymize_event(event: dict) -> dict:
    """Anonymize sensitive data in an event."""
    event_data = event.get('data', {})

    # Anonymize URLs
    if 'url' in event_data:
        # Keep the protocol and basic structure but anonymize content
        if 'telegram' in event_data['url']:
            event_data['url'] = 'https://example.com/chat/12345'
        elif 'github' in event_data['url']:
            event_data['url'] = 'https://github.com/user/repo'
        elif 'mattermost' in event_data['url']:
            event_data['url'] = 'https://chat.example.com/team/channel'
        elif 'zimbra' in event_data['url']:
            event_data['url'] = 'https://mail.example.com'
        elif 'claude' in event_data['url'].lower():
            event_data['url'] = 'https://claude.ai'
        else:
            event_data['url'] = 'https://example.com'

    # Anonymize titles
    if 'title' in event_data:
        title = event_data['title']
        # Keep application names but anonymize content
        if 'Mozilla Firefox' in title:
            event_data['title'] = 'Web Page — Mozilla Firefox'
        elif 'Chromium' in title:
            event_data['title'] = 'Web Page - Chromium'
        elif 'GNU Emacs' in title:
            event_data['title'] = 'file.txt - GNU Emacs at localhost'
        elif 'foot' in title.lower() or 'ssh' in title.lower():
            event_data['title'] = 'terminal'
        elif 'Delta Chat' in title:
            event_data['title'] = 'Delta Chat'
        else:
            # Generic anonymization
            event_data['title'] = 'Application Window'

    # Anonymize file paths in emacs data
    if 'file' in event_data:
        # Keep structure but anonymize path
        event_data['file'] = '/home/user/project/file.md'

    if 'project' in event_data:
        event_data['project'] = 'myproject'

    # Anonymize app names that might be sensitive
    if 'app' in event_data:
        app = event_data['app']
        # Keep common apps, anonymize custom/specific ones
        known_apps = ['foot', 'Emacs', 'firefox', 'chromium', 'DeltaChat']
        if app not in known_apps and app not in ['gcr-prompter']:
            event_data['app'] = 'custom-app'

    return event


def main() -> None:
    """Anonymize the sample data file."""
    repo_root = Path(__file__).parent.parent
    input_file = repo_root / 'tests' / 'fixtures' / 'sample_15min_raw.json'
    output_file = repo_root / 'tests' / 'fixtures' / 'sample_15min.json'

    # Read the raw data
    with open(input_file, 'r') as f:
        data = json.load(f)

    # Anonymize all events
    for bucket_id, events in data['events'].items():
        for event in events:
            anonymize_event(event)

    # Mark as anonymized
    data['metadata']['anonymized'] = True

    # Write anonymized data
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"Anonymization complete. Output written to {output_file}")


if __name__ == '__main__':
    main()
