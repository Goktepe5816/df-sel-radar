# Sel radarı (Disaster Frontline): ABD sel olaylarını rakipten önce yakalar, Telegram botuyla telefona yazar.
# Saatte bir launchd ile çalışır. Kullanım: python3 sel_radar.py [--dry]
# Kaynaklar: NWS uyarıları (api.weather.gov), NOAA nehir ölçümleri (NWPS), Google Trends ABD, rakip GWN RSS.
import os, sys, shutil, json, re, html, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

D = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(D, 'gorulen_sel.json')
TG = os.path.join(os.path.dirname(D), '_assets', 'telegram_api.txt')
TR = timezone(timedelta(hours=3))  # bulutta (UTC) da TR saati
UA = {'User-Agent': 'DFSelRadar/1.0 (personal news monitor)'}
DRY = '--dry' in sys.argv
NOW = datetime.now(timezone.utc)
DAY = NOW.strftime('%Y-%m-%d')

# Büyük metro çekirdek ilçeleri (NWS areaDesc biçimi "Ilce, ST"). Kural: metro >=500 bin veya ulusal bilinirlik.
METRO = {
 'Los Angeles, CA':'Los Angeles','Orange, CA':'Orange County','San Diego, CA':'San Diego','Riverside, CA':'Riverside',
 'San Bernardino, CA':'San Bernardino','Ventura, CA':'Ventura','Santa Clara, CA':'San Jose','San Francisco, CA':'San Francisco',
 'Alameda, CA':'Oakland','Sacramento, CA':'Sacramento','Fresno, CA':'Fresno','Kern, CA':'Bakersfield',
 'Maricopa, AZ':'Phoenix','Pima, AZ':'Tucson','Clark, NV':'Las Vegas','Washoe, NV':'Reno','Salt Lake, UT':'Salt Lake City',
 'Denver, CO':'Denver','El Paso, CO':'Colorado Springs','Bernalillo, NM':'Albuquerque','El Paso, TX':'El Paso',
 'Harris, TX':'Houston','Fort Bend, TX':'Houston','Montgomery, TX':'Houston','Galveston, TX':'Galveston','Dallas, TX':'Dallas',
 'Tarrant, TX':'Fort Worth','Collin, TX':'Dallas','Denton, TX':'Dallas','Travis, TX':'Austin','Williamson, TX':'Austin',
 'Bexar, TX':'San Antonio','Kerr, TX':'Kerrville','Hidalgo, TX':'McAllen','Cameron, TX':'Brownsville','Nueces, TX':'Corpus Christi',
 'Oklahoma, OK':'Oklahoma City','Tulsa, OK':'Tulsa','Sedgwick, KS':'Wichita','Jackson, MO':'Kansas City','St. Louis, MO':'St. Louis',
 'St. Louis City, MO':'St. Louis','Douglas, NE':'Omaha','Hennepin, MN':'Minneapolis','Cook, IL':'Chicago','DuPage, IL':'Chicago',
 'Milwaukee, WI':'Milwaukee','Wayne, MI':'Detroit','Oakland, MI':'Detroit','Franklin, OH':'Columbus','Cuyahoga, OH':'Cleveland',
 'Hamilton, OH':'Cincinnati','Marion, IN':'Indianapolis','Jefferson, KY':'Louisville','Davidson, TN':'Nashville',
 'Shelby, TN':'Memphis','Knox, TN':'Knoxville','Hamilton, TN':'Chattanooga','Fulton, GA':'Atlanta','DeKalb, GA':'Atlanta',
 'Cobb, GA':'Atlanta','Gwinnett, GA':'Atlanta','Chatham, GA':'Savannah','Jefferson, AL':'Birmingham','Mobile, AL':'Mobile',
 'Orleans, LA':'New Orleans','Jefferson, LA':'New Orleans','East Baton Rouge, LA':'Baton Rouge','Hinds, MS':'Jackson',
 'Pulaski, AR':'Little Rock','Miami-Dade, FL':'Miami','Broward, FL':'Fort Lauderdale','Palm Beach, FL':'West Palm Beach',
 'Hillsborough, FL':'Tampa','Pinellas, FL':'St. Petersburg','Orange, FL':'Orlando','Duval, FL':'Jacksonville',
 'Lee, FL':'Fort Myers','Brevard, FL':'Brevard / Space Coast','Leon, FL':'Tallahassee','Mecklenburg, NC':'Charlotte',
 'Wake, NC':'Raleigh','Buncombe, NC':'Asheville','Charleston, SC':'Charleston','Richland, SC':'Columbia',
 'Fairfax, VA':'Northern Virginia','Virginia Beach City, VA':'Virginia Beach','Norfolk City, VA':'Norfolk',
 'District of Columbia, DC':'Washington DC','Baltimore City, MD':'Baltimore','Philadelphia, PA':'Philadelphia',
 'Allegheny, PA':'Pittsburgh','New York, NY':'New York City','Kings, NY':'Brooklyn','Queens, NY':'Queens','Bronx, NY':'Bronx',
 'Hudson, NJ':'Jersey City','Essex, NJ':'Newark','Suffolk, MA':'Boston','Erie, NY':'Buffalo','King, WA':'Seattle',
 'Pierce, WA':'Tacoma','Snohomish, WA':'Everett','Multnomah, OR':'Portland','Honolulu, HI':'Honolulu','Anchorage, AK':'Anchorage',
 'Coconino, AZ':'Grand Canyon / Flagstaff','Yavapai, AZ':'Sedona / Prescott','Park, WY':'Yellowstone',
}
SEL = re.compile(r'flood|flash flood|storm surge|king tide|atmospheric river|levee|dam (break|fail)|evacuat', re.I)
ABD = re.compile(r'\b(US|U\.S\.|USA|America|Texas|California|Florida|Arizona|Nevada|Georgia|Tennessee|Carolina|Virginia|'
                 r'New York|New Jersey|Louisiana|Mississippi|Alabama|Kentucky|Ohio|Colorado|Utah|Oregon|Washington|Hawaii|'
                 r'Alaska|Oklahoma|Kansas|Missouri|Arkansas|Pennsylvania|Michigan|Illinois|Wisconsin|Minnesota|Iowa|'
                 r'Nebraska|Montana|Idaho|Wyoming|New Mexico|Maryland|Massachusetts|Puerto Rico|' + '|'.join(
                 sorted({re.escape(v.split(' /')[0]) for v in METRO.values()})) + r')\b', re.I)

def get(url, timeout=40):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()

def metrolar(area):
    return sorted({METRO[a.strip()] for a in area.split(';') if a.strip() in METRO})

def nws():
    d = json.loads(get('https://api.weather.gov/alerts/active?status=actual&event=Flash%20Flood%20Warning,Flood%20Warning,Flash%20Flood%20Statement,Coastal%20Flood%20Warning,High%20Surf%20Warning'))
    yigin = {}
    for f in d['features']:
        p = f['properties']; pa = p.get('parameters') or {}
        ev, area, office = p['event'], p['areaDesc'], p.get('senderName', 'NWS')
        if ev in ('Flash Flood Warning', 'Flood Warning'):
            for z in area.split(';'):
                yigin.setdefault(z.strip()[-2:], set()).add(z.strip())
        tehdit = (pa.get('flashFloodDamageThreat') or [''])[0]
        m = metrolar(area)
        url = 'https://forecast.weather.gov/wwamap/wwatxtget.php?cwa=usa&wwa=' + urllib.parse.quote(ev)
        if tehdit == 'CATASTROPHIC':
            yield 10, f'ffe:{office}:{DAY}', '🚨 FLASH FLOOD EMERGENCY', f"{area[:140]} ({office})" + (f" — METRO: {', '.join(m)}" if m else ''), url
        elif m and ev == 'Flash Flood Warning':
            puan = 8 if tehdit == 'CONSIDERABLE' else 6
            yield puan, f"ffw:{'+'.join(m)}:{DAY}", f"⚠️ Flash Flood Warning — {', '.join(m)}" + (' (CONSIDERABLE)' if tehdit == 'CONSIDERABLE' else ''), area[:140], url
        elif ev in ('High Surf Warning', 'Coastal Flood Warning') and not m:
            yield 5, f"kiyi:{ev}:{office}:{DAY}", f"🌊 {ev} — {area.split(';')[0][:60]}", f"{area[:140]} ({office})", url
        elif m and ev in ('Flood Warning', 'Coastal Flood Warning', 'High Surf Warning'):
            yield 5, f"fw:{ev}:{'+'.join(m)}:{DAY}", f"🌊 {ev} — {', '.join(m)}", area[:140], url

    for st, ilc in yigin.items():
        if len(ilc) >= 3:
            yield 6, f"yigin:{st}:{DAY}:{len(ilc) // 3}", f"🌧️ {st}: {len(ilc)} ilçede aynı anda sel uyarısı", '; '.join(sorted(ilc)[:6]), 'https://forecast.weather.gov/wwamap/wwatxtget.php?cwa=usa&wwa=Flash%20Flood%20Warning'

def nwps():
    d = json.loads(get('https://api.water.noaa.gov/nwps/v1/gauges?bbox.xmin=-170&bbox.ymin=17&bbox.xmax=-64&bbox.ymax=72&srid=EPSG_4326', timeout=120))
    major = {}
    for g in d.get('gauges', d):
        st = g.get('status', {})
        obs, fc = st.get('observed', {}).get('floodCategory'), st.get('forecast', {}).get('floodCategory')
        if 'major' in (obs, fc) and not re.search(r'tide|devils lake|stump lake', g['name'], re.I):
            major.setdefault(g['state']['abbreviation'], []).append(g['name'] + ('' if obs == 'major' else ' (tahmin)'))
    for st, names in major.items():
        if len(names) >= 2:
            yield 7, f"nwps:{st}:{DAY}", f"🏞️ {st}: {len(names)} nehir noktası MAJOR taşkında", '; '.join(names[:4]), 'https://water.noaa.gov'

def trends():
    x = ET.fromstring(get('https://trends.google.com/trending/rss?geo=US'))
    ns = {'ht': 'https://trends.google.com/trending/rss'}
    for it in x.iter('item'):
        q = it.findtext('title') or ''
        if SEL.search(q):
            trafik = it.findtext('ht:approx_traffic', '', ns)
            yield 6, f"tr:{q.lower()}:{DAY}", f"📈 Google Trends ABD: '{q}' aranıyor ({trafik})", '', 'https://trends.google.com/trending?geo=US'


# NATURE ALERT (Avrupa) — 2026-11-18 yeniden: uyarı değil GERÇEK OLAY yakala.
# 1) Google News yerel dil haber yoğunluğu (heyelan/sel/tahliye/mahsur) 2) EMSC deprem M4.8+ 3) Meteoalarm KIRMIZI
# 4) GWN'nin Avrupa videoları 5) YouTube'da Avrupa afet videosu talebi (6 saatte bir). Hepsi ayrı 'NATURE ALERT' mesajında.
AB = {'france':'🇫🇷 Fransa','spain':'🇪🇸 İspanya','italy':'🇮🇹 İtalya','germany':'🇩🇪 Almanya','united-kingdom':'🇬🇧 İngiltere',
      'greece':'🇬🇷 Yunanistan','portugal':'🇵🇹 Portekiz','austria':'🇦🇹 Avusturya','poland':'🇵🇱 Polonya','czechia':'🇨🇿 Çekya',
      'romania':'🇷🇴 Romanya','croatia':'🇭🇷 Hırvatistan','slovenia':'🇸🇮 Slovenya','switzerland':'🇨🇭 İsviçre','belgium':'🇧🇪 Belçika',
      'netherlands':'🇳🇱 Hollanda','ireland':'🇮🇪 İrlanda','norway':'🇳🇴 Norveç','sweden':'🇸🇪 İsveç','bulgaria':'🇧🇬 Bulgaristan'}
AB_OLAY = re.compile(r'flood|rain|thunder|storm|wind|coastal', re.I)
def avrupa():
    """Meteoalarm: sadece KIRMIZI ya da 10+ bölgede TURUNCU (turuncu tek başına olay değil, gürültü)."""
    cap = '{urn:oasis:names:tc:emergency:cap:1.2}'; ns = '{http://www.w3.org/2005/Atom}'
    for slug, ad in AB.items():
        try:
            x = ET.fromstring(get(f'https://feeds.meteoalarm.org/feeds/meteoalarm-legacy-atom-{slug}'))
        except Exception:
            continue
        grup = {}
        for e in x.iter(ns + 'entry'):
            sev = e.findtext(cap + 'severity') or ''; ev = e.findtext(cap + 'event') or ''
            if sev in ('Severe', 'Extreme') and AB_OLAY.search(ev):
                tur = re.sub(r'^(Severe|Extreme|Moderate|Orange|Red)\s+|\s+warning$', '', ev, flags=re.I)
                grup.setdefault((sev, tur), set()).add(e.findtext(cap + 'areaDesc') or '')
        for (sev, tur), yer in grup.items():
            if sev == 'Severe' and len(yer) < 10:
                continue
            renk = '🔴 KIRMIZI' if sev == 'Extreme' else '🟠 TURUNCU'
            yield (15 if sev == 'Extreme' else 8), f"na:ma:{slug}:{sev}:{tur}:{DAY}", f"{ad}: Meteoalarm {renk} {tur} — {len(yer)} bölge", '; '.join(sorted(yer)[:6]), 'https://meteoalarm.org'

NA_HABER = [  # (ülke, dil, gl, sorgu) — yerel dilde HASAR/ETKİ kelimeleri (tahmin değil)
    ('🇮🇹 İtalya','it','IT','frana isolati'), ('🇮🇹 İtalya','it','IT','alluvione sfollati'), ('🇮🇹 İtalya','it','IT','esondazione fiume evacuazione'),
    ('🇮🇹 İtalya','it','IT','eruzione Etna'), ('🇫🇷 Fransa','fr','FR','inondations évacués'), ('🇫🇷 Fransa','fr','FR','crue routes coupées'),
    ('🇫🇷 Fransa','fr','FR','vigilance rouge crues'), ('🇪🇸 İspanya','es','ES','inundaciones desalojados'), ('🇪🇸 İspanya','es','ES','DANA riada rescate'),
    ('🇵🇹 Portekiz','pt-PT','PT','inundações desalojados Portugal'), ('🇬🇷 Yunanistan','el','GR','πλημμύρες εκκένωση'), ('🇬🇷 Yunanistan','el','GR','κατολίσθηση αποκλεισμένοι'),
    ('🇩🇪 Almanya','de','DE','Hochwasser evakuiert'), ('🇦🇹 Avusturya','de','AT','Hochwasser Mure'), ('🇨🇭 İsviçre','de','CH','Murgang evakuiert'),
    ('🇬🇧 İngiltere','en','GB','flooding evacuated England OR Scotland OR Wales'), ('🇬🇧 İngiltere','en','GB','"major incident" flooding'),
    ('🇵🇱 Polonya','pl','PL','powódź ewakuacja'), ('🇨🇿 Çekya','cs','CZ','povodně evakuace'), ('🇭🇷 Hırvatistan','hr','HR','poplave evakuacija'),
    ('🇧🇦 Bosna','bs','BA','poplave evakuacija'), ('🇷🇴 Romanya','ro','RO','inundații evacuați'), ('🇸🇮 Slovenya','sl','SI','poplave evakuacija'),
    ('🇮🇸 İzlanda','is','IS','eldgos'), ('🇳🇴 Norveç','no','NO','flom evakuert'),
]
NON_EU = re.compile(r'Bahia|Brasil|Brazil|Rio |São Paulo|Minas|Pernambuco|México|Mexico|Chalco|Argentin|Colombia|Chile|Peru|Venezuela|'
                    r'Texas|Florida|California|Carolina|Kentucky|Colorado|St\\. Louis|Missouri|Washington|Oregon|USA|U\\.S\\.|America|Canada|'
                    r'Australia|India|Pakistan|Vietnam|Indonesia|Philippin|China|Japan|Africa|Nigeria|Kenya|Iraq|Iran|Gaza|KUNC', re.I)
def na_haber():
    """Bir ülkede son 12 saatte etki haberi yoğunlaşınca (3/8/15 eşik) yaz. Örnek başlıklarla."""
    sayac, ornek = {}, {}
    for ulke, hl, gl, q in NA_HABER:
        try:
            x = ET.fromstring(get(f'https://news.google.com/rss/search?q={urllib.parse.quote(q + " when:12h")}&hl={hl}&gl={gl}&ceid={gl}:{hl}'))
        except Exception:
            continue
        for it in x.iter('item'):
            t = it.findtext('title') or ''
            if NON_EU.search(t):
                continue
            k = re.sub(r'\W+', ' ', t.lower())[:50]
            if k in ornek.setdefault(ulke, {}):
                continue
            ornek[ulke][k] = (t, it.findtext('link') or '')
            sayac[ulke] = sayac.get(ulke, 0) + 1
    for ulke, n in sayac.items():
        esik = 15 if n >= 15 else 8 if n >= 8 else 3 if n >= 3 else 0
        if not esik:
            continue
        ilk = list(ornek[ulke].values())
        yield (8 + esik // 2), f"na:haber:{ulke}:{esik}:{DAY}", f"{ulke}: son 12 saatte {n} hasar/tahliye haberi", ' | '.join(t[:90] for t, _ in ilk[:3]), ilk[0][1]

def na_deprem():
    s = (NOW - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%S')
    d = json.loads(get(f'https://www.seismicportal.eu/fdsnws/event/1/query?format=json&minmag=4.8&start={s}&minlat=34&maxlat=72&minlon=-25&maxlon=45'))
    for f in d['features']:
        p = f['properties']
        yield (13 if p['mag'] >= 5.5 else 9), f"na:emsc:{f['id']}", f"🌍 DEPREM M{p['mag']:.1f} — {p.get('flynn_region','')}", f"{p.get('time','')[:16]} UTC, derinlik {p.get('depth','?')} km", f"https://www.emsc-csem.org/Earthquake_information/earthquake.php?id={f['id']}"

AB_KELIME = re.compile(r'Ital|Tuscan|Sicil|Sardin|Venice|Rome|Milan|Genoa|Naples|France|French|Paris|Marseille|Nice|Corsica|Spain|Spanish|Valencia|'
                       r'Barcelona|Madrid|Malaga|Andalus|Mallorca|Canary|Portugal|Lisbon|Madeira|Greece|Greek|Athens|Crete|Rhodes|UK|Britain|England|'
                       r'Scotland|Wales|Ireland|London|Germany|Austria|Switzerland|Swiss|Alps|Poland|Czech|Slovenia|Croatia|Bosnia|Serbia|Romania|'
                       r'Bulgaria|Norway|Sweden|Iceland|Etna|Vesuvius|Campi Flegrei|Europe|Belgium|Netherlands|Dutch|Albania|Montenegro', re.I)
def na_rakip():
    for t, pub, izl, url in rakip_videolar(RAKIP['GWN']):
        if AB_KELIME.search(t) and NOW - pub <= timedelta(hours=6):
            saat = max((NOW - pub).total_seconds() / 3600, 0.25)
            yield (18 if izl / saat >= 10000 else 11), f"na:gwn:{url}", f"🆕 GWN Avrupa videosu ({saat:.1f} sa, {izl:,} izl) — konu bizde de olabilir", t, url

NA_YT_Q = ['Italy flood', 'France flood', 'Spain flood', 'Greece flood', 'UK storm flooding', 'Europe landslide']
def na_youtube():
    """6 saatte bir (kota): son 12 saatte yüklenmiş Avrupa afet videosu 10K+ izlendiyse talep var."""
    h = datetime.now(TR)
    if h.hour % 6 != 0 or h.minute >= 15:
        return
    key = os.environ.get('YT_API_KEY')
    kf = os.path.join(os.path.dirname(D), '_assets', 'youtube_api_key.txt')
    if not key and os.path.exists(kf):
        key = open(kf).read().strip()
    if not key:
        return
    after = (NOW - timedelta(hours=12)).strftime('%Y-%m-%dT%H:%M:%SZ')
    for q in NA_YT_Q:
        r = json.loads(get('https://www.googleapis.com/youtube/v3/search?' + urllib.parse.urlencode(dict(
            part='id', q=q, type='video', order='viewCount', publishedAfter=after, maxResults=5, key=key))))
        ids = ','.join(i['id']['videoId'] for i in r.get('items', []))
        if not ids:
            continue
        vs = json.loads(get('https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics&id=' + ids + '&key=' + key))
        for v in vs['items']:
            izl = int(v['statistics'].get('viewCount', 0)); t = v['snippet']['title']
            if izl >= 10000 and AB_KELIME.search(t):
                yield 12, f"na:yt:{v['id']}", f"📺 Avrupa talebi: {izl:,} izlenme (≤12 sa) — {v['snippet']['channelTitle']}", t, 'https://www.youtube.com/watch?v=' + v['id']

# TÜM DÜNYA (kullanıcı 17.11: ayırma, her yere bak): GDACS turuncu/kırmızı + her yanardağ, USGS M6+ deprem
def dunya():
    x = ET.fromstring(get('https://www.gdacs.org/xml/rss.xml'))
    g = '{http://www.gdacs.org}'
    simge = {'EQ':'🌋 Deprem','TC':'🌀 Kasırga/Tayfun','FL':'🌊 Sel','VO':'🌋 Yanardağ','WF':'🔥 Orman yangını','DR':'☀️ Kuraklık'}
    for it in x.iter('item'):
        tip = it.findtext(g + 'eventtype') or ''; sev = it.findtext(g + 'alertlevel') or ''
        ulke = it.findtext(g + 'country') or ''; t = it.findtext('title') or ''
        pub = it.findtext('pubDate') or ''
        try:
            if NOW - datetime.strptime(pub, '%a, %d %b %Y %H:%M:%S %Z').replace(tzinfo=timezone.utc) > timedelta(hours=48):
                continue
        except Exception:
            pass
        if sev in ('Orange', 'Red') or tip == 'VO':
            renk = '🔴 KIRMIZI' if sev == 'Red' else ('🟠 TURUNCU' if sev == 'Orange' else '🟢')
            yield (16 if sev == 'Red' else 10), f"gdacs:{it.findtext(g + 'eventid') or t}:{sev}", f"🌍 {ulke}: {simge.get(tip, tip)} — GDACS {renk}", t, it.findtext('link') or 'https://www.gdacs.org'
    d = json.loads(get('https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson'))
    for f in d['features']:
        pr = f['properties']
        if (pr.get('mag') or 0) >= 6.0:
            yield (14 if pr['mag'] >= 7 else 9), f"usgs:{f['id']}", f"🌍 DEPREM M{pr['mag']:.1f} — {pr.get('place','')}", (pr.get('alert') or '') and f"PAGER: {pr['alert']}", pr.get('url') or 'https://earthquake.usgs.gov'

RAKIP = {'GWN': 'UCSn-jzJf_LMbT8bAfHj92_Q', 'WeatherWatchUSA': 'UCm9RoJU7rc-bk-3SZzUksdQ'}
def rakip_videolar(cid):
    """Önce YouTube Data API (bulutta tek güvenilir yol), sonra RSS, en son yt-dlp. Son 6 video."""
    key = os.environ.get('YT_API_KEY')
    kf = os.path.join(os.path.dirname(D), '_assets', 'youtube_api_key.txt')
    if not key and os.path.exists(kf):
        key = open(kf).read().strip()
    if key:
        try:
            pl = json.loads(get('https://www.googleapis.com/youtube/v3/playlistItems?part=contentDetails&maxResults=6&playlistId=UU'
                                + cid[2:] + '&key=' + key))
            ids = ','.join(i['contentDetails']['videoId'] for i in pl['items'])
            vs = json.loads(get('https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics&id=' + ids + '&key=' + key))
            return [(v['snippet']['title'], datetime.fromisoformat(v['snippet']['publishedAt'].replace('Z', '+00:00')),
                     int(v['statistics'].get('viewCount', 0)), 'https://www.youtube.com/watch?v=' + v['id']) for v in vs['items']]
        except Exception:
            pass
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    try:
        x = ET.fromstring(get(f'https://www.youtube.com/feeds/videos.xml?channel_id={cid}'))
        out = []
        for e in x.findall('a:entry', ns):
            st = e.find('.//{http://search.yahoo.com/mrss/}statistics')
            out.append((e.findtext('a:title', '', ns), datetime.fromisoformat(e.findtext('a:published', '', ns).replace('Z', '+00:00')),
                        int(st.get('views', 0)) if st is not None else 0, e.find('a:link', ns).get('href')))
        return out
    except Exception:
        import subprocess
        r = subprocess.run([shutil.which('yt-dlp') or os.path.expanduser('~/.local/bin/yt-dlp'), '--skip-download', '--playlist-end', '6', '--no-warnings',
                            '--print', '%(timestamp)s|%(view_count)s|%(webpage_url)s|%(title)s',
                            f'https://www.youtube.com/channel/{cid}/videos'], capture_output=True, text=True, timeout=240)
        out = []
        for l in r.stdout.splitlines():
            ts, v, u, t = l.split('|', 3)
            if ts.isdigit():
                out.append((t, datetime.fromtimestamp(int(ts), timezone.utc), int(v) if v.isdigit() else 0, u))
        if not out:
            raise RuntimeError('rss+yt-dlp boş')
        return out

def rakip():
    for ad, cid in RAKIP.items():
        for t, pub, izl, url in rakip_videolar(cid):
            yas = NOW - pub
            saat = max(yas.total_seconds() / 3600, 0.25)
            # Kullanıcı 11.11: rakipte ~2 saatte 50K-100K olan konu HEMEN bizde yapılır (niş fark etmez)
            # Kullanıcı 16.11: rakip yeni konuya atlayınca HEMEN haber ver (izlenme beklemeden)
            if yas <= timedelta(hours=3):
                yield 12, f"rakipyeni:{url}", f"🆕 {ad} YENİ VİDEO ({saat:.1f} sa önce, {izl:,} izl) — konuya bak", t, url
            # 18.11 hacim modu: eşik düşürüldü (GWN 17-18.11: 43K-617K patlayanlar ilk saatlerde 5K/sa üstü)
            if yas <= timedelta(hours=4) and (izl >= 15000 or izl / saat >= 5000):
                yield 20, f"patla:{url}", f"🔥 PATLIYOR — {ad} {izl:,} izlenme / {saat:.1f} saat → HEMEN YAPALIM", t, url

def gonder(mesaj):
    if os.environ.get('TG_BOT_TOKEN'):  # bulut (GitHub Actions secrets)
        cfg = {'bot_token': os.environ['TG_BOT_TOKEN'], 'chat_id': os.environ['TG_CHAT_ID']}
    else:
        cfg = dict(l.strip().split('=', 1) for l in open(TG) if '=' in l)
    veri = urllib.parse.urlencode({'chat_id': cfg['chat_id'], 'text': mesaj, 'parse_mode': 'HTML',
                                   'disable_web_page_preview': 'true'}).encode()
    urllib.request.urlopen('https://api.telegram.org/bot' + cfg['bot_token'] + '/sendMessage', veri, timeout=30).read()

def main():
    try:
        gor = json.load(open(STATE))
    except Exception:
        gor = {}
    ilk = not gor
    yeni, hatalar = [], []
    na = []
    for kaynak in (nws, nwps, trends, dunya, rakip, avrupa, na_haber, na_deprem, na_rakip, na_youtube):
        try:
            for puan, key, baslik, detay, url in (kaynak() or []):
                if key not in gor:
                    gor[key] = DAY; (na if key.startswith('na:') else yeni).append((puan, baslik, detay, url))
        except Exception as e:
            hatalar.append(f'{kaynak.__name__}: {e}')
    # 3 günden eski kayıtları temizle
    sinir = (NOW - timedelta(days=3)).strftime('%Y-%m-%d')
    gor = {k: v for k, v in gor.items() if k.startswith('_') or v >= sinir}
    yeni.sort(key=lambda x: -x[0])
    zaman = datetime.now(TR).strftime('%d.%m %H:%M')
    if yeni:
        parca = [f'🌧️ <b>DÜNYA AFET RADARI</b> {zaman}' + (' (ilk tarama, şu an açık olanlar)' if ilk else '')]
        for puan, b, dt, u in yeni[:12]:
            parca.append(f'\n<b><a href="{html.escape(u)}">{html.escape(b)}</a></b>' + (f'\n{html.escape(dt)}' if dt else ''))
        mesaj = '\n'.join(parca)
        print(mesaj)
        if not DRY:
            gonder(mesaj[:4000])
    else:
        print(zaman, 'yeni yok')
    if na:
        na.sort(key=lambda x: -x[0])
        parca = [f'🇪🇺 <b>NATURE ALERT — AVRUPA RADARI</b> {zaman}' + (' (ilk tarama)' if ilk else '')]
        for puan, b, dt, u in na[:10]:
            parca.append(f'\n<b><a href="{html.escape(u)}">{html.escape(b)}</a></b>' + (f'\n{html.escape(dt)}' if dt else ''))
        mesaj = '\n'.join(parca)
        print(mesaj)
        if not DRY:
            gonder(mesaj[:4000])
    # Günlük 'hayattayım' mesajı (TR 10:00 sonrası ilk tarama): sessizlik = bozuk mu sorusu olmasın
    if datetime.now(TR).hour >= 10 and gor.get('_nabiz') != DAY:
        gor['_nabiz'] = DAY
        nabiz = f'✅ Dünya radarı (ABD + NATURE ALERT Avrupa haber/deprem/GWN/YouTube + GDACS) çalışıyor ({zaman}). Son 24 saatte {len([1 for k,v in gor.items() if not k.startswith("_") and v == DAY])} uyarı. Büyük olay olunca yazarım.'
        print(nabiz)
        if not DRY:
            gonder(nabiz)
    if hatalar:
        print('HATA:', hatalar)
    if not DRY:
        json.dump(gor, open(STATE, 'w'))

main()
