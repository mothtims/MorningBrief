# TV Watchlist + Tech News Rotation: Design Proposal

Investigation-first, per instructions. All open decisions below are now
resolved — Peacemaker id=50603 confirmed, Demon Slayer stays in config
per the "dormant costs nothing" rule, feeds are Ars Technica + BBC Tech
(The Verge skipped), the `politics_line`→`news_line` rename is
confirmed, and the prompt wording intent (genericise the news mention,
encode the trim order, tone untouched) is confirmed. Nothing
implemented yet as of this doc — see the end of this file for build
status.

## 1. TV watchlist — investigation

### 1a. Show resolution (real TVmaze searches, not guessed IDs)

```
Lanterns (HBO)                     -> id=44776  premiered 2026-08-16  HBO           Running
House of the Dragon                -> id=44778  premiered 2022-08-21  HBO           Running
A Knight of the Seven Kingdoms     -> id=53063  premiered 2026-01-18  HBO           Running
Game of Thrones                    -> id=82     premiered 2011-04-17  HBO           Ended
Peacemaker                         -> id=50603  premiered 2022-01-13  HBO Max       Ended  [see note]
The Rings of Power                 -> id=33352  premiered 2022-09-02  Prime Video   Running
Jujutsu Kaisen                     -> id=48450  premiered 2020-10-02  MBS           Running
Invincible                         -> id=37196  premiered 2021-03-26  Prime Video   Running
X-Men '97                          -> id=58951  premiered 2024-03-20  Disney+       Running
Frieren: Beyond Journey's End      -> id=69956  premiered 2023-09-29  NTV           Running
Dandadan                           -> id=73023  premiered 2024-10-03  AbemaTV       Running
Sakamoto Days                      -> id=77383  premiered 2025-01-11  TV Tokyo      Running
Demon Slayer                       -> id=41469  premiered 2019-04-06  Fuji TV       Ended  [see note]
```

All 13 resolved to a single unambiguous match **except** two worth
your explicit sign-off:

- **Peacemaker**: top match (id=50603, the John Cena HBO Max show) and
  a second entry (id=12686, a 2003 Japanese anime also literally
  titled "Peacemaker," TV Asahi) scored almost identically (0.89 vs
  0.88) — TVmaze's fuzzy-search score doesn't discriminate well here.
  I checked both shows' content directly (language, genre, summary) to
  confirm id=50603 is the right one — English-language, Scripted,
  matches the HBO Max synopsis. High confidence, but flagging since
  the score alone would've been a coin flip.
- **Frieren**: a second, much lower-scored result (id=80137, "Sousou
  no Frieren: ●● no Mahou," YouTube, score 0.44 vs the top match's
  0.54) looks like a companion/extras series under a similar title,
  not the main show. Not a real ambiguity, just flagging for
  completeness.

Also worth flagging even though it's not a naming ambiguity: **Demon
Slayer shows `status: Ended`, `ended: 2024-06-30`** — that's not TVmaze
being stale, I checked. TVmaze's entry for this show covers TV
broadcast seasons only (through Season 4 / the Hashira Training Arc,
June 2024); the current story is continuing via the **Infinity Castle**
theatrical trilogy, not TV episodes. TVmaze tracks TV broadcast
schedules, not cinema releases, so this watchlist entry will
legitimately never fire again unless/until a new TV season is
announced — even though the franchise itself is very much active. This
matches your "include ended/dormant shows anyway, zero daily cost"
instruction, but it's worth knowing *why* it'll stay silent, so a
silent Demon Slayer entry doesn't get mistaken for a bug later.

**Game of Thrones** is included per your instruction, `status: Ended`,
correctly dormant — will only ever fire if TVmaze records a revival.

### 1b. Anime airdate caveat (JP broadcast vs UK availability)

TVmaze's episode data for the six anime entries (Jujutsu Kaisen,
Frieren, Dandadan, Sakamoto Days, Demon Slayer, and any future anime
additions) tracks the **original Japanese network broadcast**
(MBS/NTV/AbemaTV/TV Tokyo/Fuji TV) — not any UK streaming platform's
release. Two practical implications for wording:

- Modern simulcast anime (all of the currently-running titles above)
  typically hit Crunchyroll/Netflix within roughly an hour of JP
  broadcast, so the *lag* usually isn't the issue — but "brief says
  it's out, but it isn't on your streaming service yet" is still
  possible for an edge case, so the design should say **"new episode
  airs today"** rather than **"out now, go watch it"** — accurate to
  what's actually known, not overpromising availability.
- JP is UTC+9; a show airing in a late-night JST slot (very common for
  anime, e.g. 00:30 JST) can fall on what's still the *previous*
  calendar day in UK time. The window calculation must use TVmaze's
  `airstamp` field (an absolute UTC instant) for the "today or next
  48h" check, never the plain `airdate` string (a JST-relative date) —
  using `airdate` directly risks an off-by-one-day error right at that
  boundary. Noting this as an implementation detail to get right, not
  something needing your input.

### 1c. Config shape

```json
{
  "tv_watchlist": [
    {"name": "Lanterns", "tvmaze_id": 44776},
    {"name": "House of the Dragon", "tvmaze_id": 44778},
    {"name": "A Knight of the Seven Kingdoms", "tvmaze_id": 53063},
    {"name": "Game of Thrones", "tvmaze_id": 82},
    {"name": "Peacemaker", "tvmaze_id": 50603},
    {"name": "The Rings of Power", "tvmaze_id": 33352},
    {"name": "Jujutsu Kaisen", "tvmaze_id": 48450},
    {"name": "Invincible", "tvmaze_id": 37196},
    {"name": "X-Men '97", "tvmaze_id": 58951},
    {"name": "Frieren: Beyond Journey's End", "tvmaze_id": 69956},
    {"name": "Dandadan", "tvmaze_id": 73023},
    {"name": "Sakamoto Days", "tvmaze_id": 77383},
    {"name": "Demon Slayer", "tvmaze_id": 41469}
  ]
}
```

`config.example.json` gets `"tv_watchlist": []`. Adding a show later
means one more object in this list — I'd propose `tv_watchlist.py`
grow a small `--resolve "Show Name"` CLI mode (mirroring `weather.py`'s
`__main__` block) so future additions don't need a hand-run API query,
but that's a nice-to-have, not required for v1.

### 1d. New module: `tv_watchlist.py` (flat layout)

```python
def summarize_tv_watchlist(watchlist: list[dict]) -> str:
    """Three-way contract, different from the other fetchers:
    - Nothing airing in the window -> "" (empty string - caller omits
      the section entirely, no filler).
    - Something airing -> a short line.
    - TVmaze unreachable -> a visible degraded note (never "", never
      raises) - same visibility principle as weather/trains/politics,
      just not the *default* outcome the way it is for them."""
```

Internals sketch:

```python
def _next_episode(show_id: int) -> dict | None:
    data = get_json(f"{TVMAZE_BASE}/shows/{show_id}?embed=nextepisode", log)
    return data.get("_embedded", {}).get("nextepisode")

def summarize_tv_watchlist(watchlist: list[dict]) -> str:
    if not watchlist:
        return ""

    upcoming, errors = [], 0
    for show in watchlist:
        try:
            ep = _next_episode(show["tvmaze_id"])
        except Exception as exc:
            log.warning("TVmaze lookup failed for %s: %s", show["name"], exc)
            errors += 1
            continue
        if ep and _airs_within_48h(ep):   # uses airstamp, not airdate
            upcoming.append((show["name"], ep))

    if errors == len(watchlist):
        return "TV watchlist unavailable right now."
    if not upcoming:
        return ""
    return "; ".join(_format_line(name, ep) for name, ep in upcoming)
```

Per-show lookups fail independently (one bad ID or a transient hiccup
on one show doesn't blank the whole section) — only escalates to a
visible failure note if *every* lookup failed, which is the signal
that TVmaze itself is down rather than one show having no upcoming
episode. 13 shows means 13 API calls per brief run, well under
TVmaze's documented 20-calls/10-seconds limit (no key required); worth
revisiting only if the watchlist grows substantially.

### 1e. Failure mode

Matches your instruction directly: `summarize_tv_watchlist()` never
raises. Genuine silence (nothing airing) costs nothing — literally no
section appears in text or voice. A real TVmaze outage produces one
visible line, same visibility principle as the other fetchers.

## 2. Tech news section — investigation

### 2a. Feed candidates (verified live, not just proposed)

| Feed | Format | Result |
|---|---|---|
| Ars Technica (`feeds.arstechnica.com/arstechnica/index`) | RSS 2.0 | ✅ 20 items, parses cleanly with `politics.py`'s existing `./channel/item` approach |
| BBC Technology (`feeds.bbci.co.uk/news/technology/rss.xml`) | RSS 2.0 | ✅ 21 items, same BBC infrastructure `politics.py` already trusts |
| The Verge (`theverge.com/rss/index.xml`) | **Atom**, not RSS | ⚠️ Parses to 0 items with the existing RSS-only code — it's a `<feed>`/`<entry>` Atom document, not `<rss>`/`<channel>`/`<item>` |

**Recommendation: Ars Technica + BBC Technology.** Both are proper RSS
2.0 and drop straight into `politics.py`'s existing parsing pattern
with zero new code. The Verge is a fine outlet but would need a second
parser branch (Atom's `<entry>`/`<updated>`/`<summary>` instead of
RSS's `<item>`/`<pubDate>`/`<description>`) for one feed — not worth
the added complexity unless you specifically want it. Happy to add it
later if you do.

### 2b. New module: `tech_news.py` (mirrors `politics.py` exactly)

Same shape as `politics.py`: fetch headlines from both feeds (or pick
one — your call, listed both since it doubles headline diversity for
roughly free), same `claude -p` no-tool-access summarization call,
same `CLAUDE_BINARY` absolute-path pattern, same
`.claude/settings-notools.json`, same retry/logging via
`httputil.get_bytes`/`logutil`. Failure mode identical to
`politics.py`: degraded to a plain headline list if the `claude -p`
call fails, a visible "unavailable" note if the fetch itself fails.

## 3. Section rotation mechanism in `brief.py`

Reuses the hour check that already exists for leg selection — no
parallel time check, per your instruction.

```python
def is_morning_send(now_hour: int | None = None) -> bool:
    return (now_hour if now_hour is not None else datetime.now().hour) < LEG_SWITCH_HOUR

def pick_leg(config: dict, morning: bool) -> dict:
    return config["morning_leg"] if morning else config["evening_leg"]

def gather_brief_data() -> BriefData:
    config = load_config()
    morning = is_morning_send()
    leg = pick_leg(config, morning)

    return BriefData(
        calendar_line=summarize_calendar(config.get("calendar_allowlist", [])),
        train_line=summarize_leg(leg["from"], leg["to"], leg["departs"]),
        weather_line=summarize_weather(config["home_postcode"]),
        tv_line=summarize_tv_watchlist(config.get("tv_watchlist", [])),
        news_label="Politics headlines" if morning else "Tech news",
        news_line=summarize_politics() if morning else summarize_tech(),
    )
```

**Flagging a rename**: `BriefData.politics_line` becomes
`BriefData.news_line` (plus a new `news_label` field). A field
literally called `politics_line` holding tech content half the time
would be actively misleading — small, contained rename (touches
`brief.py` and `voice_script.py` only) but worth knowing it's not
purely additive.

`format_text()` changes from a fixed template to conditional section
assembly, so the TV line can be omitted cleanly (and any future
optional section can reuse the same pattern):

```python
def format_text(data: BriefData) -> str:
    sections = [
        f"📅 {data.calendar_line}",
        f"🚆 {data.train_line}",
        f"🌤 {data.weather_line}",
    ]
    if data.tv_line:
        sections.append(f"📺 {data.tv_line}")
    sections.append(f"📰 {data.news_line}")
    return "\n\n".join(sections)
```

Proposed order — calendar, train, weather, TV (if present), news last
— matches the voice prioritisation you specified. Open to reordering if
you'd rather TV appear elsewhere.

## 4. `voice_script.py` prompt changes — flagging for your eyes, as requested

Tone instructions (warm/cheerful, contractions, direct address, no
list-like phrasing, light humour) are **unchanged** — not touching
those. Two structural changes to the prompt mechanics:

**1. The data block becomes assembled, not fixed**, so the TV line can
be conditionally included exactly like `format_text()`:

```python
data_lines = [
    f"Calendar: {data.calendar_line}",
    f"Train: {data.train_line}",
    f"Weather: {data.weather_line}",
]
if data.tv_line:
    data_lines.append(f"TV: {data.tv_line}")
data_lines.append(f"{data.news_label}: {data.news_line}")
data_block = "\n\n".join(data_lines)
```

**2. Two lines of prompt prose need updating** to reflect variable
section count and your explicit trim-priority:

- Current: *"Given this data - today's calendar, train status,
  weather, and headline summaries - turn it into that kind of
  script."* → would become something like *"Given this data below -
  today's calendar, train status, weather, and news, plus TV when
  there's an upcoming episode - turn it into that kind of script."*
- Current: *"with four data points to cover in the same word budget,
  keep each one to a sentence or two"* → needs to become
  count-agnostic and encode your priority order, something like:
  *"If you need to trim to stay in budget, shorten or drop the news
  section first, then TV if present — calendar and train details
  should never be cut."*

Exact wording is negotiable — flagging that this prompt needs a small
edit, not asking you to write it. Let me know if you want to adjust
the phrasing before I apply it.

## 5. Draft ADR for `MorningBrief/DECISIONS.md`

---

### ADR-0002: Section rotation reuses the existing leg-selection time check, not a parallel switch

**Context:** The 16:30 send needs to carry a technology section instead
of politics, while the 07:00 send keeps politics — a genuine content
swap, not an additional section. `brief.py` already computes
`now_hour < LEG_SWITCH_HOUR` once, to pick which commute leg
(`morning_leg`/`evening_leg`) to report on. Adding a second,
independently-computed time check for the news-section choice would
create two sources of truth for "is this a morning or afternoon send,"
with the attendant risk of them disagreeing (e.g. one gets a threshold
tweak later and the other doesn't).

**Decision:** Factor the existing hour check into a named
`is_morning_send()` function, computed once per `gather_brief_data()`
call, and use that single boolean for both `pick_leg()` and the
news-section choice (`summarize_politics()` vs `summarize_tech()`).
`BriefData.politics_line` is renamed to `BriefData.news_line` (with a
paired `news_label` field), since a field named for one topic holding
another topic's content half the time would be misleading.

**Consequences:** `LEG_SWITCH_HOUR` (13:00) now implicitly governs three
things — leg selection, train direction, and news topic — from one
place. Any future section that should also vary by time of day (rather
than being a new independent fetcher like TV) should extend this same
boolean rather than adding another time check. The rename touches
`brief.py` and `voice_script.py`'s prompt-formatting call; no other
files reference the old field name.

---

## 6. Scope estimate

- `tv_watchlist.py`: new module, ~50-70 lines (similar size to
  `calendar_events.py`'s dedupe/format logic, but simpler — no TCC, no
  timezone-conversion display since only a date/time window check is
  needed).
- `tech_news.py`: new module, near-identical to `politics.py`, ~60-70
  lines (two feeds instead of one).
- `brief.py`: `is_morning_send()` extraction, `BriefData` gets 3 new
  fields (`tv_line`, `news_label`, rename `politics_line`→`news_line`),
  `format_text()` becomes list-based. Small-to-moderate, contained.
- `voice_script.py`: data-block assembly change + two prompt-prose
  edits (shown above, pending your wording sign-off).
- `config.example.json`/`config.local.json`: `tv_watchlist` key added
  (13 shows, IDs already resolved above).
- `pyproject.toml`/`uv.lock`: no new dependencies — both new modules
  use only `httputil`/`logutil`/stdlib, same as the existing fetchers.
- `DECISIONS.md`: ADR-0002 (drafted above).
- No launchd/schedule changes — this rides the existing twice-daily
  schedule for both text and voice.

Overall: two contained new fetcher modules following exactly the
established pattern, one small structural change to `brief.py` (the
rotation + optional-section mechanism), and one prompt edit that
genuinely needs your eyes before it ships.

## 7. Decisions

All resolved:

- Peacemaker: id=50603, confirmed.
- Demon Slayer: stays in config, dormant, per the "costs nothing" rule.
- Feeds: Ars Technica + BBC Technology; The Verge skipped.
- Rename: `politics_line` → `news_line`, confirmed.
- Prompt wording: intent confirmed as described in section 4 — genericise
  the news mention, encode the trim order, tone untouched. Exact final
  wording to be written during implementation and shown before it ships.

Ready to build.
