from aw_core.config import load_config_toml

default_config = """
[tags.housework]
source_tags = [ "housework", "dishwash" ]
prepend = [ "4chores", "afk" ] 

[tags.tea]
source_tags = [ "tea" ]
prepend = [ "4break", "afk", "tea" ] 

[tags.entertainment]
source_tags = [ "entertainment" ]
prepend = [ "4break" ] 

[rules.browser.entertainment]
url_regexp = "^https://(?:www\\\\.)?(theguardian).com/"
timew_tags = [ "entertainment", "$1" ]

[rules.app.comms]
app_names = ["Signal", "DeltaChat"]
timew_tags = [ "personal communication", "$app" ]

[rules.editor.acme]
project_regexp = "acme"
timew_tags = [ "work", "acme" ]
""".strip()

config = load_config_toml("aw-export-timewarrior", default_config)
