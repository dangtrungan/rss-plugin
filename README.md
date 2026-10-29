# News Feed

An on-demand RSS and Atom reader for Omarchy 4.x. It adds an icon to the
right side of the bar, with a count of unread headlines when there are any.
Clicking the icon opens a panel with headlines from your feeds, newest first,
with the source shown beside each time.

Feeds are fetched only when you open the panel or press refresh. There are
no timers and no background polling. At shell startup the plugin reads only
local cache and read-state files, with no network activity.

Plugin ID: `dangtrungan.newsfeed`

## Install

Install from a git URL, or from a local checkout:

```sh
omarchy plugin add https://github.com/dangtrungan/rss-plugin.git --enable
```

Confirm it is listed:

```sh
omarchy plugin list --json
```

## Remove

```sh
omarchy plugin remove dangtrungan.newsfeed
```

This does not delete your feed config, cache, or read state. To remove them:

```sh
rm -r ~/.config/omarchy-newsfeed ~/.cache/omarchy-newsfeed
```

## Feed configuration

Feeds are read from `~/.config/omarchy-newsfeed/feeds.json`. If
`XDG_CONFIG_HOME` is set, the file is read from `$XDG_CONFIG_HOME/omarchy-newsfeed/feeds.json`.

```json
[
  {"name": "Hacker News", "url": "https://news.ycombinator.com/rss"},
  {"name": "Omarchy News", "url": "https://omarchy.org/news/rss.xml"},
  {"name": "VnExpress Khoa học công nghệ", "url": "https://vnexpress.net/rss/khoa-hoc-cong-nghe.rss"},
  {"name": "r/programming", "url": "https://www.reddit.com/r/programming/top/.rss?t=day"}
]
```

Rules:

- Each entry needs a non-empty `name` and an `http://` or `https://` `url`.
  Other entries are skipped.
- If the file is missing, is not valid JSON, or has no valid entries, the
  built-in defaults are used: Hacker News and Omarchy News.
- At most 50 feeds are read. Feeds larger than 2 MB are reported as errors.

The plugin never creates or changes `feeds.json` on its own. It is written
only when you add or remove a feed in the panel (see below). Those changes
keep every entry the plugin does not own, including entries it skips. If the
file is not valid JSON or is not a list, the plugin refuses to change it and
shows an error, so your file is never overwritten.

## Settings

Each feed shows up to 15 headlines by default. To change this, add a `limit`
field to the plugin's entry in `~/.config/omarchy/shell.json`, for example
`{"id": "dangtrungan.newsfeed", "limit": 25}`. The value is clamped to 1–50.

## Using the panel

- Click the icon to open or close the panel. The count next to the icon is
  the number of headlines you have not opened yet.
- Click a headline to open it in your browser. It is marked read.
- Keyboard:
  - `j`/`k` or the arrow keys move the selection.
  - `Enter` opens the selected headline.
  - `r` refreshes.
  - `m` marks all headlines read.
  - `o` opens up to 10 unread headlines in your browser and marks them read.
  - `/` filters headlines by title or source. In the filter, `Enter` keeps the
    filter and `Esc` clears it.
  - `f` opens feed management (and `f` again returns to the news list).
  - `Esc` closes the panel.
- Read headlines are dimmed.
- In feed management:
  - `a` adds a feed. Type its `http://` or `https://` URL and press `Enter`.
    The feed is named after its host name. Press `Esc` to cancel.
  - `x` removes the selected feed. Press `x` twice: the first press asks, the
    second removes it.
- A feed that fails shows its error under its own name. The other feeds still
  load.
- The last headlines are cached in `~/.cache/omarchy-newsfeed/cache.json`
  (or `$XDG_CACHE_HOME`). Opening the panel shows them right away while the
  feeds refresh. A feed that fails keeps its cached headlines until it
  recovers or is removed. Cached headlines never expire on their own.
- Read state is stored in `~/.cache/omarchy-newsfeed/seen.json`. The 2000 most
  recently read headlines are kept. If this file is deleted, headlines show as
  unread again.

## Security and privacy

- Feed content is untrusted. Titles and names are shown as plain text, and
  only `http://` and `https://` links are opened, with `xdg-open`.
- Network requests go only to the URLs in your feed config, and only when you
  open the panel or refresh.
- The plugin runs as code inside the Omarchy shell, like every shell plugin.
  Only install code you trust.

## Dependencies

- Omarchy 4.x shell, which provides the bar, panel, and plugin system.
- Python 3, from the standard library only. No Python packages are needed.
- `xdg-open`, to open headlines in a browser.
- Network access to the feed hosts you configure.

## Tests

```sh
python3 -m unittest discover -s tests
```

## License

MIT. See [LICENSE](LICENSE).
