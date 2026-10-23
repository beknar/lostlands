# Lostlands Wiki — static export

A static HTML/CSS copy of the **Lostlands Wiki**, previously served by
MediaWiki 1.37.2 at <https://lostlands.rpg4you.com/>.

The wiki held exactly one content page (`Main_Page`), two revisions and no
uploads, with its last edit in May 2022. Keeping a full MediaWiki install —
PHP, MariaDB and ~271 MB of application code, all of it long past upstream
end-of-life — to serve one page is not a good trade, so the page was converted
to flat files. The result is 27 files and about 224 KB.

## Layout

```
html/Main_Page.html       the rendered page as fetched from the live wiki (build input)
site/                     the static site — serve this directory
  index.html              the converted page
  assets/styles.css       the skin stylesheet, pulled from load.php
  assets/static-site.css  hand-written layout corrections (NOT generated)
  static/                 skin images the stylesheet references
tools/build-static.py     rebuilds site/ from html/
```

## Rebuilding

```bash
python3 tools/build-static.py            # rebuild from the saved html/
python3 tools/build-static.py --fetch    # re-fetch from the live wiki first
```

No dependencies beyond the Python 3 standard library — `bs4` and `lxml` are not
installed on the origin host, so the script tracks tag nesting itself rather
than parsing. `--fetch` only works while the live wiki still exists.

The build prints a count of every rewrite and removal it performed, then
verifies that no absolute reference back to the wiki survives. A removal that
silently stops matching shows up as a `MISSING ...` line rather than passing
unnoticed.

## What was removed

The wiki chrome that cannot work without MediaWiki behind it is removed from
the markup, not hidden with CSS, so it is genuinely gone and costs nothing to
download. The page is 4,856 bytes against 16,207 live — about 70% smaller.

| Removed | Markup |
|---|---|
| Not logged in / Talk / Contributions / Log in | `p-personal` |
| Read / Edit / Edit source / View history | `p-views` |
| Main page / Discussion tabs | `p-namespaces` |
| Tools portlet (What links here, Special pages, …) | `p-tb` |
| Recent changes, Random page, Help about MediaWiki | `n-recentchanges`, `n-randompage`, `n-help-mediawiki` |
| Search box | `p-search` |
| "This page was last edited on …" | `footer-info-lastmod` |
| Privacy policy / About / Disclaimers | `footer-places` |
| "Powered by MediaWiki" badge | `footer-icons` |
| `[edit \| edit source]` beside headings | `.mw-editsection` |
| "Getting started" section and everything below it | MediaWiki's stock new-wiki boilerplate |
| "Retrieved from <url>" print line | `.printfooter` |

What survives: the logo, a Navigation portlet holding the single **Main page**
link, and the "Omeria Content List" content. `p-cactions` and `p-variants`
remain in the markup but MediaWiki tags them `.emptyPortlet`, which Vector's
own stylesheet hides.

Emptied containers are dropped too — `footer-info` and `<footer>` itself — but
only when nothing is left inside them, so a returning item is never silently
swallowed.

## Accessibility note

Vector emits two screen-reader skip links. "Jump to search" targeted
`#searchInput`, which no longer exists, so it was removed: a skip link to
nothing is worse than no skip link, because a screen reader still announces it.
"Jump to navigation" aimed at `#mw-head`, now empty, so it was repointed at
`#mw-panel`, where the navigation actually lives.

## Gotchas worth keeping in mind

Each of these is silent when it breaks, which is what makes it worth writing
down.

**`url()` inside the stylesheet.** The bundle comes straight off `load.php`, so
its `url()` values are absolute (`/skins/…`) or root-relative (`resources/…`).
Both 404 the moment the sheet is served as a plain file. Rewriting only the
HTML attributes leaves the wiki logo, the sidebar bullets and every skin icon
missing, with nothing in the markup to explain why. The rewrite is idempotent —
it skips values already pointing at `../static/` — so re-running the build does
not stack prefixes.

**`srcset` needs the same rewriting as `src`.** Miss it and the image still
works, because the browser falls back to `src`; only high-DPI displays fetch
the untouched candidates. The page then appears fine on an ordinary monitor
while quietly depending on the live wiki.

**`client-js` without ResourceLoader.** The server renders
`<html class="client-nojs">` and an inline script flips it to `client-js`.
Vector's stylesheet uses that distinction to decide what to show outright
versus what to hide until JavaScript reveals it. With the ResourceLoader
bootstrap removed, claiming `client-js` would leave such elements hidden
permanently, so that script is dropped and the class stays `client-nojs`. The
`RLQ` queue scripts are dropped for the same reason: nothing drains that queue
any more, so they only ship a payload that never runs.

**Fetch assets after stripping, not before.** Scanning the original page for
images collects assets belonging to chrome that is about to be removed — the
powered-by badge and its two high-DPI variants — and ships them as orphans. The
fetch therefore runs against the finished document.

**Removal has to track nesting.** The section edit links nest further spans
inside for the `[` and `]` brackets, so a flat regex stops at the first
`</span>` and strands the brackets beside the heading.

## Provenance

Converted from the live wiki on 2026-10-22. The MediaWiki install and its
database are backed up separately and are not part of this repository — they
contain `LocalSettings.php` and user password hashes, neither of which belongs
in a public repo.

The page body links to a Google Sheets document. That link was already public
on the live wiki; it is reproduced here verbatim, as moving it would change the
content rather than the presentation.
