"""Date helpers as Python SOURCE, for code nodes and hooks inside a workflow.

The workflow's sandbox runs snippets, not imports from here, so the helpers travel as text:
date_lib(holidays) returns source that defines them. The same text is exec'd in tests on this
machine, so what runs on Freya is exactly what was tested. Values (holidays, working days)
always come from the brief; nothing here knows any brief.
"""

DATE_LIB = '''import datetime, json
HOLIDAYS = set(%(holidays)r)
WORKDAYS = set(%(workdays)r)
DAYNAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
def to_date(s):
    return datetime.date.fromisoformat(str(s).strip()[:10])
def is_bd(d):
    return d.weekday() in WORKDAYS and d.isoformat() not in HOLIDAYS
def add_bd(d, n):
    while n > 0:
        d = d + datetime.timedelta(days=1)
        if is_bd(d):
            n -= 1
    return d
def next_bd(d):
    d = d + datetime.timedelta(days=1)
    while not is_bd(d):
        d = d + datetime.timedelta(days=1)
    return d
def bd_on_or_after(d):
    while not is_bd(d):
        d = d + datetime.timedelta(days=1)
    return d
def week_start(d):
    return d - datetime.timedelta(days=d.weekday())
def last_bd_of_week(d):
    e = week_start(d) + datetime.timedelta(days=6)
    while e >= week_start(d):
        if is_bd(e):
            return e
        e = e - datetime.timedelta(days=1)
    return None
def say(d):
    return DAYNAMES[d.weekday()] + ' ' + str(d.day) + ' ' + d.strftime('%%B %%Y') + ' (' + d.isoformat() + ')'
def money(x):
    return '%%.2f' %% float(x)
def day_table(today, weeks=3):
    rows = []
    start = week_start(today)
    for i in range(7 * (weeks + 1)):
        d = start + datetime.timedelta(days=i)
        if d < today:
            continue
        wk = (week_start(d) - start).days // 7
        tag = 'today' if d == today else ('this week' if wk == 0 else ('next week' if wk == 1 else 'in %%d weeks' %% wk))
        kind = 'business day' if is_bd(d) else ('HOLIDAY, not a business day' if d.isoformat() in HOLIDAYS else 'weekend, not a business day')
        rows.append('- ' + say(d) + ': ' + tag + ', ' + kind)
    return chr(10).join(rows)
'''


def date_lib(holidays, workdays=(0, 1, 2, 3, 4)):
    return DATE_LIB % {"holidays": sorted(holidays), "workdays": sorted(workdays)}


def load(holidays, workdays=(0, 1, 2, 3, 4)):
    """The helpers as a namespace, for tests on this machine."""
    ns = {}
    exec(date_lib(holidays, workdays), ns)
    return ns
