"""Anonymize sample ActivityWatch data for testing."""

import json
from pathlib import Path

# Counter for varying file names
_file_counter = {"count": 0}


def anonymize_event(event: dict) -> dict:
    """Anonymize sensitive data in an event, creating varied test data that matches test_config.toml."""
    event_data = event.get("data", {})

    # Anonymize URLs - create variety for testing regex matching
    if "url" in event_data:
        url = event_data["url"]
        # Create URLs that will match test_config.toml patterns
        if "telegram" in url or "chat" in url:
            event_data["url"] = "https://web.telegram.org/chat"
        elif "github" in url:
            event_data["url"] = "https://github.com/user/myproject"
        elif "mattermost" in url or "chat.example" in url:
            event_data["url"] = "https://chat.company.com/team/general"
        elif "zimbra" in url or "mail" in url:
            event_data["url"] = "https://mail.company.com/inbox"
        elif "claude" in url.lower():
            event_data["url"] = "https://claude.ai"
        elif "docs.python" in url or _file_counter["count"] % 5 == 0:
            # Some URLs point to Python docs for testing
            event_data["url"] = "https://docs.python.org/3/library/datetime.html"
            _file_counter["count"] += 1
        else:
            event_data["url"] = "https://example.com/page"

    # Anonymize titles - create variety for testing
    if "title" in event_data:
        title = event_data["title"]
        app = event_data.get("app", "")

        # Vary titles based on app and create test patterns
        if "Mozilla Firefox" in title:
            # Vary between Python docs and generic pages
            if "docs.python" in event_data.get("url", ""):
                event_data["title"] = "datetime — Python Documentation — Mozilla Firefox"
            else:
                event_data["title"] = "Web Page — Mozilla Firefox"
        elif "Chromium" in title:
            if "github" in event_data.get("url", ""):
                event_data["title"] = "myproject - GitHub - Chromium"
            else:
                event_data["title"] = "Web Page - Chromium"
        elif "GNU Emacs" in title:
            # Create file.py for testing editor rules
            event_data["title"] = "main.py - GNU Emacs at localhost"
        elif app == "Code" or "vscode" in title.lower() or "Code" in title:
            # VSCode with .py file for testing
            event_data["title"] = "main.py - Visual Studio Code"
        elif "foot" in title.lower() or "ssh" in title.lower() or app == "foot":
            event_data["title"] = "terminal - foot"
        elif "Delta Chat" in title:
            event_data["title"] = "Delta Chat"
        else:
            # Generic anonymization
            event_data["title"] = "Application Window"

    # Anonymize file paths in emacs data - create .py files for testing
    if "file" in event_data:
        # Vary between .py and .md files
        if _file_counter["count"] % 3 == 0:
            event_data["file"] = "/home/user/myproject/src/main.py"
        elif _file_counter["count"] % 3 == 1:
            event_data["file"] = "/home/user/myproject/tests/test_app.py"
        else:
            event_data["file"] = "/home/user/myproject/README.md"
        _file_counter["count"] += 1

    if "project" in event_data:
        event_data["project"] = "myproject"

    # Update language based on file extension
    if "language" in event_data and "file" in event_data:
        if event_data["file"].endswith(".py"):
            event_data["language"] = "python-mode"
        else:
            event_data["language"] = "markdown-mode"

    # Anonymize app names - vary for testing
    if "app" in event_data:
        app = event_data["app"]
        # Map to test-friendly app names
        if app == "Emacs":
            # Keep Emacs as is
            pass
        elif app == "foot":
            # Keep terminal
            pass
        elif app == "firefox":
            # Keep firefox
            pass
        elif app == "chromium":
            # Keep chromium, but sometimes map to Code for VSCode testing
            if _file_counter["count"] % 7 == 0:
                event_data["app"] = "Code"
                event_data["title"] = "main.py - Visual Studio Code"
                _file_counter["count"] += 1
        elif app not in ["gcr-prompter", "DeltaChat"]:
            event_data["app"] = "GenericApp"

    return event


def main() -> None:
    """Anonymize the sample data file."""
    repo_root = Path(__file__).parent.parent
    input_file = repo_root / "tests" / "fixtures" / "sample_15min_raw.json"
    output_file = repo_root / "tests" / "fixtures" / "sample_15min.json"

    # Read the raw data
    with open(input_file) as f:
        data = json.load(f)

    # Anonymize all events
    for _bucket_id, events in data["events"].items():
        for event in events:
            anonymize_event(event)

    # Mark as anonymized
    data["metadata"]["anonymized"] = True

    # Write anonymized data
    with open(output_file, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Anonymization complete. Output written to {output_file}")


if __name__ == "__main__":
    main()
