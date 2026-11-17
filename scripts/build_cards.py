"""Build the profile cards (minimal SVGs, dark + light) from live GitHub data.

    GH_TOKEN=... python scripts/build_cards.py --out dist

Reads profile.json for the hand-written parts (role, stack, focus, projects) and the
GitHub GraphQL API for everything that is counted.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
import urllib.request
from xml.sax.saxutils import escape

SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace"
W = 840

THEMES = {
    'dark': {'bg': '#0a0a0a', 'line': '#262626', 'text': '#fafafa', 'muted': '#8a8a8a', 'faint': '#3a3a3a',
             'accent': '#3ddc84', 'pill': '#141414',
             'heat': ['#161616', '#0d3b24', '#14663a', '#22a35a', '#3ddc84']},
    'light': {'bg': '#ffffff', 'line': '#e6e6e6', 'text': '#0a0a0a', 'muted': '#6e6e6e', 'faint': '#cfcfcf',
              'accent': '#14a150', 'pill': '#f6f6f6',
              'heat': ['#efefef', '#bfe8cf', '#7cd29d', '#2fb36a', '#14874a']},
}

QUERY = """query($login:String!){user(login:$login){createdAt followers{totalCount}
 repositories(ownerAffiliations:OWNER,privacy:PUBLIC,first:100){totalCount nodes{name description stargazerCount
   primaryLanguage{name color} url pushedAt}}
 contributionsCollection{contributionCalendar{totalContributions weeks{contributionDays{date contributionCount}}}}}}"""


def fetch(login, token):
    req = urllib.request.Request('https://api.github.com/graphql', method='POST',
                                 data=json.dumps({'query': QUERY, 'variables': {'login': login}}).encode(),
                                 headers={'Authorization': f'bearer {token}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as r:
        data = json.load(r)
    if data.get('errors'):
        raise SystemExit(data['errors'])
    return data['data']['user']


def svg(h, body, label):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" '
            f'role="img" aria-label="{escape(label)}">{body}</svg>\n')


def card(x, y, w, h, t):
    return f'<rect x="{x + .5}" y="{y + .5}" width="{w - 1}" height="{h - 1}" rx="14" fill="{t["bg"]}" stroke="{t["line"]}"/>'


def text(x, y, s, size, fill, weight=400, family=SANS, anchor='start', extra=''):
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}" {extra}>{escape(str(s))}</text>')


def tw(s, size):
    """Rough text width for the system sans stack."""
    return sum(size * (0.34 if c in 'il.,:|/ ' else 0.62 if c.isupper() else 0.55) for c in s)


# ---------------------------------------------------------------- data

def stats(user):
    days = [d for w in user['contributionsCollection']['contributionCalendar']['weeks'] for d in w['contributionDays']]
    longest = run = 0
    for d in days:
        run = run + 1 if d['contributionCount'] else 0
        longest = max(longest, run)
    current = 0
    for d in reversed(days):
        if d['contributionCount']:
            current += 1
        elif current or d is not days[-1]:  # today may still be empty
            break
    created = dt.date.fromisoformat(user['createdAt'][:10])
    return {
        'days': days,
        'total': user['contributionsCollection']['contributionCalendar']['totalContributions'],
        'active': sum(1 for d in days if d['contributionCount']),
        'longest': longest, 'current': current,
        'since': created.year,
        'years': (dt.date.today() - created).days // 365,
        'repos': user['repositories']['totalCount'],
    }


# ---------------------------------------------------------------- cards

def ridges(days, x0, y0, w, h, t, frames=16, dur=48):
    """Twelve stacked lines, one per month of the last year.

    Each month's activity loops through the line: frame f samples the month shifted by
    f/frames of its length, and SMIL morphs between frames, so the peaks drift forever
    while the ends stay flat."""
    months = {}
    for d in days:
        months.setdefault(d['date'][:7], []).append(d['contributionCount'])
    rows = list(months.values())[-12:]
    n, lift = 64, 52

    def sample(r, shift):
        size, curve = len(r), []
        for k in range(n + 1):
            pos = (k / n * size + shift * size) % size
            v = 0
            for j, c in enumerate(r):
                dist = abs(pos - j)
                dist = min(dist, size - dist)
                v += c * math.exp(-dist * dist / 5)
            curve.append(v)
        return curve

    shapes = [[sample(r, f / frames) for f in range(frames)] for r in rows]
    flat = sorted(v for row in shapes for v in row[0])
    peak = flat[int(len(flat) * 0.97)] or 1
    gap = (h - lift) / (len(rows) - 1)
    out = []
    for i, row in enumerate(shapes):
        base = y0 + lift + i * gap
        ds = []
        for curve in row + row[:1]:
            pts = []
            for k, v in enumerate(curve):
                u = k / n
                y = base - math.sqrt(min(v / peak, 1.15)) * lift * math.sin(math.pi * u) ** 1.5
                pts.append(f'{x0 + u * w:.0f},{y:.1f}')
            ds.append('M' + ' L'.join(pts))
        close = f' L{x0 + w},{base + 8} L{x0},{base + 8} Z'
        anim = f'<animate attributeName="d" dur="{dur}s" repeatCount="indefinite" values="%s"/>'
        last = i == len(rows) - 1
        stroke = t['accent'] if last else t['muted']
        out.append(f'<path d="{ds[0]}{close}" fill="{t["bg"]}">{anim % ";".join(d + close for d in ds)}</path>'
                   f'<path d="{ds[0]}" fill="none" stroke="{stroke}" stroke-width="{1.4 if last else 1}" '
                   f'stroke-opacity="{1 if last else 0.55}" stroke-linejoin="round">{anim % ";".join(ds)}</path>')
    return ''.join(out)


def header(p, s, t):
    h = 248
    art_x, art_w = 500, 300
    body = [
        card(0, 0, W, h, t),
        text(36, 52, p['login'].lower(), 12, t['muted'], family=MONO, extra='letter-spacing="1.5"'),
        text(36, 100, p['name'], 36, t['text'], 600, extra='letter-spacing="-0.8"'),
        text(36, 130, p['role'], 15, t['muted']),
        text(36, 160, p['tagline'], 15, t['text']),
        f'<circle cx="40" cy="{h - 44}" r="3.5" fill="{t["accent"]}"/>',
        text(52, h - 40, f"{p['location']}  ·  on GitHub since {s['since']}", 12, t['muted'], family=MONO),
        ridges(s['days'], art_x, 20, art_w, 200, t),
    ]
    return svg(h, ''.join(body), f"{p['name']}, {p['role']}")


ICONS = {
    'pulse': '<polyline points="1,8 4.5,8 6.5,3 9.5,13 11.5,8 15,8" fill="none"/>',
    'flame': '<path d="M8 1.5c.6 2.6 3.6 4 3.6 7.6a3.6 3.6 0 0 1-7.2 0c0-1.7.8-2.7 1.7-3.5.2 1.3.9 2 1.6 2.2C7 6 7.3 3.6 8 1.5z" fill="none"/>',
    'cal': '<rect x="2" y="3" width="12" height="11" rx="2" fill="none"/><path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3"/>',
    'cube': '<path d="M8 1.5l6 3.2v6.6L8 14.5l-6-3.2V4.7zM2 4.7l6 3.2 6-3.2M8 7.9v6.6" fill="none"/>',
    'plug': '<path d="M5.5 1.5v3M10.5 1.5v3M3.5 4.5h9v3a4.5 4.5 0 0 1-9 0zM8 12v2.5" fill="none"/>',
    'clock': '<circle cx="8" cy="8" r="6.5" fill="none"/><path d="M8 4.5V8l2.5 1.5" fill="none"/>',
}


def tiles(p, s, t):
    h, gap = 118, 16
    w = (W - 3 * gap) / 4
    items = [(x['icon'], x['value'], x['label']) for x in p.get('highlights', [])]
    items += [('pulse', f"{s['total']:,}", 'contributions · 12 months'),
              ('cal', f"{s['active']}", 'active days · 12 months'),
              ('flame', f"{s['longest']}", 'day longest streak'),
              ('clock', f"{s['years']}", f"years on GitHub · {s['repos']} repos")]
    items = items[:4]
    body = []
    for i, (icon, num, label) in enumerate(items):
        x = i * (w + gap)
        body += [card(x, 0, w, h, t),
                 f'<g transform="translate({x + 22:.1f},22)" stroke="{t["accent"]}" stroke-width="1.4" '
                 f'stroke-linecap="round" stroke-linejoin="round">{ICONS[icon]}</g>',
                 text(x + 22, 78, num, 30, t['text'], 600, extra='letter-spacing="-0.6"'),
                 text(x + 22, 100, label, 12, t['muted'])]
    return svg(h, ''.join(body), f"{s['total']:,} contributions in the last year")


def calendar(p, s, t):
    h = 218
    cell, pitch = 11, 14
    weeks = [s['days'][i:i + 7] for i in range(0, len(s['days']), 7)]
    if s['days'] and dt.date.fromisoformat(s['days'][0]['date']).weekday() != 6:  # align first column to Sunday
        first = (dt.date.fromisoformat(s['days'][0]['date']).weekday() + 1) % 7
        weeks = [s['days'][:7 - first]] + [s['days'][i:i + 7] for i in range(7 - first, len(s['days']), 7)]
    counts = sorted(d['contributionCount'] for d in s['days'] if d['contributionCount'])
    qs = [counts[int(len(counts) * f)] for f in (0.25, 0.5, 0.75)] if counts else [1, 2, 3]

    def level(c):
        return 0 if not c else 1 + sum(c > q for q in qs)

    gx = (W - len(weeks) * pitch + 3) / 2 + 12
    gy = 74
    body = ['<style>.tw1,.tw2{animation:tw1 3s ease-in-out infinite}.tw2{animation-name:tw2}'
            '@keyframes tw1{50%{opacity:.45}}@keyframes tw2{50%{opacity:.15}}'
            '@media (prefers-reduced-motion:reduce){.tw1,.tw2{animation:none}}</style>',
            card(0, 0, W, h, t),
            text(28, 40, 'Contributions', 15, t['text'], 600),
            text(W - 28, 40, f"{s['total']:,} in the last year", 13, t['muted'], anchor='end')]
    last_month = None
    for wi, wk in enumerate(weeks):
        for d in wk:
            date = dt.date.fromisoformat(d['date'])
            row = (date.weekday() + 1) % 7
            lv = level(d['contributionCount'])
            # active days twinkle like stars: stable pseudo-random speed and phase per date
            seed = int(hashlib.md5(d['date'].encode()).hexdigest()[:8], 16)
            twinkle = (f' class="tw{1 + (lv > 2)}" style="animation-duration:{2.2 + seed % 40 / 10:.1f}s;'
                       f'animation-delay:-{seed // 40 % 60 / 10:.1f}s"') if lv else ''
            body.append(f'<rect x="{gx + wi * pitch:.1f}" y="{gy + row * pitch}" width="{cell}" height="{cell}" rx="2.5" '
                        f'fill="{t["heat"][lv]}"{twinkle}><title>{d["contributionCount"]} on {d["date"]}</title></rect>')
        m = dt.date.fromisoformat(wk[0]['date']).strftime('%b')
        if m != last_month and wi < len(weeks) - 2:
            body.append(text(f'{gx + wi * pitch:.1f}', gy - 10, m, 10, t['muted'], family=MONO))
            last_month = m
    for row, name in ((1, 'Mon'), (3, 'Wed'), (5, 'Fri')):
        body.append(text(f'{gx - 8:.1f}', gy + row * pitch + 9, name, 9, t['faint'], family=MONO, anchor='end'))
    lx = W - 28 - tw('more', 10) - 10 - 5 * pitch
    ly = h - 30
    body.append(text(lx - 8, ly + 9, 'less', 10, t['muted'], family=MONO, anchor='end'))
    for i in range(5):
        body.append(f'<rect x="{lx + i * pitch}" y="{ly}" width="{cell}" height="{cell}" rx="2.5" fill="{t["heat"][i]}"/>')
    body.append(text(28, ly + 9, f"longest streak {s['longest']} days  ·  current {s['current']}", 10, t['muted'], family=MONO))
    body.append(text(lx + 5 * pitch + 2, ly + 9, 'more', 10, t['muted'], family=MONO))
    return svg(h, ''.join(body), f"Contribution calendar, {s['total']:,} contributions")


def stack(p, s, t):
    gap = 16
    w = (W - gap) / 2
    # pills, wrapped
    px, py, rows = 28, 64, []
    x, y = px, py
    for name in p['stack']:
        pw = tw(name, 13) + 26
        if x + pw > w - 24:
            x, y = px, y + 38
        rows.append((x, y, pw, name))
        x += pw + 8
    h = max(y + 28 + 30, 64 + len(p['focus']) * 34 + 26)
    body = [card(0, 0, w, h, t), text(28, 40, 'Core technologies', 15, t['text'], 600)]
    for x, y, pw, name in rows:
        body += [f'<rect x="{x + .5}" y="{y + .5}" width="{pw - 1:.1f}" height="27" rx="13.5" fill="{t["pill"]}" stroke="{t["line"]}"/>',
                 text(f'{x + pw / 2:.1f}', y + 18, name, 13, t['text'], anchor='middle')]
    fx = w + gap
    body += [card(fx, 0, w, h, t), text(fx + 28, 40, 'Focus', 15, t['text'], 600)]
    for i, line in enumerate(p['focus']):
        y = 64 + i * 34
        body += [f'<text x="{fx + 28}" y="{y + 18}" font-family="{MONO}" font-size="12" fill="{t["accent"]}">0{i + 1}</text>',
                 text(fx + 58, y + 18, line, 14, t['text'])]
    return svg(h, ''.join(body), 'Core technologies and focus')


def project(proj, repo, t):
    cw, h = W / 2, 136
    title = proj.get('title') or repo['name']
    desc = proj.get('description') or (repo or {}).get('description') or ''
    words, lines = desc.split(), ['']
    for word in words:
        if tw(lines[-1] + ' ' + word, 13) > cw - 70 and lines[-1]:
            if len(lines) == 2:
                lines[-1] += '…'
                break
            lines.append(word)
        else:
            lines[-1] = (lines[-1] + ' ' + word).strip()
    body = [card(4, 0, cw - 8, h, t),
            f'<rect x="26" y="27" width="8" height="8" rx="2" fill="{t["accent"]}"/>',
            text(46, 36, title, 15, t['text'], 600)]
    body += [text(26, 64 + i * 19, ln, 13, t['muted']) for i, ln in enumerate(lines) if ln]
    if proj.get('tech'):
        body.append(text(26, h - 22, proj['tech'], 11, t['muted'], family=MONO))
    elif repo and repo['primaryLanguage']:
        lang = repo['primaryLanguage']
        body += [f'<circle cx="31" cy="{h - 26}" r="5" fill="{lang["color"] or t["muted"]}"/>',
                 text(42, h - 22, lang['name'], 12, t['muted'])]
    if repo and repo['stargazerCount']:
        body.append(text(cw - 26, h - 22, f"★ {repo['stargazerCount']}", 12, t['muted'], anchor='end'))
    return svg(h, ''.join(body), f"{title}: {desc}").replace(f'width="{W}"', f'width="{cw:.0f}"').replace(f'viewBox="0 0 {W} {h}"', f'viewBox="0 0 {cw:.0f} {h}"')


def about(p, t):
    h, cols = 112, p['background']
    cw = (W - 56) / len(cols)
    body = [card(0, 0, W, h, t)]
    for i, col in enumerate(cols):
        x = 28 + i * cw
        if i:
            body.append(f'<line x1="{x - 14:.1f}" y1="26" x2="{x - 14:.1f}" y2="{h - 26}" stroke="{t["line"]}"/>')
        body.append(text(f'{x:.1f}', 38, col['label'], 11, t['muted'], family=MONO, extra='letter-spacing="1"'))
        body += [text(f'{x:.1f}', 64 + j * 20, ln, 13 if j else 14, t['muted'] if j else t['text'], 400 if j else 500)
                 for j, ln in enumerate(col['lines'])]
    return svg(h, ''.join(body), 'Education, recognition and languages')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='dist')
    ap.add_argument('--config', default='profile.json')
    a = ap.parse_args()
    p = json.load(open(a.config))
    user = fetch(p['login'], os.environ['GH_TOKEN'])
    s = stats(user)
    repos = {r['name']: r for r in user['repositories']['nodes']}
    os.makedirs(a.out, exist_ok=True)
    for name, t in THEMES.items():
        files = {'header': header(p, s, t), 'stats': tiles(p, s, t), 'calendar': calendar(p, s, t), 'stack': stack(p, s, t)}
        if p.get('background'):
            files['about'] = about(p, t)
        for i, proj in enumerate(p['projects'], 1):
            files[f'work-{i}'] = project(proj, repos.get(proj.get('repo')), t)
        for key, content in files.items():
            with open(f'{a.out}/{key}-{name}.svg', 'w') as f:
                f.write(content)
    print(json.dumps({k: v for k, v in s.items() if k != 'days'}))


if __name__ == '__main__':
    main()
