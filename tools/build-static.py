#!/usr/bin/env python3
"""Turn the Lostlands Wiki (MediaWiki 1.37.2) into a self-contained static site.

The wiki holds exactly one content page, Main_Page, and no uploads, so this is
a far smaller job than the Siete Pares Escrima export: fetch the rendered page,
pull the stylesheet and everything it references, rewrite the URLs, and strip
the controls a static page cannot support.

Run from the repo root:

    python3 tools/build-static.py            # rebuild from html/Main_Page.html
    python3 tools/build-static.py --fetch    # re-fetch from the live wiki first

Inputs : html/Main_Page.html  (fetched from the live wiki)
Output : site/index.html, site/assets/, site/static/
"""

import os
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

LIVE = "https://lostlands.rpg4you.com"
OUT = "site"
counts = Counter()


def fetch(url, dest):
    """Download url to dest, creating parent directories."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with urllib.request.urlopen(url, timeout=30) as r:
        data = r.read()
    with open(dest, "wb") as fh:
        fh.write(data)
    return len(data)


# ---------------------------------------------------------------------------
# chrome removal
# ---------------------------------------------------------------------------

# Elements removed wholesale, by id. Each entry records which part of the
# request it satisfies, because "the links on the left" and "the tabs" map to
# several separate portlets in Vector's markup.
REMOVE_IDS = [
    # upper right: "Not logged in" / Talk / Contributions / Log in
    "p-personal",
    # the tab strip: Read / Edit / Edit source / View history
    "p-views",
    # the namespace tabs beside them: "Main page" and "Discussion". Discussion
    # was a redlink even on the live wiki (no Talk page was ever created), and
    # "Main page" pointed at the page you were already on. The whole portlet
    # goes -- those two <li>s were its only contents.
    "p-namespaces",
    # left sidebar "Tools" portlet, in full: What links here, Related changes,
    # Special pages, Printable version, Permanent link, Page information
    "p-tb",
    # the search box -- it needs a search backend to do anything, and its form
    # posted to /index.php, which does not exist here
    "p-search",
    # footer: the "Powered by MediaWiki" badge, bottom right
    "footer-icons",
    # footer: "This page was last edited on ..."
    "footer-info-lastmod",
    # footer: Privacy policy / About / Disclaimers
    "footer-places",
]

# Sidebar links removed individually. The Navigation portlet itself stays,
# because "Main page" is the one link that was asked to survive and it lives
# here; removing the portlet would take it too.
REMOVE_NAV_ITEMS = [
    "n-recentchanges",
    "n-randompage",
    "n-help-mediawiki",
]


def remove_element(doc, elem_id):
    """Drop the element carrying id="elem_id", including its children.

    Tracks nesting depth on the element's own tag name rather than reaching for
    a parser: MediaWiki's output is well-formed, and bs4/lxml are not installed
    on this host. Tag-agnostic, so it handles <nav>, <div> and <li> alike --
    1.37 wraps portlets in <nav> where 1.35 used <div>.
    """
    m = re.search(r'<(\w+)([^>]*\sid="%s")' % re.escape(elem_id), doc)
    if not m:
        return doc, False
    tag = m.group(1)
    start = m.start()

    open_end = doc.index(">", m.end() - 1)
    if doc[open_end - 1] == "/":                      # self-closing
        return doc[:start] + doc[open_end + 1:], True

    depth = 0
    pos = start
    pat = re.compile(r"<(/?)%s\b" % re.escape(tag), re.I)
    while True:
        mm = pat.search(doc, pos)
        if not mm:
            return doc, False
        if mm.group(1):
            depth -= 1
            if depth == 0:
                end = doc.index(">", mm.end()) + 1
                return doc[:start] + doc[end:], True
        else:
            depth += 1
        pos = mm.end()


def remove_by_class(doc, tag, cls):
    """Remove every <tag class="...cls..."> element, children included.

    Needed for the section edit links, which carry no id and nest further
    spans inside (the [ ] brackets), so a flat regex would stop at the first
    </span> and leave the brackets stranded beside the heading.
    """
    pat = re.compile(r'<%s\b[^>]*class="[^"]*\b%s\b[^"]*"' % (re.escape(tag), re.escape(cls)))
    nest = re.compile(r"<(/?)%s\b" % re.escape(tag), re.I)
    removed = 0
    while True:
        m = pat.search(doc)
        if not m:
            return doc, removed
        depth, pos = 0, m.start()
        while True:
            mm = nest.search(doc, pos)
            if not mm:
                return doc, removed          # malformed; leave the rest alone
            if mm.group(1):
                depth -= 1
                if depth == 0:
                    end = doc.index(">", mm.end()) + 1
                    doc = doc[:m.start()] + doc[end:]
                    removed += 1
                    break
            else:
                depth += 1
            pos = mm.end()


def drop_getting_started(doc):
    """Remove the "Getting started" heading and everything after it.

    This is MediaWiki's stock new-wiki boilerplate -- links to the config
    settings list, the FAQ, the release mailing list, localisation and
    anti-spam docs. It is the tail of the page, so everything from its <h2>
    up to the end of the parser output goes. The real content above it, the
    "Omeria Content List" section, is untouched.
    """
    start = doc.find('<h2><span class="mw-headline" id="Getting_started"')
    if start == -1:
        return doc, False

    # The parser output ends at MediaWiki's limit-report comment; fall back to
    # the closing div of mw-parser-output if that comment is ever absent.
    end = doc.find("<!-- \nNewPP limit report", start)
    if end == -1:
        end = doc.find("<!--", start)
    if end == -1:
        return doc, False
    return doc[:start] + doc[end:], True


def strip_controls(doc):
    for elem_id in REMOVE_IDS + REMOVE_NAV_ITEMS:
        doc, hit = remove_element(doc, elem_id)
        counts[("removed " if hit else "MISSING ") + elem_id] += 1

    # The [edit | edit source] links beside each heading. These sit in the page
    # content, not the chrome, so removing the tab strip leaves them behind --
    # and they read literally "edit | edit source", which is exactly what was
    # asked to go.
    doc, n = remove_by_class(doc, "span", "mw-editsection")
    if n:
        counts["removed section edit links"] += n

    doc, hit = drop_getting_started(doc)
    counts["removed Getting started section" if hit else "MISSING Getting started"] += 1

    # footer-info held only the last-edited line, so removing that leaves an
    # empty <ul> behind. It renders nothing but still carries Vector's list
    # margins, which pushes the powered-by badge down for no reason. Drop it,
    # but only when it really is empty -- never blindly.
    doc, n = re.subn(r'<ul id="footer-info"[^>]*>\s*</ul>\s*', "", doc)
    counts["removed emptied footer-info"] += n

    # With both the last-edited line and the powered-by badge gone, <footer>
    # itself is empty -- but Vector still gives it a top border and padding, so
    # it would draw a stray rule under the content. Remove it only if nothing
    # is left inside, so this does nothing should a footer item ever return.
    doc, n = re.subn(r'<footer id="footer"[^>]*>\s*</footer>\s*', "", doc)
    counts["removed emptied footer"] += n

    # MediaWiki's print-only "Retrieved from <url>" line: display:none on
    # screen, but an absolute http:// link to an index.php URL that will not
    # exist once this is served statically.
    doc, n = remove_by_class(doc, "div", "printfooter")
    if n:
        counts["removed print footer"] += n

    # Vector emits two screen-reader skip links. "Jump to search" now points at
    # a #searchInput that no longer exists, so it goes with the search box --
    # a skip link to nothing is worse than no skip link, because a screen
    # reader still announces it. "Jump to navigation" aimed at #mw-head, which
    # is empty now, so repoint it at the sidebar where the nav actually lives.
    doc, hit = re.subn(
        r'<a class="mw-jump-link" href="#searchInput">[^<]*</a>\s*', "", doc)
    if hit:
        counts["removed jump-to-search link"] += hit
    doc, hit = re.subn(r'(<a class="mw-jump-link" href=")#mw-head(">)', r"\1#mw-panel\2", doc)
    if hit:
        counts["retargeted jump-to-nav link"] += hit
    return doc


# ---------------------------------------------------------------------------
# URL rewriting
# ---------------------------------------------------------------------------

def rewrite_css(path, fetch_assets=False):
    """Rewrite url() refs in a CSS bundle to static/, fetching the targets.

    The bundle comes straight off load.php, so its url() values are absolute
    ("/skins/...") or root-relative ("resources/..."). Both 404 once the sheet
    is served as a plain file -- that is what hides the wiki logo, the search
    magnifier and every sidebar bullet. The sheet lives in site/assets/, so
    static/ is one directory up.
    """
    with open(path, encoding="utf-8", errors="replace") as fh:
        css = fh.read()

    def repl(m):
        quote, ref = m.group(1), m.group(2)
        # "../static/" means this sheet was rewritten already: keep the build
        # idempotent so re-runs do not stack prefixes.
        if ref.startswith(("data:", "http://", "https://", "//", "#", "../static/")):
            return m.group(0)
        clean = ref.split("?")[0].split("#")[0].lstrip("/")
        counts["css url()"] += 1
        if fetch_assets:
            dest = os.path.join(OUT, "static", clean)
            if not os.path.exists(dest):
                try:
                    fetch(LIVE + "/" + clean, dest)
                    counts["css asset fetched"] += 1
                except Exception as exc:                 # noqa: BLE001
                    counts["css asset FAILED"] += 1
                    print("  ! %s: %s" % (clean, exc))
        return "url(%s../static/%s%s)" % (quote, clean, quote)

    css = re.sub(r'url\((["\']?)([^)"\']+)\1\)', repl, css)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(css)


def rewrite(doc):
    # --- stylesheet bundle -> local copy ---
    doc = re.sub(r'href="/load\.php\?[^"]*only=styles[^"]*"', 'href="assets/styles.css"', doc)
    counts["stylesheet relinked"] += 1

    # --- ResourceLoader bootstrap -> dropped ---
    # The startup module exists to fetch further modules from load.php at
    # runtime. With no MediaWiki behind the site every one of those requests
    # 404s, and nothing on this page needs them, so the script goes entirely
    # rather than being pointed at a local copy that cannot work.
    doc, n = re.subn(r'<script[^>]*src="/load\.php\?[^"]*"[^>]*>\s*</script>', "", doc)
    counts["ResourceLoader bootstrap dropped"] += n

    # The inline scripts exist only to drive ResourceLoader, which has just
    # been removed, so all of them are now dead weight:
    #
    #   * the RLQ pushes queue callbacks onto window.RLQ. Nothing drains that
    #     queue any more, so they never run -- they just ship their payload
    #     (user.options, the parser limit report) to every visitor for nothing.
    #   * the RLCONF block also sets document.documentElement.className to
    #     "client-js". The server renders <html class="client-nojs">, and
    #     Vector's stylesheet uses that distinction to decide what to show
    #     outright versus what to hide until JavaScript reveals it. Claiming
    #     "client-js" with no ResourceLoader to follow through would leave any
    #     such element hidden permanently, so the class must stay client-nojs.
    doc, n = re.subn(r'<script(?![^>]*\ssrc=)[^>]*>\s*\(RLQ=.*?</script>', "", doc, flags=re.S)
    counts["RLQ queue scripts dropped"] += n
    doc, n = re.subn(
        r'<script(?![^>]*\ssrc=)[^>]*>\s*document\.documentElement\.className="client-js".*?</script>',
        "", doc, flags=re.S)
    counts["client-js switch dropped"] += n

    # --- skin / resource assets -> static/, query dropped ---
    def static_ref(m):
        counts["static asset"] += 1
        return '%s="static%s"' % (m.group(1), m.group(2))

    doc = re.sub(r'(src|href)="(/(?:skins|resources|extensions)/[^"?]*)(?:\?[^"]*)?"',
                 static_ref, doc)

    # srcset holds several comma-separated "url 1.5x" candidates and needs the
    # same rewriting as src. Miss it and the image still works -- the browser
    # falls back to src -- while every high-DPI candidate silently points at
    # the live wiki, so the page only breaks for retina visitors, or once the
    # wiki is gone. Same trap as the Siete Pares Escrima build.
    def srcset(m):
        parts = []
        for cand in m.group(1).split(","):
            cand = cand.strip()
            if not cand:
                continue
            bits = cand.split(None, 1)
            url, suffix = bits[0], (" " + bits[1] if len(bits) > 1 else "")
            if url.startswith(("/skins/", "/resources/", "/extensions/")):
                counts["static asset (srcset)"] += 1
                url = "static" + url.split("?")[0]
            parts.append(url + suffix)
        return 'srcset="%s"' % ", ".join(parts)

    doc = re.sub(r'srcset="([^"]*)"', srcset, doc)

    # --- the one real page -> index.html ---
    for form in ("/index.php/Main_Page", "/index.php?title=Main_Page"):
        doc = doc.replace('"%s"' % form, '"index.html"')
        counts["page link"] += 1

    # --- strip the controls ---
    doc = strip_controls(doc)

    # --- links to things that need a backend ---
    # (the favicon link pointed at the wiki's path; site/favicon.ico, the
    # rpg4you.com icon added 2026-11-12, sits where browsers look by default)
    doc = re.sub(r'<link[^>]*favicon[^>]*>', "", doc)
    doc = re.sub(r'<link[^>]*(?:opensearch_desc\.php|action=rsd|feed=atom)[^>]*>', "", doc)
    counts["stripped backend link"] += 1

    # Two <link> tags in <head> advertise the page's edit URL to clients that
    # understand them (rel="edit" and the x-wiki alternate). They render
    # nothing, but they are edit entry points aimed at an index.php that will
    # not exist, so they go with the visible edit controls.
    doc, n = re.subn(r'<link[^>]*rel="(?:edit|alternate)"[^>]*action=edit[^>]*>', "", doc)
    counts["stripped head edit link"] += n

    doc = doc.replace("</head>",
                      '<link rel="stylesheet" href="assets/static-site.css"></head>', 1)
    counts["override css linked"] += 1
    return doc


def main():
    do_fetch = "--fetch" in sys.argv
    os.makedirs(os.path.join(OUT, "assets"), exist_ok=True)

    if do_fetch:
        n = fetch(LIVE + "/index.php/Main_Page", "html/Main_Page.html")
        print("fetched Main_Page.html (%d bytes)" % n)

    with open("html/Main_Page.html", encoding="utf-8", errors="replace") as fh:
        doc = fh.read()

    # the styles bundle, taken from the page itself so the module list stays
    # whatever the wiki actually asked for
    m = re.search(r'href="(/load\.php\?[^"]*only=styles[^"]*)"', doc)
    css_path = os.path.join(OUT, "assets", "styles.css")
    if m and (do_fetch or not os.path.exists(css_path)):
        url = LIVE + m.group(1).replace("&amp;", "&")
        print("fetching stylesheet: %d bytes" % fetch(url, css_path))

    rewrite_css(css_path, fetch_assets=True)

    doc = rewrite(doc)
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(doc)

    # Images the FINISHED page references. This runs after rewrite() on
    # purpose: scanning the original would also pull in assets belonging to
    # chrome that has just been stripped -- the powered-by badge and its two
    # high-DPI variants, for instance -- and ship them for nothing. The srcset
    # candidates live inside one attribute as "url 1.5x, url 2x", so they have
    # to be split out rather than matched as a whole value.
    refs = set(re.findall(r'(?:src|href)="(static/[^"?]*)"', doc))
    for attr in re.findall(r'srcset="([^"]*)"', doc):
        for cand in attr.split(","):
            cand = cand.strip().split(None, 1)
            if cand and cand[0].startswith("static/"):
                refs.add(cand[0].split("?")[0])

    for ref in sorted(refs):
        dest = os.path.join(OUT, ref)
        if not os.path.exists(dest):
            try:
                fetch(LIVE + "/" + ref[len("static/"):], dest)
                counts["page asset fetched"] += 1
            except Exception as exc:                     # noqa: BLE001
                print("  ! %s: %s" % (ref, exc))

    print("\nwrote site/index.html (%d bytes)" % len(doc))
    for k, v in sorted(counts.items()):
        print("  %-36s %d" % (k, v))

    # --- verification ---
    leftovers = Counter()
    for mm in re.findall(r'(?:src|href)="(/[^"]*)"', doc):
        leftovers[mm.split("?")[0]] += 1
    for mm in re.findall(r'(?:src|href)="(https?://lostlands\.rpg4you\.com[^"]*)"', doc):
        leftovers["ABS " + mm.split("?")[0]] += 1

    if leftovers:
        print("\nremaining absolute refs:")
        for k, v in leftovers.most_common(20):
            print("  %5d  %s" % (v, k))
    else:
        print("\nno absolute refs remain")
    return 0


if __name__ == "__main__":
    sys.exit(main())
