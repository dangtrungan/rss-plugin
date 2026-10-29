# News Feed

An on-demand RSS and Atom reader for Omarchy 4.x. It adds an icon to the
right side of the bar. Clicking the icon opens a panel with headlines from
your feeds, newest first, with the source shown beside each time.

Feeds are fetched only when you open the panel or press refresh. There are
no timers, no background polling, and no network activity at shell startup.

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
- Each feed shows up to 15 items. Feeds larger than 2 MB are reported as
  errors.

The config file is not created for you. Create it only if you want feeds
other than the defaults.

## Using the panel

- Click the icon to open or close the panel.
- Click a headline to open it in your browser.
- Keyboard: `j`/`k` or the arrow keys move the selection, `Enter` opens the
  selected headline, `r` refreshes, `Esc` closes.
- A feed that fails shows its error under its own name. The other feeds still
  load.
- The last headlines are cached in `~/.cache/omarchy-newsfeed/cache.json`
  (or `$XDG_CACHE_HOME`). Opening the panel shows them right away while the
  feeds refresh. A feed that fails keeps its cached headlines until it
  recovers or is removed from your feed config. Cached headlines never expire
  on their own.

## Requirements

- Python 3 (standard library only, no packages to install)
- `xdg-open` to open headlines in a browser

## Tests

```sh
python3 -m unittest discover -s tests
```

## Removal

```sh
omarchy plugin remove dangtrungan.newsfeed
```

This does not delete your feed config. To remove it:

```sh
rm -r ~/.config/omarchy-newsfeed
```

## License

MIT. See [LICENSE](LICENSE).
