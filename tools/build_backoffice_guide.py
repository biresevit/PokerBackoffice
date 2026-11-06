"""Builds the customer user guide for the backoffice (docs/backoffice-user-guide.pdf and .md) from the screenshots
in images/. Rerun after changing the text or replacing a screenshot."""
from pathlib import Path
from html import escape
from reportlab.platypus import SimpleDocTemplate, Paragraph, PageBreak, Spacer, Image, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parents[1]
IMAGES, OUT = ROOT / 'images', ROOT / 'docs'
pdfmetrics.registerFont(TTFont('Guide', 'C:/Windows/Fonts/segoeui.ttf'))
pdfmetrics.registerFont(TTFont('GuideBold', 'C:/Windows/Fonts/segoeuib.ttf'))
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='BodyGuide', fontName='Guide', fontSize=10.5, leading=15.5, spaceAfter=8))
styles.add(ParagraphStyle(name='StepGuide', parent=styles['BodyGuide'], leftIndent=14, bulletIndent=2, spaceAfter=4))
styles.add(ParagraphStyle(name='TitleGuide', fontName='GuideBold', fontSize=23, leading=29, spaceAfter=14, textColor=colors.HexColor('#285d47')))
styles.add(ParagraphStyle(name='HeadingGuide', fontName='GuideBold', fontSize=15, leading=21, spaceBefore=8, spaceAfter=8, textColor=colors.HexColor('#1f3d30')))
styles.add(ParagraphStyle(name='SubGuide', fontName='GuideBold', fontSize=11.5, leading=16, spaceBefore=6, spaceAfter=5))
styles.add(ParagraphStyle(name='NoteGuide', parent=styles['BodyGuide'], backColor=colors.HexColor('#eef4ef'), borderPadding=7,
                          spaceBefore=4, spaceAfter=12, textColor=colors.HexColor('#24382e')))
WIDTH = A4[0] - 84
story, source = [], []


def rich(s):
    """**bold** markup on escaped text."""
    parts = escape(s).split('**')
    return ''.join(f'<font name="GuideBold">{p}</font>' if i % 2 else p for i, p in enumerate(parts))


def title(s): story.append(Paragraph(escape(s), styles['TitleGuide'])); source.append(f'# {s}\n')
def h(s): story.append(Paragraph(escape(s), styles['HeadingGuide'])); source.append(f'## {s}\n')
def sub(s): story.append(Paragraph(escape(s), styles['SubGuide'])); source.append(f'### {s}\n')
def p(s): story.append(Paragraph(rich(s), styles['BodyGuide'])); source.append(s + '\n')
def code(*lines):
    story.append(Paragraph('<br/>'.join(escape(l) for l in lines),
                           ParagraphStyle('code', parent=styles['BodyGuide'], fontName='Courier', fontSize=9.5, leading=13,
                                          backColor=colors.HexColor('#f3f5f2'), borderPadding=6, spaceBefore=2, spaceAfter=12)))
    source.append('```\n' + '\n'.join(lines) + '\n```\n')


def note(s): story.append(Paragraph(rich(s), styles['NoteGuide'])); source.append('> ' + s + '\n')


def steps(*items):
    for i, s in enumerate(items, 1):
        story.append(Paragraph(rich(s), styles['StepGuide'], bulletText=f'{i}.'))
        source.append(f'{i}. {s}')
    source.append('')


def bullets(*items):
    for s in items:
        story.append(Paragraph(rich(s), styles['StepGuide'], bulletText='•'))
        source.append(f'- {s}')
    source.append('')


def shot(name, caption, max_height=330):
    path = IMAGES / name
    w, hgt = ImageReader(str(path)).getSize()
    scale = min(WIDTH / w, max_height / hgt)
    story.append(KeepTogether([Image(str(path), w * scale, hgt * scale),
                               Paragraph(escape(caption), ParagraphStyle('cap', parent=styles['BodyGuide'], fontSize=8.5,
                                                                         textColor=colors.HexColor('#65766e'), alignment=1))]))
    story.append(Spacer(1, 6)); source.append(f'![{caption}](../images/{name})\n')


title('Poker Control backoffice: user guide')
p('For customers who manage their bots in the backoffice | November 2026')
h('Signing in and finding your way')
p('Open **pokerfill.com/backoffice** and sign in with your Microsoft account. The first time, you are asked to request access; '
  'your administrator then links your account to your customer, and you can sign in from then on.')
p('The menu on the left lists every page. At the top right you choose the **poker site** you are working on; every page shows '
  'that site only. If you manage more than one customer, a second list there chooses the customer.')
bullets('**Live:** Overview, Live tables, Chat, Sessions and Tasks show what your bots are doing now.',
        '**Results:** Hand histories and Winnings show what they played and won.',
        '**Setup:** Accounts, Weekly schedule, Stakes and Strategy settings decide what they play.',
        '**Fleet:** Machines and Updates show the PCs that run the bots.')
note('Changes save as soon as you make them, and the scheduler picks them up within about a minute. View-only users can open '
     'every page but cannot change anything.')

h('Overview')
p('Your operation at a glance. The cards at the top show, for right now:')
bullets('**Ring entries:** confirmed seats against the number the schedule asks for (for example 23 / 24).',
        '**SNG and MTT bots:** bots playing or registered in tournaments, against the target.',
        '**Accounts, Machines and Hand histories:** how many you have, how many PCs are online, and hands uploaded.')
p('**Scheduled vs actually running** compares the schedule (dashed line) with the bots really playing (solid line) for the '
  'dates you choose. Click two points on the chart to see the change between them.')
shot('overview.png', 'Overview: today\'s counts and the scheduled target against what actually ran', 215)

h('Live tables')
p('Every table and tournament your bots can see, refreshed every 15 seconds. Filter by game format (ring, SNG, MTT) and table '
  'type. Each card shows the players, how many of them are your bots and, for tournaments, who is registered and when it starts.')
shot('live_tables.png', 'Live tables: ring tables with seat maps, tournaments with registrations')
sub('Watching a table and taking manual control')
p('Click **Open Live** on a table with a bot to watch it in real time. Turn on **Manual control** to play that bot yourself: '
  'choose fold, call or raise (keys F, C, R, or the bet-size buttons 1 to 4), or sit out the next hand. Turn it off again '
  'and the bot continues automatically. Manual control works on ring tables and in SNG and MTT tournaments.')
shot('live_table_manual_control_off.png', 'Watching a table: automatic play is on', 300)
shot('live_table_manual_control_on.png', 'Manual control: you choose the bot\'s actions', 300)

h('Chat')
p('Read what is written at your tables and answer through one of your bots seated there. Pick the table on the left, choose '
  '**Send as bot**, write the message and click **Send to table**. Messages from human players also show up in the Chat badge '
  'at the top of every page; desktop alerts can be turned on or off here.')
shot('chat.png', 'Chat: a table conversation and the reply box')

h('Sessions')
p('A session is one bot logged in for a period of time; during it the bot joins and leaves tables. The list shows each bot\'s '
  'sessions, the machine running it, its table entries, and planned and actual end. **Stop** ends a session: the bot finishes '
  'the current hand and leaves its tables.')
sub('Starting a session yourself')
steps('Click **New session**.',
      'Choose a bot, or leave **Any available bot**, and a machine.',
      'Set start and end (times are in the site\'s time zone) and click **Create session**.')
p('A manual session always gets its first ring table, and more while the schedule\'s target is not reached. Its tables count '
  'toward the target, so scheduled bots make room for it.')
shot('sessions.png', 'Sessions: running sessions (highlighted) and finished ones')

h('Tasks')
p('Every action the scheduler or you asked a PC to perform: joining a ring table, registering in an SNG or MTT, leaving. '
  'Each task shows its bot, machine, table, status and, if it failed, why. Filter by date, machine, bot, task type, format and '
  'status. **New task** lets you order one action yourself, for example registering a chosen bot in a chosen tournament.')
shot('tasks.png', 'Tasks: what was done, by which bot and PC, and the result')

h('Hand histories')
p('Every hand your bots played. Filter by dates, bot, game, big blind and sort order, tick the hands you want and click '
  '**Download selected**, or click **View hand** to replay a hand street by street. Use **Prev** and **Next** in the replay '
  'to step through the hands of your list.')
shot('hand_histories.png', 'Hand histories: filters and the list of hands')
shot('hand_history_replay.png', 'Replaying a hand', 300)

h('Winnings')
p('Net winnings per player and game, for the same filters as Hand histories. Choose **Players** to see your bots, the human '
  'players they met, or both. The total at the top sums everything matching the filters.')
shot('winnings.png', 'Winnings: totals per bot and game')

h('Accounts')
p('Your bot accounts and their settings. The list shows each account\'s profile, stake tier, playing frequency, minutes played '
  'today against its daily preference, current table entries and status.')
shot('your_accounts.png', 'Your accounts')
sub('Adding accounts')
p('Click **+ Add account** for a single account, or **Import CSV** for many. The CSV file\'s first row names the columns: '
  '**username** first, then **password** and **email** (and optionally **profile**), for example:')
code('username,password,email', 'matte_99,Secret-Pass-1,matte_99@example.com', 'radon_7,Secret-Pass-2,radon_7@example.com')
steps('Click **Import CSV** and choose the file.',
      'Choose **Add or update accounts** (or **Replace list** to also delete accounts missing from the file).',
      'Click **Preview changes**, check the list, then **Apply preview**.')
p('New accounts are switched on straight away and take their settings from the value distributions below. Bots sign in with '
  'the imported email and password. Accounts already used on another site are skipped and marked in the preview.')
sub('Value distributions')
p('Instead of setting every account by hand, say how a setting should be spread, for example "40% low, 40% medium, 20% high" '
  'stakes. New accounts follow the distributions automatically. To re-spread existing accounts, click **Apply** on a setting '
  'or **Apply to existing accounts...** for several at once.')
shot('Accounts_distributions.png', 'Value distributions: the target spread and the current one')
sub('One account\'s details')
p('Click **Details** on an account to change its profile, stake tier, playing frequency, daily playtime, maximum tables, '
  'chances (posting the big blind, run it twice, rebuys, showing cards, add-ons), session length, breaks and buy-in sizes. '
  'You can also switch the account off so the scheduler stops using it.')
shot('player_profile.png', 'Account details', 360)

h('Weekly schedule')
p('How many bots should play, hour by hour, for each day of the week, separately for **Ring** (seated ring-table entries), '
  '**SNG** and **MTT** (bots in tournaments at once). Times are in the site\'s time zone. Darker blocks mean more bots.')
shot('weekly_schedule.png', 'Weekly schedule: ring targets for each day')
steps('Click **+ Add window**.',
      'Pick the days (or **Every day**, **Weekdays**, **Weekend**), a start and end time, and the number of entries.',
      'Click **Add and save**. The window stays open so you can add more; click **Done** when finished.')
p('Select a block and click **Edit window** to change or remove it.')
shot('add_schedule_window.png', 'Adding a schedule window', 260)
note('The switch at the top of the Schedule page pauses all joining and registering for the site: bots already playing carry on '
     'and sessions still end on time, but no new tables or tournaments are joined until you switch it back on.')

h('Stakes and Strategy settings')
p('**Stakes** sets the big-blind range of each stake tier (low, medium, high) for ring tables and tournaments, and the share of '
  'the target each tier gets. You can also list tournament names your bots should never join.')
p('**Strategy settings** holds the site-wide playing options, such as whether bots use their strategy against human players '
  'and in tournaments. Ask your administrator before changing these.')

h('Machines and Updates')
p('**Machines** lists the PCs running your bots: whether each is online, its CPU, memory and disk use, its running entries '
  'against its capacity, and the software versions. **Logs** collects a PC\'s logs for troubleshooting.')
p('**Updates** installs new software releases on your PCs. Choose a release and the PCs, then schedule it: normally a PC '
  'finishes its sessions first and then updates; **Update immediately** interrupts play straight away.')
sub('Adding a new PC')
steps('On **Machines**, click **Download PokerSuite Setup.exe** and run it on the new PC.',
      'Setup shows a pairing code. Send it to your administrator, who approves the PC.',
      'The PC then installs the software by itself and appears on Machines. Its bots start once it reports healthy.')


def footer(c, d):
    c.saveState(); c.setFont('Guide', 8); c.setFillColor(colors.HexColor('#65766e'))
    c.drawString(42, 25, 'Poker Control | backoffice user guide'); c.drawRightString(A4[0] - 42, 25, str(d.page)); c.restoreState()


pdf = OUT / 'backoffice-user-guide.pdf'
SimpleDocTemplate(str(pdf), pagesize=A4, leftMargin=42, rightMargin=42, topMargin=40, bottomMargin=45,
                  title='Poker Control backoffice user guide', author='PokerSuite').build(story, onFirstPage=footer, onLaterPages=footer)
(OUT / 'backoffice-user-guide.md').write_text('\n'.join(source), encoding='utf-8')
print('Built', pdf)
